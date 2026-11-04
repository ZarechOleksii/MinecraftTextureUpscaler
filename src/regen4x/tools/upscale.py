"""Upscale textures from any input to any output.

Usage: regen4x-upscale INPUT -o OUTPUT [--update | --force] [--scale N] [--profile NAME] [options]

INPUT
  a .png                     one texture
  a folder of .png files     loose textures (sub-folders are kept)
  an extracted mod / pack    a folder with an assets/ folder inside
  a .jar or .zip             a mod, or a resource pack
  a folder of .jar files     every mod in it (--only PREFIX narrows it down)
OUTPUT
  a folder                   the upscaled PNGs (and their .mcmeta), existing files with the same name are replaced
  a .zip                     a new resource pack; an existing zip is refused unless --force (replace it) or
                             --update (keep its other entries, add / replace the upscaled ones)

Which preset a texture gets is decided by the profile (--profile, default "standard"; --list shows them), with
--blocks / --items / --use GLOB=PRESET in front of it. --presets FILE adds presets and profiles of your own.
Loose PNGs have no mod path, so path rules cannot match them and the texture's seed comes from its file name. Say what
they are with --kind (and --namespace) to get the seed and the rules a real texture of that mod would get.
"""

import argparse
import sys
from collections.abc import Sequence
from contextlib import ExitStack, closing
from pathlib import Path

from regen4x import presets
from regen4x.tools._io import DirSource, FolderSink, Sink, Source, ZipSink, ZipSource
from regen4x.tools.run_pack import Settings, add_common_arguments, execute

DEFAULT_FOLDERS = "block,item"


def open_sources(
    path: Path, *, only: Sequence[str], kind: str | None, namespace: str, parser: argparse.ArgumentParser
) -> list[Source]:
    """The sources an input path stands for."""
    if not path.exists():
        parser.error(f"input {path} does not exist")
    if path.is_file():
        if only:
            parser.error("--only is for a folder of jars")
        if path.suffix.lower() in {".jar", ".zip"}:
            return [ZipSource(path)]
        if path.suffix.lower() == ".png":
            return [DirSource(path, kind=kind, namespace=namespace)]
        parser.error(f"don't know what to do with {path} (expected .png, .jar, .zip or a folder)")
    jars = sorted(path.glob("*.jar"))
    if jars and not (path / "assets").is_dir():
        wanted = [j for j in jars if not only or j.name.startswith(tuple(only))]
        if not wanted:
            parser.error(f"no jar in {path} starts with {', '.join(only)}")
        return [ZipSource(j) for j in wanted]
    if only:
        parser.error("--only is for a folder of jars")
    return [DirSource(path, kind=kind, namespace=namespace)]


def override_rules(
    book: presets.Book, profile: presets.Profile, blocks: str | None, items: str | None, use: Sequence[str]
) -> list[presets.Rule]:
    """The rules in front of ``profile``: ``--use`` ones in the order given, then ``--blocks`` and ``--items``.

    A bare family name (``solid``, ``cutout``) stands for the preset ``profile`` uses for that kind of texture.
    """
    rules: list[presets.Rule] = []
    for spec in use:
        pattern, sep, name = spec.rpartition("=")
        if not sep or not pattern or not name:
            raise ValueError(f"--use wants GLOB=PRESET, not {spec!r}")
        name = book.resolve(name, profile)
        rules.append(presets.Rule(name, book.preset(name), path=pattern))
    if blocks:
        blocks = book.resolve(blocks, profile)
        rules.append(presets.Rule(blocks, book.preset(blocks), path="*/textures/block/*", keep_opaque=True))
    if items:
        items = book.resolve(items, profile)
        rules.append(presets.Rule(items, book.preset(items), path="*/textures/item/*"))
    return rules


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def list_book(book: presets.Book) -> str:
    lines = ["presets:"]
    for n in book.presets:
        status = book.statuses.get(n)
        lines.append(f"  {n}{f' [{status}]' if status else ''}  {first_line(book.notes.get(n, ''))}".rstrip())
    lines.append("profiles:")
    lines += [f"  {alias}  = {target}" for alias, target in book.aliases.items()]
    for name, profile in book.profiles.items():
        lines.append(f"  {name}  {first_line(book.notes.get(name, ''))}".rstrip())
        for rule in profile.rules:
            keep = " (keep opaque)" if rule.keep_opaque else ""
            lines.append(f"    {rule.when}: {rule.preset}{keep}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="regen4x-upscale INPUT -o OUTPUT [options]",
    )
    parser.add_argument("input", nargs="?", type=Path, help="a png, a folder, a mod / pack folder, a jar or zip")
    parser.add_argument("-o", "--output", type=Path, help="a folder, or a .zip resource pack")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="add to / replace entries in the existing output zip")
    mode.add_argument("--force", action="store_true", help="replace the existing output zip")
    add_common_arguments(parser)
    parser.add_argument(
        "--blocks",
        metavar="PRESET",
        help="preset for textures/block (instead of the profile; `solid` and `cutout` name the profile's own)",
    )
    parser.add_argument("--items", metavar="PRESET", help="preset for textures/item (instead of the profile)")
    parser.add_argument(
        "--use",
        action="append",
        default=[],
        metavar="GLOB=PRESET",
        help='preset for the textures whose "/<ns>/textures/<kind>/<name>.png" matches GLOB; repeatable',
    )
    parser.add_argument(
        "--folders",
        default=DEFAULT_FOLDERS,
        metavar="A,B",
        help=f"texture folders to take from jars and packs (default {DEFAULT_FOLDERS}; loose files are all taken)",
    )
    parser.add_argument("--only", action="append", default=[], metavar="PREFIX", help="mods folder: only these jars")
    parser.add_argument("--kind", metavar="KIND", help="loose PNGs: they are textures/KIND of --namespace (e.g. block)")
    parser.add_argument(
        "--namespace", default="minecraft", metavar="NS", help="loose PNGs with --kind (default minecraft)"
    )
    parser.add_argument("--list", action="store_true", help="list the presets and profiles and exit")
    parser.add_argument(
        "--describe", metavar="PRESET", help="show what a preset sets, and where it comes from, and exit"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        book = presets.load_book(args.presets)
        if args.list:
            print(list_book(book))
            return 0
        chosen = book.profile(args.profile)
        if args.describe:
            print(book.describe(book.resolve(args.describe, chosen)))
            return 0
        profile = chosen.with_first(override_rules(book, chosen, args.blocks, args.items, args.use))
        settings = Settings(profile, args.scale, tuple(f for f in args.folders.split(",") if f))
    except (KeyError, ValueError) as e:
        return parser.error(str(e.args[0]))
    if args.input is None or args.output is None:
        parser.error("INPUT and -o OUTPUT are required")
    output: Path = args.output
    sink: Sink
    if output.suffix.lower() == ".zip":
        if output.exists() and not (args.update or args.force):
            parser.error(f"{output} exists; add --update to add to it or --force to replace it")
        if args.update and not output.exists():
            parser.error(f"--update: {output} does not exist")
        sink = ZipSink(output, update=args.update, description=f"{settings.tile}x regen4x: {args.input.name}")
    else:
        if args.update or args.force:
            parser.error("--update and --force are for a .zip output")
        if output.is_file():
            parser.error(f"{output} is a file; give a folder or a .zip")
        sink = FolderSink(output)
    with ExitStack() as stack:
        sources = [
            stack.enter_context(closing(s))
            for s in open_sources(args.input, only=args.only, kind=args.kind, namespace=args.namespace, parser=parser)
        ]
        if args.input.suffix.lower() == ".png" and not args.kind and isinstance(sink, ZipSink):
            print("note: without --kind the zip gets the bare file name, not an assets/... path", file=sys.stderr)
        return execute(sources, sink, settings, budget=args.budget, cache_dir=args.cache_dir, report=output)


if __name__ == "__main__":
    raise SystemExit(main())
