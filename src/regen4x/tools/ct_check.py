"""Check connected-texture sheets in a pack: seam step at tile joins of a 3x3 wall, original vs 64px.

usage: regen4x-ct-check <pack_zip> <mods_dir> <jar_prefix>... [--scale N] [--sheet out.png name1,name2,...]

A wall is built from sheet tiles chosen by which sides are open (as in a 3x3 wall of the same block).
Seam step = mean colour jump across tile joins; inner = jump one pixel inside. Flags sheets whose
64px seam step is clearly larger than the original's (new > 1.2 * old + 2).
"""

import argparse
import io
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from regen4x import ct

Grid = dict[tuple[int, int], tuple[int, int]]  # wall cell -> sheet tile


class SheetRow(NamedTuple):
    name: str
    single_16: Image.Image
    single_64: Image.Image
    wall_16: Image.Image
    wall_64: Image.Image
    seam_16: float
    seam_64: float


def load_rgba(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGBA")


def wall(tiles: ct.Tiles, op: dict[tuple[int, int], ct.OpenSides], base: NDArray[np.uint8], n: int = 3) -> Grid:
    """For each cell of an n x n wall, the sheet tile whose open sides match that cell best."""
    grid: Grid = {}
    for y in range(n):
        for x in range(n):
            want: dict[ct.Side, bool] = {"u": y > 0, "d": y < n - 1, "l": x > 0, "r": x < n - 1}
            best = best_score = None
            for k, t in tiles.items():
                mismatches = sum(op[k][s] != want[s] for s in want)
                score = (mismatches, -float(np.abs(t.astype(int) - base.astype(int)).sum()))
                if best_score is None or score < best_score:
                    best, best_score = k, score
            assert best is not None
            grid[y, x] = best
    return grid


def compose(arr: NDArray[np.uint8], grid: Grid, ts: int, n: int = 3) -> NDArray[np.uint8]:
    out = np.zeros((n * ts, n * ts, 4), np.uint8)
    for (y, x), (ty, tx) in grid.items():
        out[y * ts : (y + 1) * ts, x * ts : (x + 1) * ts] = arr[ty * ts : (ty + 1) * ts, tx * ts : (tx + 1) * ts]
    return out


def seams(wall_pixels: NDArray[np.uint8], ts: int, n: int = 3) -> float:
    """Mean colour jump across the tile joins of a wall."""
    rgb = wall_pixels[..., :3].astype(float)
    steps = []
    for k in range(1, n):
        c = k * ts
        steps.append(np.abs(rgb[:, c - 1] - rgb[:, c]).mean())
        steps.append(np.abs(rgb[c - 1] - rgb[c]).mean())
    return float(np.mean(steps))


def render_comparison(rows: list[SheetRow], out_path: Path) -> None:
    """One row per sheet: single block and 3x3 wall, original vs 64px."""
    grey = (60, 60, 60, 255)
    canvas = Image.new("RGBA", (4 * 394 + 10, len(rows) * 414 + 10), grey)
    draw = ImageDraw.Draw(canvas)
    for r, row in enumerate(rows):
        px = row.single_64.width
        for col, im in enumerate([row.single_16, row.single_64, row.wall_16, row.wall_64]):
            tile = Image.new("RGBA", (384, 384), grey)
            tile.alpha_composite(im.resize((384, 384), Image.Resampling.NEAREST))
            canvas.paste(tile, (10 + col * 394, 30 + r * 414))
        draw.text(
            (10, 14 + r * 414),
            f"{row.name}:  single original | single {px}px | 3x3 joined original | 3x3 joined {px}px"
            f"   (seam step {row.seam_16:.1f} -> {row.seam_64:.1f})",
            fill=(255, 255, 255, 255),
        )
    canvas.save(out_path)


def check_pack(
    pack: zipfile.ZipFile, mods_dir: Path, prefixes: Sequence[str], wanted: Sequence[str] = (), scale: int = 4
) -> tuple[int, list[tuple[object, ...]], list[SheetRow]]:
    """Returns (sheets checked, flagged sheets, rows for the comparison image of the ``wanted`` blocks)."""
    pack_names = set(pack.namelist())
    rows: list[SheetRow] = []
    bad: list[tuple[object, ...]] = []
    checked = 0
    for jar in sorted(mods_dir.glob("*.jar")):
        if not jar.name.startswith(tuple(prefixes)):
            continue
        with zipfile.ZipFile(jar) as z:
            for n in sorted(z.namelist()):
                if not n.endswith("_connected.png") or n not in pack_names:
                    continue
                base_name = n[: -len("_connected.png")] + ".png"
                s16, s64 = load_rgba(z.read(n)), load_rgba(pack.read(n))
                if s64.size != (s16.size[0] * scale, s16.size[1] * scale):
                    bad.append((n, "wrong size", s64.size))
                    continue
                b16 = np.asarray(load_rgba(z.read(base_name)))
                tiles = ct.split(s16)
                op = {q: ct.opens(t, b16) for q, t in tiles.items()}
                grid = wall(tiles, op, b16)
                w16 = compose(np.asarray(s16), grid, 16)
                w64 = compose(np.asarray(s64), grid, 16 * scale)
                seam_16, seam_64 = seams(w16, 16), seams(w64, 16 * scale)
                checked += 1
                if seam_64 > 1.2 * seam_16 + 2:
                    bad.append((n, f"seam {seam_16:.1f} -> {seam_64:.1f}"))
                name = PurePosixPath(base_name).stem
                if name in wanted and name not in [r.name for r in rows]:
                    single_64 = load_rgba(pack.read(base_name))
                    rows.append(
                        SheetRow(
                            name,
                            Image.fromarray(b16),
                            single_64,
                            Image.fromarray(w16),
                            Image.fromarray(w64),
                            seam_16,
                            seam_64,
                        )
                    )
    return checked, bad, rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack_zip", type=Path)
    parser.add_argument("mods_dir", type=Path)
    parser.add_argument("prefixes", nargs="+", metavar="jar_prefix")
    parser.add_argument("--scale", type=int, default=4, help="the scale the pack was built with (default 4)")
    parser.add_argument(
        "--sheet", nargs=2, metavar=("OUT_PNG", "NAMES"), help="also render a comparison for these blocks"
    )
    args = parser.parse_args(argv)
    sheet_out, wanted = (Path(args.sheet[0]), args.sheet[1].split(",")) if args.sheet else (None, [])
    with zipfile.ZipFile(args.pack_zip) as pack:
        checked, bad, rows = check_pack(pack, args.mods_dir, args.prefixes, wanted, args.scale)
    print(checked, "sheets checked;", len(bad), "flagged")
    for b in bad:
        print("  ", b)
    if sheet_out and rows:
        rows.sort(key=lambda row: wanted.index(row.name))
        render_comparison(rows, sheet_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
