import fnmatch
import hashlib
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from importlib import resources
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from regen4x.params import RegenParams

_PRESET_KEYS = {"extends", "reset", "description", "status", "changelog"}
_PROFILE_KEYS = {"extends", "description", "rules", "alias"}
STATUSES = ("base", "stable", "experimental", "superseded")

#: Bare family names accepted where a preset name is expected: the preset the chosen profile uses for that kind of
#: texture (value: whether the texture has see-through pixels).
FAMILIES: Mapping[str, bool] = {"solid": False, "cutout": True}
_RULE_KEYS = {"path", "transparent", "preset", "keep_opaque"}


@dataclass(frozen=True, slots=True)
class Rule:
    """One line of a profile: the textures it applies to and what to do with them."""

    preset: str
    params: RegenParams
    path: str | None = None  #: glob on "/<namespace>/textures/<kind>/<name>.png"
    transparent: bool | None = None
    keep_opaque: bool = False

    @property
    def unconditional(self) -> bool:
        return self.path is None and self.transparent is None

    @property
    def when(self) -> str:
        """The condition in words, e.g. ``path */textures/block/* and see-through``."""
        parts = []
        if self.path:
            parts.append(f"path {self.path}")
        if self.transparent is not None:
            parts.append("see-through" if self.transparent else "solid")
        return " and ".join(parts) or "otherwise"

    def matches(self, rel_path: str, transparent: bool) -> bool:
        if self.transparent is not None and self.transparent != transparent:
            return False
        return self.path is None or fnmatch.fnmatchcase("/" + rel_path, self.path)


@dataclass(frozen=True, slots=True)
class Choice:
    """What a profile decided for one texture."""

    preset: str
    params: RegenParams
    keep_opaque: bool


@dataclass(frozen=True, slots=True)
class Profile:
    """An ordered list of rules; the first one that matches a texture wins."""

    name: str
    rules: tuple[Rule, ...]

    def choose_for(self, rel_path: str, transparent: bool) -> Choice:
        for rule in self.rules:
            if rule.matches(rel_path, transparent):
                return Choice(rule.preset, rule.params, rule.keep_opaque)
        raise LookupError(f"profile {self.name!r} has no rule for {rel_path!r}")

    def choose(self, rel_path: str, im: Image.Image) -> Choice:
        return self.choose_for(rel_path, has_transparency(im))

    def with_first(self, rules: Iterable[Rule]) -> "Profile":
        """The same profile with ``rules`` tried before its own."""
        return Profile(self.name, (*rules, *self.rules))


@dataclass(frozen=True, slots=True, eq=False)
class Book:
    """All presets and profiles that were loaded."""

    presets: dict[str, RegenParams]
    profiles: dict[str, Profile]
    parents: dict[str, str | None]
    notes: dict[str, str]
    origins: dict[str, dict[str, str]] = field(repr=False)
    statuses: dict[str, str] = field(default_factory=dict)
    changelogs: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  #: profile alias -> the profile it stands for

    def preset(self, name: str) -> RegenParams:
        try:
            return self.presets[name]
        except KeyError:
            raise KeyError(f"unknown preset {name!r}; known: {', '.join(self.presets)}") from None

    def profile(self, name: str) -> Profile:
        try:
            return self.profiles[self.aliases.get(name, name)]
        except KeyError:
            raise KeyError(f"unknown profile {name!r}; known: {', '.join([*self.profiles, *self.aliases])}") from None

    def resolve(self, name: str, profile: Profile) -> str:
        """``name`` itself, or for a bare family name (``solid``, ``cutout``) the preset ``profile`` uses for it."""
        if name not in self.presets and name in FAMILIES:
            return profile.choose_for("", FAMILIES[name]).preset
        return name

    def describe(self, name: str) -> str:
        """The settings of preset ``name`` that differ from the defaults, and which preset in its chain set each."""
        params = self.preset(name)
        chain = [name]
        while (parent := self.parents[chain[-1]]) is not None:
            chain.append(parent)
        lines = [f"{name}: {' -> '.join(reversed(chain))}"]
        if status := self.statuses.get(name):
            lines.append(f"  status: {status}")
        if changelog := self.changelogs.get(name):
            lines.append(f"  changes: {changelog}")
        if note := self.notes.get(name):
            lines.extend(f"  {line}" for line in note.splitlines())
        defaults = RegenParams()
        for f in fields(RegenParams):
            value = getattr(params, f.name)
            if value != getattr(defaults, f.name):
                lines.append(f"  {f.name} = {value!r}   [{self.origins[name].get(f.name, name)}]")
        return "\n".join(lines)


def _allowed(hint: Any) -> list[Any]:
    """The non-None alternatives of a type hint such as ``float | None``."""
    if get_origin(hint) in (Union, UnionType):
        return [t for t in get_args(hint) if t is not NoneType]
    return [hint]


def _coerce(where: str, option: str, value: object, hint: Any) -> object:
    """``value`` as the type of the RegenParams option, or a ValueError naming the option."""
    for t in _allowed(hint):
        if get_origin(t) is Literal:
            if value in get_args(t):
                return value
        elif t is bool:
            if isinstance(value, bool):
                return value
        elif t is int:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        elif t is float and isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    raise ValueError(f"{where}: option {option!r} cannot be {value!r} (expected {hint})")


def _check_keys(where: str, spec: Mapping[str, Any], known: set[str]) -> None:
    unknown = sorted(set(spec) - known)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {', '.join(map(repr, unknown))}")


class _Builder:
    """Resolves the raw TOML tables into presets and profiles."""

    def __init__(self, raw_presets: dict[str, dict[str, Any]], raw_profiles: dict[str, dict[str, Any]]) -> None:
        self.raw_presets = raw_presets
        self.raw_profiles = raw_profiles
        self.hints = get_type_hints(RegenParams)
        self.defaults = RegenParams()
        self.presets: dict[str, RegenParams] = {}
        self.origins: dict[str, dict[str, str]] = {}
        self.profiles: dict[str, Profile] = {}

    def preset(self, name: str, stack: tuple[str, ...] = ()) -> RegenParams:
        if name in self.presets:
            return self.presets[name]
        where = f"preset {name!r}"
        if name in stack:
            raise ValueError(f"{where}: extends itself ({' -> '.join((*stack, name))})")
        if name not in self.raw_presets:
            raise ValueError(f"{' -> '.join(stack) or 'presets'}: unknown preset {name!r}")
        spec = self.raw_presets[name]
        _check_keys(where, spec, _PRESET_KEYS | {f.name for f in fields(RegenParams)})
        parent = spec.get("extends")
        base = self.defaults if parent is None else self.preset(parent, (*stack, name))
        status = spec.get("status")
        if status is not None and status not in STATUSES:
            raise ValueError(f"{where}: status must be one of {', '.join(STATUSES)}, not {status!r}")
        origin = {} if parent is None else dict(self.origins[parent])
        resets = list(spec.get("reset", []))
        options = {k: v for k, v in spec.items() if k not in _PRESET_KEYS}
        values: dict[str, Any] = {}
        for option in resets:
            if option not in self.hints:
                raise ValueError(f"{where}: cannot reset unknown option {option!r}")
            if option in options:
                raise ValueError(f"{where}: option {option!r} is both set and reset")
            values[option] = getattr(self.defaults, option)
        for option, value in options.items():
            values[option] = _coerce(where, option, value, self.hints[option])
        origin.update(dict.fromkeys(values, name))
        self.origins[name] = origin
        self.presets[name] = replace(base, **values)
        return self.presets[name]

    def rule(self, where: str, spec: Mapping[str, Any]) -> Rule:
        _check_keys(where, spec, _RULE_KEYS)
        if "preset" not in spec:
            raise ValueError(f"{where}: a rule needs a 'preset'")
        path, transparent, keep = spec.get("path"), spec.get("transparent"), spec.get("keep_opaque", False)
        if path is not None and not isinstance(path, str):
            raise ValueError(f"{where}: 'path' must be a string")
        if transparent is not None and not isinstance(transparent, bool):
            raise ValueError(f"{where}: 'transparent' must be true or false")
        if not isinstance(keep, bool):
            raise ValueError(f"{where}: 'keep_opaque' must be true or false")
        if spec["preset"] not in self.raw_presets:
            raise ValueError(f"{where}: unknown preset {spec['preset']!r}")
        return Rule(spec["preset"], self.preset(spec["preset"]), path, transparent, keep)

    def profile(self, name: str, stack: tuple[str, ...] = ()) -> Profile:
        if name in self.profiles:
            return self.profiles[name]
        where = f"profile {name!r}"
        if name in stack:
            raise ValueError(f"{where}: extends itself ({' -> '.join((*stack, name))})")
        spec = self.raw_profiles[name]
        _check_keys(where, spec, _PROFILE_KEYS)
        if "alias" in spec:
            raise ValueError(f"{where}: an alias cannot be extended or used as a profile of its own")
        rules = [self.rule(f"{where} rule {i + 1}", r) for i, r in enumerate(spec.get("rules", []))]
        parent = spec.get("extends")
        if parent is not None:
            if parent not in self.raw_profiles:
                raise ValueError(f"{where}: unknown profile {parent!r}")
            rules.extend(self.profile(parent, (*stack, name)).rules)
        if not any(r.unconditional for r in rules):
            raise ValueError(f"{where}: needs a last rule without a condition (just a 'preset')")
        self.profiles[name] = Profile(name, tuple(rules))
        return self.profiles[name]


def parse_book(documents: Sequence[Mapping[str, Any]]) -> Book:
    """Presets and profiles from parsed TOML documents; a name may be defined in one document only."""
    raw_presets: dict[str, dict[str, Any]] = {}
    raw_profiles: dict[str, dict[str, Any]] = {}
    for doc in documents:
        _check_keys("file", doc, {"preset", "profile"})
        for kind, target in (("preset", raw_presets), ("profile", raw_profiles)):
            for name, spec in doc.get(kind, {}).items():
                if name in target:
                    raise ValueError(f"{kind} {name!r} is defined twice")
                target[name] = dict(spec)
    builder = _Builder(raw_presets, raw_profiles)
    for name in raw_presets:
        builder.preset(name)
    aliases: dict[str, str] = {}
    for name, spec in raw_profiles.items():
        if "alias" not in spec:
            continue
        _check_keys(f"profile {name!r}", spec, {"alias", "description"})
        if spec["alias"] not in raw_profiles or "alias" in raw_profiles[spec["alias"]]:
            raise ValueError(f"profile {name!r}: alias of {spec['alias']!r}, which is not a profile with rules")
        aliases[name] = spec["alias"]
    for name in raw_profiles:
        if name not in aliases:
            builder.profile(name)
    parents = {n: raw_presets[n].get("extends") for n in raw_presets}
    notes = {n: str(s["description"]) for n, s in {**raw_presets, **raw_profiles}.items() if "description" in s}
    statuses = {n: str(s["status"]) for n, s in raw_presets.items() if "status" in s}
    changelogs = {n: str(s["changelog"]) for n, s in raw_presets.items() if "changelog" in s}
    return Book(builder.presets, builder.profiles, parents, notes, builder.origins, statuses, changelogs, aliases)


def load_book(extra_files: Iterable[Path] = ()) -> Book:
    """The built-in presets and profiles plus those of ``extra_files`` (TOML, same format)."""
    documents = [tomllib.loads(resources.files("regen4x").joinpath("presets.toml").read_text(encoding="utf-8"))]
    for path in extra_files:
        try:
            documents.append(tomllib.loads(path.read_text(encoding="utf-8")))
        except (tomllib.TOMLDecodeError, OSError) as e:
            raise ValueError(f"{path}: {getattr(e, 'strerror', None) or e}") from e
    return parse_book(documents)


BOOK = load_book()

#: Every preset selectable by name from the command line.
PRESETS: dict[str, RegenParams] = BOOK.presets
PROFILES: dict[str, Profile] = BOOK.profiles
STANDARD_PROFILE = BOOK.profile("standard")

BASE_V1_0 = PRESETS["base-v1.0"]
ITEMS_DIAG_V1_0 = PRESETS["items-diag-v1.0"]
LINES_V1_0 = PRESETS["lines-v1.0"]
CUTOUT_V1_0 = PRESETS["cutout-v1.0"]
CUTOUT_V2_0 = PRESETS["cutout-v2.0"]
CUTOUT_V2_1 = PRESETS["cutout-v2.1"]
SOLID_V1_0 = PRESETS["solid-v1.0"]
SOLID_V1_1 = PRESETS["solid-v1.1"]
SOLID_V1_2 = PRESETS["solid-v1.2"]
SOLID_V1_3 = PRESETS["solid-v1.3"]
SOLID_V1_4 = PRESETS["solid-v1.4"]
SOLID_V1_5 = PRESETS["solid-v1.5"]
SOLID_V1_6 = PRESETS["solid-v1.6"]

#: What the standard profile ships: see-through textures -> SHIP_CUTOUT, solid ones -> SHIP_BLOCK.
SHIP_CUTOUT = STANDARD_PROFILE.choose_for("", True).params
SHIP_BLOCK = STANDARD_PROFILE.choose_for("", False).params


def seed_for(name: str) -> int:
    """Deterministic per-texture seed: same file name -> same output."""
    return int(hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()[:8], 16)


def has_transparency(im: Image.Image) -> bool:
    """True if any pixel is fully see-through (cut-out textures: items, plants, layered block overlays)."""
    a: NDArray[np.uint8] = np.asarray(im.convert("RGBA"))
    return bool((a[..., 3] == 0).any())


def ship_for(im: Image.Image) -> RegenParams:
    """The preset to ship for this texture under the standard profile."""
    return STANDARD_PROFILE.choose("", im).params


# Block textures are often layered (base + glowing cutout overlay on the same face).
# Smoothing may cut corners off thin opaque parts, which leaves real holes where the
# overlay is also clear (a 32px glowing overlay, say). For block-folder textures an
# opaque source pixel must stay fully opaque; its colour comes from the source pixel.
def keep_opaque(src: Image.Image, out: Image.Image) -> tuple[Image.Image, int]:
    """Restore every source-opaque pixel that the upscale made (partly) see-through. Returns (image, pixels fixed)."""
    s: NDArray[np.uint8] = np.asarray(src.convert("RGBA"))
    o: NDArray[np.uint8] = np.asarray(out.convert("RGBA")).copy()
    k = o.shape[0] // s.shape[0]
    big = np.kron(s, np.ones((k, k, 1), np.uint8))
    lost = (big[..., 3] > 0) & (o[..., 3] < big[..., 3])
    o[lost] = big[lost]
    return Image.fromarray(o), int(lost.sum())


def finish_choice(choice: Choice, src: Image.Image, out: Image.Image) -> Image.Image:
    """Post-step for output made with ``choice``: restore lost opaque pixels if the rule asks for it."""
    if choice.keep_opaque and has_transparency(src):
        return keep_opaque(src, out)[0]
    return out


def finish(rel_path: str, src: Image.Image, out: Image.Image) -> Image.Image:
    """Post-step for standard-profile output. rel_path like 'mymod/textures/block/x.png'."""
    return finish_choice(STANDARD_PROFILE.choose(rel_path, src), src, out)
