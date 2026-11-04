"""Interactive front end for regen4x-upscale: asks what to upscale, how big and where to put it, prints the one command
that does it, and runs it.

Usage: regen4x-wizard [--presets FILE ...] [--dry-run]

It asks, in order: the input (a texture, a folder, a mod or pack, a folder of mod jars), what loose textures are, the
size (2..8 times), the profile, whether to pick the block / item presets yourself, and the output (a folder or a .zip
resource pack; an existing zip can be updated or replaced). Every question has a default: press Enter to take it.
The command it prints is a plain ``regen4x-upscale`` call, so you can run it again later without the questions.
"""

import argparse
import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from regen4x import presets
from regen4x.tools import upscale
from regen4x.tools.run_pack import MAX_SCALE, MIN_SCALE

type Ask = Callable[[str], str]
type Say = Callable[[str], None]

PROFILE_DECIDES = "(profile decides)"
DEFAULT_SCALE = 4
TILE = 16


@dataclass(frozen=True, slots=True)
class Input:
    """What the input path is, as far as the questions are concerned."""

    path: Path
    mods: bool  #: a folder of mod jars (--only applies)
    loose: bool  #: loose PNGs, with no mod path (--kind and --namespace apply)


def classify(path: Path) -> Input | None:
    """The kind of input ``path`` is, or None if regen4x-upscale cannot take it."""
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in {".jar", ".zip"}:
            return Input(path, mods=False, loose=False)
        if suffix == ".png":
            return Input(path, mods=False, loose=True)
        return None
    if not path.is_dir():
        return None
    has_assets = (path / "assets").is_dir()
    if not has_assets and any(path.glob("*.jar")):
        return Input(path, mods=True, loose=False)
    return Input(path, mods=False, loose=not has_assets)


class Prompter:
    """The few kinds of question the wizard asks; ``ask`` is ``input`` and ``say`` is ``print`` in real use."""

    def __init__(self, ask: Ask, say: Say) -> None:
        self.ask = ask
        self.say = say

    def text(self, question: str, default: str | None = None) -> str:
        """A line of text. Without a default an answer is required; an empty default allows an empty answer."""
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self.ask(f"{question}{suffix}: ").strip()
            if answer:
                return answer
            if default is not None:
                return default
            self.say("  Please enter a value.")

    def path(self, question: str, default: str | None = None) -> Path:
        """A path; quotes (as pasted from a file manager) and ``~`` are handled."""
        return Path(self.text(question, default).strip("\"'")).expanduser()

    def yes_no(self, question: str, default: bool) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self.ask(f"{question} [{hint}]: ").strip().lower()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self.say("  Please answer y or n.")

    def integer(self, question: str, low: int, high: int, default: int) -> int:
        while True:
            answer = self.text(f"{question} ({low}..{high})", str(default))
            if answer.isdigit() and low <= int(answer) <= high:
                return int(answer)
            self.say(f"  Please enter a whole number from {low} to {high}.")

    def choose(self, question: str, options: Sequence[tuple[str, str]], default: str) -> str:
        """One of ``options`` (name, description), picked by number or by name."""
        names = [name for name, _ in options]
        width = max(len(name) for name in names)
        self.say(question)
        for number, (name, description) in enumerate(options, 1):
            mark = " (default)" if name == default else ""
            self.say(f"  {number}. {name.ljust(width)}  {description}{mark}".rstrip())
        while True:
            answer = self.text("Choose", str(names.index(default) + 1))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return names[int(answer) - 1]
            by_name = {name.lower(): name for name in names}
            if answer.lower() in by_name:
                return by_name[answer.lower()]
            self.say(f"  Please enter a number from 1 to {len(options)}, or a name from the list.")


def ask_input(p: Prompter) -> Input:
    while True:
        path = p.path("Input: a .png, a folder, a mod / pack (.jar, .zip or folder), or a folder of mod jars")
        found = classify(path)
        if found is not None:
            return found
        if path.exists():
            p.say(f"  Don't know what to do with {path}: expected a .png, .jar, .zip or a folder.")
        else:
            p.say(f"  {path} does not exist.")


def ask_only(p: Prompter, folder: Path) -> list[str]:
    """Which jars of a mods folder to take: the name prefixes, or all."""
    jars = sorted(j.name for j in folder.glob("*.jar"))
    p.say(f"  {len(jars)} jars in {folder}.")
    while True:
        answer = p.text("Only jars whose name starts with (comma separated; Enter for all)", "")
        prefixes = [x.strip() for x in answer.split(",") if x.strip()]
        if not prefixes or any(j.startswith(tuple(prefixes)) for j in jars):
            return prefixes
        p.say("  No jar starts with that.")


def ask_kind(p: Prompter) -> list[str]:
    """What loose textures are: they get the seed and the rules of a real texture of that mod."""
    kind = p.choose(
        "What are these textures?",
        [
            ("block", "textures/block of a mod"),
            ("item", "textures/item of a mod"),
            ("unsure", "no mod path: the zip gets bare file names"),
        ],
        "block",
    )
    if kind == "unsure":
        return []
    namespace = p.text("Mod id (the folder under assets/, e.g. mymod)", "minecraft")
    return ["--kind", kind, "--namespace", namespace]


def describe_preset(book: presets.Book, name: str) -> str:
    return upscale.first_line(book.notes.get(name, ""))


def ask_presets(p: Prompter, book: presets.Book) -> list[str]:
    """Optionally a preset for blocks and one for items, in front of the profile's own rules."""
    if not p.yes_no("Pick the block / item presets yourself instead of the profile's?", False):
        return []
    options = [(PROFILE_DECIDES, "use the profile's rule"), *((n, describe_preset(book, n)) for n in book.presets)]
    flags: list[str] = []
    for flag, what in (("--blocks", "blocks"), ("--items", "items")):
        name = p.choose(f"Preset for {what}:", options, PROFILE_DECIDES)
        if name != PROFILE_DECIDES:
            flags += [flag, name]
    return flags


def ask_output(p: Prompter, source: Input, scale: int) -> tuple[Path, list[str]]:
    """The output and the flags it needs (--update / --force for an existing zip)."""
    tag = f"_{TILE * scale}x"
    default = source.path.with_name(f"{source.path.stem if source.path.is_file() else source.path.name}{tag}.zip")
    while True:
        out = p.path("Output: a .zip resource pack, or a folder", str(default))
        if out.suffix.lower() != ".zip":
            if out.is_file():
                p.say(f"  {out} is a file: give a folder or a .zip.")
                continue
            return out, []
        if out.is_dir():
            p.say(f"  {out} is a folder: give a .zip name.")
            continue
        if not out.exists():
            return out, []
        action = p.choose(
            f"{out} already exists. What now?",
            [
                ("update", "keep its other entries, add or replace the upscaled ones"),
                ("replace", "start the pack over"),
                ("other", "choose another output"),
            ],
            "update",
        )
        if action == "update":
            return out, ["--update"]
        if action == "replace":
            return out, ["--force"]


def gather(p: Prompter, book: presets.Book, extra_presets: Sequence[Path]) -> list[str]:
    """Ask everything and return the arguments for ``regen4x-upscale``."""
    source = ask_input(p)
    only = ask_only(p, source.path) if source.mods else []
    kind = ask_kind(p) if source.loose else []
    scale = p.integer("Size: how many times bigger", MIN_SCALE, MAX_SCALE, DEFAULT_SCALE)
    p.say(f"  {TILE}px textures become {TILE * scale}px.")
    profile = p.choose(
        "Profile: which preset for which texture",
        [(name, describe_preset(book, name)) for name in [*book.aliases, *book.profiles]],
        "standard",
    )
    chosen = ask_presets(p, book)
    out, mode = ask_output(p, source, scale)
    argv = [str(source.path), "-o", str(out), *mode, "--scale", str(scale), "--profile", profile, *kind, *chosen]
    for prefix in only:
        argv += ["--only", prefix]
    for file in extra_presets:
        argv += ["--presets", str(file)]
    return argv


def format_command(argv: Sequence[str]) -> str:
    """``regen4x-upscale`` with ``argv``, quoted for the shell the user is in."""
    quoted = subprocess.list2cmdline(list(argv)) if os.name == "nt" else shlex.join(argv)
    return f"regen4x-upscale {quoted}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--presets", action="append", default=[], type=Path, metavar="FILE", help="extra presets / profiles (TOML)"
    )
    parser.add_argument("--dry-run", action="store_true", help="ask the questions and print the command, don't run it")
    args = parser.parse_args(argv)
    try:
        book = presets.load_book(args.presets)
    except (KeyError, ValueError) as e:
        return parser.error(str(e.args[0]))
    prompter = Prompter(input, print)
    try:
        command = gather(prompter, book, args.presets)
        print(f"\nThis is the command:\n\n  {format_command(command)}\n")
        if args.dry_run:
            return 0
        if not prompter.yes_no("Run it now?", True):
            print("Not run.")
            return 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 1
    return upscale.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
