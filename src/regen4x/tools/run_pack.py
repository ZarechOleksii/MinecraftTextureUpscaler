import argparse
import hashlib
import io
import logging
import multiprocessing
import os
import sys
import time
import traceback
from collections.abc import Sequence
from contextlib import ExitStack, closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import numpy as np
from PIL import Image

from regen4x import ct, presets
from regen4x.tools._io import PACK_FORMAT, Sink, Source, ZipSink, ZipSource
from regen4x.upscaler import regen4x

__all__ = [
    "PACK_FORMAT",
    "Budget",
    "Cache",
    "OutOfTimeError",
    "PackBuilder",
    "Settings",
    "Stats",
    "code_hash",
    "execute",
]

#: The upscaler library (every module directly in the package, i.e. not the tools): its source decides the cache.
CODE_DIR = Path(__file__).resolve().parents[1]
MAX_WORKERS = 4
TILE = ct.T  # side of a source texture (px)
MIN_SCALE, MAX_SCALE = 2, 8

log = logging.getLogger("run_pack")


def code_hash() -> str:
    """Hash of the upscaler sources: a code change starts a new cache folder."""
    files = [f for f in sorted(CODE_DIR.glob("*.py")) if f.name != "__init__.py"] + sorted(CODE_DIR.glob("*.toml"))
    data = b"".join(f.read_bytes() for f in files)
    return hashlib.md5(data, usedforsecurity=False).hexdigest()[:10]


class OutOfTimeError(Exception):
    """The --budget ran out; finished work is cached, run again to continue."""


@dataclass(slots=True)
class Budget:
    """Stop cleanly before ``seconds`` have passed since creation (``None`` = unlimited)."""

    seconds: float | None = None
    start: float = 0.0

    def __post_init__(self) -> None:
        self.start = time.monotonic()

    def check(self) -> None:
        if self.seconds is not None and time.monotonic() - self.start > self.seconds:
            raise OutOfTimeError


class Cache:
    """Finished outputs; a code change starts a new cache folder (see :func:`code_hash`)."""

    def __init__(self, root: Path, code: str) -> None:
        self.dir = root / code

    @staticmethod
    def _digest(rel: str, data: bytes, salt: str) -> str:
        return hashlib.md5(rel.encode() + b"|" + data + b"|" + salt.encode(), usedforsecurity=False).hexdigest()

    def path(self, rel: str, data: bytes, salt: str = "") -> Path:
        """Cache file for a texture. ``salt`` = everything besides the texture that changes the result."""
        return self.dir / f"{self._digest(rel, data, salt)}.png"

    @staticmethod
    def get(path: Path) -> Image.Image | None:
        if path.exists() and path.stat().st_size > 0:
            with Image.open(path) as im:
                return im.convert("RGBA")
        return None

    def put(self, path: Path, im: Image.Image) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            im.save(fh, "PNG")


@dataclass(slots=True)
class Stats:
    done: int = 0
    skipped: int = 0
    failed: int = 0
    items: int = 0
    blocks: int = 0
    anims: int = 0
    scrolls: int = 0
    linked: int = 0
    unpaired: int = 0
    pairs: int = 0
    cts: int = 0


@dataclass(frozen=True, slots=True)
class Settings:
    """What to upscale with: the profile that picks the preset per texture, the scale factor, the texture folders."""

    profile: presets.Profile = presets.STANDARD_PROFILE
    scale: int = 4
    folders: tuple[str, ...] = ("block", "item")

    def __post_init__(self) -> None:
        if not MIN_SCALE <= self.scale <= MAX_SCALE:
            raise ValueError(f"scale must be {MIN_SCALE}..{MAX_SCALE}, not {self.scale}")

    @property
    def tile(self) -> int:
        """Side of an upscaled 16px texture (px)."""
        return TILE * self.scale

    @property
    def salt(self) -> str:
        """Part of every cache key: the same texture under another profile or scale is another result."""
        return f"{self.scale}|{self.profile.rules!r}"


class Entry(NamedTuple):
    """An upscaled texture and the 16px source it came from (``None`` for connected-texture sheets)."""

    out: Image.Image
    src: Image.Image | None


class CtJob(NamedTuple):
    name: str
    sheet: bytes
    base: bytes
    base_up: bytes
    rel: str
    settings: Settings


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load_rgba(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGBA")


def ct_job(job: CtJob) -> tuple[str, bytes]:
    """Connected-texture sheet -> xscale (see ct.py). Runs in a worker process."""
    sheet, base, base_up = load_rgba(job.sheet), load_rgba(job.base), load_rgba(job.base_up)
    out = ct.upscale_sheet(sheet, base, base_up, job.rel, job.settings.scale, job.settings.profile)[0]
    return job.name, png_bytes(out)


class PackBuilder:
    """Upscales every handled texture of the sources and writes the results to the sink."""

    def __init__(self, sources: Sequence[Source], sink: Sink, settings: Settings, budget: Budget, cache: Cache) -> None:
        self.sources = tuple(sources)
        self.sink = sink
        self.settings = settings
        self.budget = budget
        self.cache = cache
        self.stats = Stats()
        self.t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def build(self) -> str:
        """Upscale everything into the sink (the caller commits it) and return the summary line."""
        log.info("sources: %s", [src.label for src in self.sources])
        for src in self.sources:
            self._process_source(src)
        s = self.stats
        return (
            f"FINISHED upscaled {s.done} (items/cutouts {s.items}, solid blocks {s.blocks}, animations {s.anims}, "
            f"scroll strips {s.scrolls}, stills cut from strips {s.linked}, shift pairs {s.pairs}, "
            f"unpaired kept original {s.unpaired}, connected sheets {s.cts}), skipped {s.skipped} (other sizes), "
            f"failed {s.failed}, {self.elapsed:.0f}s"
        )

    def upscale(self, im: Image.Image, rel: str) -> tuple[Image.Image, presets.Choice]:
        """One 16x16 texture -> 16*scale (cached)."""
        st = self.settings
        choice = st.profile.choose(rel, im)
        cache_path = self.cache.path(rel, im.tobytes(), st.salt)
        out = self.cache.get(cache_path)
        if out is None:
            self.budget.check()
            out = regen4x(im, choice.params, seed=presets.seed_for(rel), scale=st.scale)
            out = presets.finish_choice(choice, im, out)
            self.cache.put(cache_path, out)
        return out, choice

    def _process_source(self, src: Source) -> None:
        s = self.stats
        names = src.names()
        todo = src.texture_keys(self.settings.folders)
        log.info("%s: %d candidate textures", src.label, len(todo))
        res: dict[str, Entry] = {}  # name -> upscaled texture
        for k, n in enumerate(todo):
            try:
                entry = self._upscale_entry(src, names, n)
                if entry is None:
                    s.skipped += 1
                    continue
                res[n] = entry
                s.done += 1
            except OutOfTimeError:
                raise
            except Exception:
                s.failed += 1
                log.info("FAILED %s\n%s", n, traceback.format_exc())
            if k % 10 == 0:
                log.info(
                    "%d/%d  upscaled %d  skipped %d  failed %d  %.0fs",
                    k + 1,
                    len(todo),
                    s.done,
                    s.skipped,
                    s.failed,
                    self.elapsed,
                )
        self._pair_shift_textures(todo, names, res)
        self._link_stills_to_strips(res)
        self._upscale_connected_sheets(src, todo, res)
        for n, entry in res.items():
            self.sink.write(src.out_name(n), png_bytes(entry.out))
            if n + ".mcmeta" in names:
                self.sink.write(src.out_name(n + ".mcmeta"), src.read(n + ".mcmeta"))

    def _upscale_entry(self, src: Source, names: set[str], n: str) -> Entry | None:
        """Upscale texture ``n``; ``None`` if its size is not handled."""
        s = self.stats
        scale = self.settings.scale
        im = load_rgba(src.read(n))
        rel = n.split("assets/", 1)[1]
        w, h = im.size
        stem = PurePosixPath(n).stem
        if (w, h) == (TILE, TILE):
            o = self.upscale(im, rel)[0]
            if presets.has_transparency(im):
                s.items += 1
            else:
                s.blocks += 1
        elif w == TILE and h % TILE == 0 and n + ".mcmeta" in names:
            # animation strip: every 16x16 frame on its own, same seed so grain doesn't flicker
            o = Image.new("RGBA", (TILE * scale, h * scale))
            for frame in range(h // TILE):
                crop = im.crop((0, frame * TILE, TILE, frame * TILE + TILE))
                o.paste(self.upscale(crop, rel)[0], (0, frame * TILE * scale))
            s.anims += 1
        elif w == TILE and h % TILE == 0 and stem.endswith(("_scroll", "_animated")):
            # Sprite-shift target (a mod moves it over the still texture by a fixed atlas offset): it must
            # have the same scale as that still, or the moved texture lands on its atlas neighbours
            o = self.upscale(im, rel)[0]
            s.scrolls += 1
        else:
            return None
        return Entry(o, im)

    def _pair_shift_textures(self, todo: list[str], names: set[str], res: dict[str, Entry]) -> None:
        """Sprite-shift pairs (conveyor belts, flames, rope coils, panel connections ...).

        The moving version X_..._scroll / X_..._animated is drawn by shifting UVs from the still X by a fixed atlas
        offset, so both must be upscaled or neither. Pair = longest existing prefix of the moving name.
        """
        s = self.stats
        stills = {n for n in names if n.endswith(".png")}
        for n in [x for x in todo if PurePosixPath(x).stem.endswith(("_scroll", "_animated"))]:
            parts = n[:-4].split("_")
            still = None
            for i in range(len(parts) - 1, 0, -1):
                candidate = "_".join(parts[:i]) + ".png"
                if candidate in stills:
                    still = candidate
                    break
            if still is None:
                continue
            if (still in res) != (n in res):
                for x in (still, n):
                    if x in res:
                        del res[x]
                        log.info("UNPAIRED, kept original: %s", x)
                        s.unpaired += 1
            elif n in res:
                s.pairs += 1

    def _link_stills_to_strips(self, res: dict[str, Entry]) -> None:
        """A still texture that is exactly the top of its scroll strip is cut from the upscaled strip.

        So a stopped belt and a running belt look the same.
        """
        for n, (o, im) in list(res.items()):
            if not PurePosixPath(n).stem.endswith("_scroll") or im is None:
                continue
            still = n[: -len("_scroll.png")] + ".png"
            if still not in res:
                continue
            still_src = res[still].src
            if (
                still_src is not None
                and still_src.size == (TILE, TILE)
                and np.array_equal(np.asarray(still_src), np.asarray(im)[:TILE])
            ):
                side = self.settings.tile
                res[still] = Entry(o.crop((0, 0, side, side)), still_src)
                self.stats.linked += 1

    def _upscale_connected_sheets(self, src: Source, todo: list[str], res: dict[str, Entry]) -> None:
        """Connected-texture sheets <X>_connected.png of an upscaled 16x16 X: every tile upscaled in context."""
        s = self.stats
        st = self.settings
        jobs: list[CtJob] = []
        for n in todo:
            if not n.endswith("_connected.png"):
                continue
            base_n = n[: -len("_connected.png")] + ".png"
            base = res.get(base_n)
            if base is None or base.src is None or base.src.size != (TILE, TILE):
                continue
            sheet = src.read(n)
            with Image.open(io.BytesIO(sheet)) as sheet_im:
                sw, sh = sheet_im.size
            if sw % TILE or sh % TILE:
                continue
            if n in res:
                del res[n]
                s.done -= 1
            else:
                s.skipped -= 1
            job = CtJob(n, sheet, src.read(base_n), png_bytes(base.out), n.split("assets/", 1)[1], st)
            cache_path = self.cache.path(job.rel, job.sheet + job.base + job.base_up, st.salt)
            cached = self.cache.get(cache_path)
            if cached is not None:
                res[n] = Entry(cached, None)
                s.cts += 1
                s.done += 1
            else:
                jobs.append(job)
        if not jobs:
            return
        log.info("connected-texture sheets: %d", len(jobs))
        paths = {j.name: self.cache.path(j.rel, j.sheet + j.base + j.base_up, st.salt) for j in jobs}
        with multiprocessing.Pool(max(1, min(MAX_WORKERS, os.cpu_count() or 1))) as pool:
            self.budget.check()
            for i, (n, data) in enumerate(pool.imap_unordered(ct_job, jobs)):
                o = load_rgba(data)
                self.cache.put(paths[n], o)
                res[n] = Entry(o, None)
                s.cts += 1
                s.done += 1
                log.info("  CT %d/%d %s  %.0fs", i + 1, len(jobs), n, self.elapsed)
                self.budget.check()


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """The options both pack tools share."""
    parser.add_argument("--scale", type=int, default=4, metavar="N", help=f"{MIN_SCALE}..{MAX_SCALE}, default 4")
    parser.add_argument("--profile", default="standard", metavar="NAME", help="which preset for which texture")
    parser.add_argument(
        "--presets", action="append", default=[], type=Path, metavar="FILE", help="extra presets / profiles (TOML)"
    )
    parser.add_argument(
        "--budget",
        type=float,
        metavar="SECONDS",
        help="stop after about this long (finished work is cached); run again to continue",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        metavar="DIR",
        help="where finished textures are cached (default: $REGEN_CACHE, else ./cache)",
    )


def settings_from(args: argparse.Namespace, parser: argparse.ArgumentParser, folders: Sequence[str]) -> Settings:
    """Settings from the common options; a bad profile / preset file / scale ends the program with a usage error."""
    try:
        book = presets.load_book(args.presets)
        return Settings(book.profile(args.profile), args.scale, tuple(folders))
    except (KeyError, ValueError) as e:
        return parser.error(str(e.args[0]))


def execute(
    sources: Sequence[Source],
    sink: Sink,
    settings: Settings,
    *,
    budget: float | None,
    cache_dir: Path | None,
    report: Path,
) -> int:
    """Run the build and write ``<report>.log`` and ``<report>.done``. Returns the exit code (3 = out of time)."""
    cache = Cache(cache_dir or Path(os.environ.get("REGEN_CACHE") or "cache"), code_hash())
    log_path = report.with_name(report.name + ".log")
    done_path = report.with_name(report.name + ".done")
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        builder = PackBuilder(sources, sink, settings, Budget(budget), cache)
        with sink:
            message = builder.build()
        log.info(message)
        done_path.write_text(message + "\n", encoding="utf-8")
        print(message)
        return 0
    except OutOfTimeError:
        message = f"INCOMPLETE: time budget used, finished work is cached in {cache.dir}; run the same command again"
        log.info(message)
        done_path.write_text(message + "\n", encoding="utf-8")
        print(message)
        return 3
    finally:
        log.removeHandler(handler)
        handler.close()


def parse_args(argv: Sequence[str] | None = None) -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(description="Build a resource pack from mod jars.")
    parser.add_argument("mods_dir", type=Path, help="folder with the mod jars")
    parser.add_argument("out_zip", type=Path, help="resource pack zip to create (an existing one is replaced)")
    parser.add_argument(
        "prefixes", nargs="+", metavar="jar_name_prefix", help="only jars whose file name starts with one"
    )
    add_common_arguments(parser)
    return parser.parse_args(argv), parser


def main(argv: Sequence[str] | None = None) -> int:
    args, parser = parse_args(argv)
    settings = settings_from(args, parser, ("block", "item"))
    jars = [j for j in sorted(args.mods_dir.glob("*.jar")) if j.name.startswith(tuple(args.prefixes))]
    description = f"{settings.tile}x regen4x test: " + ", ".join(args.prefixes)
    sink = ZipSink(args.out_zip, description=description)
    with ExitStack() as stack:
        sources = [stack.enter_context(closing(ZipSource(jar))) for jar in jars]
        return execute(sources, sink, settings, budget=args.budget, cache_dir=args.cache_dir, report=args.out_zip)


if __name__ == "__main__":
    sys.exit(main())
