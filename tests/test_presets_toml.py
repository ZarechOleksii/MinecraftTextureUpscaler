import dataclasses
import re
import tomllib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from regen4x import presets
from regen4x.params import RegenParams


def book(*documents: str) -> presets.Book:
    return presets.parse_book([tomllib.loads(d) for d in documents])


def image(*, see_through: bool) -> Image.Image:
    a = np.full((16, 16, 4), 255, np.uint8)
    if see_through:
        a[0, 0, 3] = 0
    return Image.fromarray(a)


# ---- presets ---------------------------------------------------------------------------------------------------------


def test_a_preset_without_extends_starts_from_the_defaults() -> None:
    p = book("[preset.A]\nthr = 0.5\nkeep_gaps = true").presets["A"]
    assert p == dataclasses.replace(RegenParams(), thr=0.5, keep_gaps=True)


def test_extends_adds_to_the_parent_and_leaves_it_alone() -> None:
    b = book("[preset.A]\nthr = 0.5\n[preset.B]\nextends = 'A'\nline_field = true")
    assert b.presets["B"].thr == 0.5
    assert b.presets["B"].line_field is True
    assert b.presets["A"].line_field is False


def test_a_child_can_switch_off_what_its_parent_switched_on() -> None:
    b = book("[preset.A]\nline_field = true\n[preset.B]\nextends = 'A'\nline_field = false")
    assert b.presets["B"].line_field is False


def test_reset_puts_options_back_to_their_defaults() -> None:
    b = book(
        "[preset.A]\nthr = 0.5\nadaptive_smooth = 3\nline_bend = 'both'\n"
        "[preset.B]\nextends = 'A'\nreset = ['adaptive_smooth', 'line_bend', 'thr']"
    )
    assert b.presets["A"].adaptive_smooth == 3
    assert (b.presets["B"].adaptive_smooth, b.presets["B"].line_bend, b.presets["B"].thr) == (None, None, 0.13)


def test_the_order_of_the_file_does_not_matter() -> None:
    b = book("[preset.B]\nextends = 'A'\n[preset.A]\nthr = 0.5")
    assert b.presets["B"].thr == 0.5


def test_whole_numbers_are_accepted_for_float_options() -> None:
    p = book("[preset.A]\nsmooth = 3").presets["A"]
    assert p.smooth == 3.0
    assert isinstance(p.smooth, float)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("[preset.A]\nthr_typo = 1", "unknown key(s) 'thr_typo'"),
        ("[preset.A]\nthr = 'high'", "option 'thr' cannot be 'high'"),
        ("[preset.A]\nkeep_gaps = 1", "option 'keep_gaps' cannot be 1"),
        ("[preset.A]\nmerge_size = 1.5", "option 'merge_size' cannot be 1.5"),
        ("[preset.A]\nthr = true", "option 'thr' cannot be True"),
        ("[preset.A]\nline_bend = 'sideways'", "option 'line_bend' cannot be 'sideways'"),
        ("[preset.A]\nextends = 'B'", "unknown preset 'B'"),
        ("[preset.A]\nextends = 'B'\n[preset.B]\nextends = 'A'", "extends itself"),
        ("[preset.A]\nreset = ['nope']", "cannot reset unknown option 'nope'"),
        ("[preset.A]\nthr = 0.5\nreset = ['thr']", "both set and reset"),
        ("[nonsense.A]\nthr = 1", "unknown key(s) 'nonsense'"),
    ],
)
def test_mistakes_are_refused_with_a_message(toml: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        book(toml)


def test_a_name_may_be_defined_only_once() -> None:
    with pytest.raises(ValueError, match="preset 'A' is defined twice"):
        book("[preset.A]\nthr = 1", "[preset.A]\nthr = 2")


def test_describe_names_the_preset_that_set_each_option() -> None:
    b = book("[preset.A]\ndescription = 'base'\nthr = 0.5\n[preset.B]\nextends = 'A'\nkeep_gaps = true")
    text = b.describe("B")
    assert text.splitlines()[0] == "B: A -> B"
    assert "  thr = 0.5   [A]" in text
    assert "  keep_gaps = True   [B]" in text
    assert "base" in b.describe("A")
    with pytest.raises(KeyError, match="unknown preset 'C'"):
        b.preset("C")


# ---- profiles --------------------------------------------------------------------------------------------------------

PROFILES = """
[preset.SOLID]
thr = 0.1
[preset.CUT]
thr = 0.2
[preset.SPECIAL]
thr = 0.3
[profile.p]
rules = [
    { path = "*/textures/block/*", transparent = true, preset = "SPECIAL", keep_opaque = true },
    { transparent = true, preset = "CUT" },
    { preset = "SOLID" },
]
"""


def test_the_first_matching_rule_wins() -> None:
    p = book(PROFILES).profile("p")
    cut, solid = image(see_through=True), image(see_through=False)
    assert p.choose("m/textures/block/x.png", cut) == presets.Choice("SPECIAL", book(PROFILES).presets["SPECIAL"], True)
    assert p.choose("m/textures/item/x.png", cut).preset == "CUT"
    assert p.choose("m/textures/block/x.png", solid).preset == "SOLID"
    assert p.choose("x.png", solid).preset == "SOLID"
    assert not p.choose("m/textures/item/x.png", cut).keep_opaque


def test_path_globs_see_the_whole_path_from_the_namespace_on() -> None:
    rule = presets.Rule("X", RegenParams(), path="*/textures/block/*")
    assert rule.matches("mymod/textures/block/a/b.png", False)
    assert not rule.matches("mymod/textures/item/a.png", False)
    assert not rule.matches("a.png", False)


def test_a_profile_extends_by_appending_the_rules_of_its_parent() -> None:
    b = book(PROFILES + "[profile.q]\nextends = 'p'\nrules = [{ path = '*/item/*', preset = 'SPECIAL' }]")
    q = b.profile("q")
    assert [r.preset for r in q.rules] == ["SPECIAL", "SPECIAL", "CUT", "SOLID"]
    assert q.choose_for("m/textures/item/x.png", False).preset == "SPECIAL"
    assert q.choose_for("m/textures/block/x.png", False).preset == "SOLID"


def test_rules_can_be_put_in_front_of_a_profile() -> None:
    p = book(PROFILES).profile("p")
    front = presets.Rule("CUT", p.rules[1].params, path="*/textures/item/*")
    assert p.with_first([front]).choose_for("m/textures/item/x.png", False).preset == "CUT"
    assert p.choose_for("m/textures/item/x.png", False).preset == "SOLID"  # the original is unchanged


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("[profile.p]\nrules = [{ transparent = true, preset = 'CUT' }]", "needs a last rule without a condition"),
        ("[profile.p]\nrules = [{ preset = 'NOPE' }]", "unknown preset 'NOPE'"),
        ("[profile.p]\nrules = [{ transparent = true }]", "a rule needs a 'preset'"),
        ("[profile.p]\nrules = [{ preset = 'CUT', colour = 1 }]", "unknown key"),
        ("[profile.p]\nrules = [{ preset = 'CUT', transparent = 'yes' }]", "'transparent' must be true or false"),
        ("[profile.p]\nrules = [{ preset = 'CUT', path = 3 }]", "'path' must be a string"),
        ("[profile.p]\nrules = [{ preset = 'CUT', keep_opaque = 1 }]", "'keep_opaque' must be true or false"),
        ("[profile.p]\nextends = 'nope'\nrules = [{ preset = 'CUT' }]", "unknown profile 'nope'"),
        ("[profile.p]\nextends = 'q'\n[profile.q]\nextends = 'p'", "extends itself"),
    ],
)
def test_profile_mistakes_are_refused(toml: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        book("[preset.CUT]\nthr = 0.2\n" + toml)


# ---- the built-in file and extra files -------------------------------------------------------------------------------


def test_the_default_profile_ships_what_the_old_code_shipped() -> None:
    assert presets.STANDARD_PROFILE.choose_for("m/textures/item/x.png", True).preset == "cutout-v2.1"
    assert presets.STANDARD_PROFILE.choose_for("m/textures/block/x.png", True).keep_opaque
    assert not presets.STANDARD_PROFILE.choose_for("m/textures/item/x.png", True).keep_opaque
    assert presets.STANDARD_PROFILE.choose_for("m/textures/block/x.png", False).preset == "solid-v1.6"
    assert (
        presets.PROFILES["legacy-cutout-v1-r1"].choose_for("m/textures/item/x.png", True).params is presets.CUTOUT_V1_0
    )
    assert (
        presets.PROFILES["legacy-cutout-v1-r1"].choose_for("m/textures/item/x.png", False).params is presets.SOLID_V1_6
    )


def test_an_extra_file_can_build_on_the_built_in_presets(tmp_path: Path) -> None:
    extra = tmp_path / "mine.toml"
    extra.write_text(
        "[preset.MY_BLOCK]\nextends = 'solid-v1.6'\nreset = ['line_thru']\nsmooth = 2.6\n"
        "[profile.mine]\nrules = [{ preset = 'MY_BLOCK' }]\n",
        encoding="utf-8",
    )
    b = presets.load_book([extra])
    assert b.presets["MY_BLOCK"] == dataclasses.replace(presets.SOLID_V1_6, smooth=2.6, line_thru=False)
    assert b.profile("mine").choose_for("a.png", True).preset == "MY_BLOCK"
    assert "MY_BLOCK" not in presets.PRESETS  # the built-in book is not touched


def test_an_extra_file_may_not_redefine_a_built_in_preset(tmp_path: Path) -> None:
    extra = tmp_path / "mine.toml"
    extra.write_text('[preset."base-v1.0"]\nthr = 1\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"preset 'base-v1.0' is defined twice"):
        presets.load_book([extra])


def test_a_broken_file_is_named_in_the_error(tmp_path: Path) -> None:
    extra = tmp_path / "broken.toml"
    extra.write_text("[preset.A\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"broken\.toml"):
        presets.load_book([extra])


# ---- naming and versioning (docs/versioning.md) ----------------------------------------------------------------------

NAME = re.compile(r"(?P<family>[a-z]+(?:-[a-z]+)*)-v(?P<major>\d+)\.(?P<minor>\d+)")
PROFILE_NAME = re.compile(r"[a-z]+(-[a-z0-9]+)*-r\d+")


def test_built_in_preset_names_are_family_dash_version() -> None:
    assert all(NAME.fullmatch(n) for n in presets.PRESETS), list(presets.PRESETS)


def test_built_in_profile_names_are_name_dash_release_or_an_alias() -> None:
    assert all(PROFILE_NAME.fullmatch(n) for n in presets.BOOK.profiles)
    assert all(a in presets.BOOK.profiles or a not in presets.BOOK.aliases.values() for a in presets.BOOK.aliases)


def test_every_built_in_preset_has_a_status_and_a_changelog() -> None:
    b = presets.BOOK
    assert set(b.statuses) == set(b.presets) == set(b.changelogs)
    assert set(b.statuses.values()) <= set(presets.STATUSES)
    assert all(text.strip() and "\n" not in text for text in b.changelogs.values())


def test_a_child_has_a_higher_version_than_its_parent_in_the_same_family() -> None:
    for name, parent in presets.BOOK.parents.items():
        if parent is None:
            continue
        child, base = NAME.fullmatch(name), NAME.fullmatch(parent)
        assert child and base
        if child[1] == base[1]:  # same family: the number must go up
            assert (int(child[2]), int(child[3])) > (int(base[2]), int(base[3])), name


def test_the_standard_profile_ships_only_stable_presets_and_all_stable_ones_are_shipped() -> None:
    b = presets.BOOK
    shipped = {r.preset for r in b.profile("standard").rules}
    assert {b.statuses[n] for n in shipped} == {"stable"}
    assert {n for n, s in b.statuses.items() if s == "stable"} == shipped


def test_experimental_and_base_presets_are_not_shipped_by_any_profile() -> None:
    b = presets.BOOK
    shipped = {r.preset for p in b.profiles.values() for r in p.rules}
    assert not {n for n, s in b.statuses.items() if s in ("base", "experimental")} & shipped


def test_a_profile_alias_is_another_name_for_the_same_profile() -> None:
    assert presets.BOOK.aliases == {"standard": "standard-r1"}
    assert presets.BOOK.profile("standard") is presets.BOOK.profile("standard-r1")
    assert "standard" not in presets.PROFILES  # aliases are not profiles of their own
    with pytest.raises(KeyError, match="standard"):
        presets.BOOK.profile("nope")


def test_a_bare_family_name_means_what_the_profile_uses() -> None:
    b = presets.BOOK
    standard, legacy = b.profile("standard"), b.profile("legacy-cutout-v1-r1")
    assert b.resolve("solid", standard) == "solid-v1.6"
    assert b.resolve("cutout", standard) == "cutout-v2.1"
    assert b.resolve("cutout", legacy) == "cutout-v1.0"
    assert b.resolve("solid-v1.2", standard) == "solid-v1.2"  # a full name is left alone
    assert b.resolve("MINE", standard) == "MINE"  # so is an unknown one (the caller reports it)


def test_a_preset_called_like_a_family_wins_over_the_family_name() -> None:
    b = book('[preset.solid]\nthr = 1\n[profile.p]\nrules = [{ preset = "solid" }]\n')
    assert b.resolve("solid", b.profile("p")) == "solid"


def test_a_bad_status_is_refused() -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        book('[preset.A]\nstatus = "final"\n')


@pytest.mark.parametrize(
    ("profiles", "message"),
    [
        ('[profile.a]\nalias = "zz"\n', "not a profile with rules"),
        ('[profile.a]\nalias = "b"\n[profile.b]\nalias = "a"\n', "not a profile with rules"),
        ('[profile.a]\nalias = "b"\nrules = []\n[profile.b]\nrules = [{ preset = "P" }]\n', "unknown key"),
        ('[profile.b]\nrules = [{ preset = "P" }]\n[profile.a]\nalias = "b"\n[profile.c]\nextends = "a"\n', "alias"),
    ],
)
def test_a_profile_alias_must_point_at_a_real_profile(profiles: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        book("[preset.P]\nthr = 1\n" + profiles)
