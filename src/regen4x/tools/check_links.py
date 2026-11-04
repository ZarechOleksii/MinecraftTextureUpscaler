"""Local diagonal-link check for regen4x line experiments.

Every pair of same-area pixels that touch only at a corner AND form a visible line (same visibility rule as
regen4x.lines.line_pairs) must be connected INSIDE their own 2x2 window (8x8 px at 64px). At a true crossing (the other
diagonal is also a visible same-area corner pair) at least one of the two must be connected.

Usage:  regen4x-check-links [<folder with 16x16 pngs>]
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage as ndi

from regen4x.params import RegenParams
from regen4x.presets import LINES_V1_0
from regen4x.upscaler import regen4x

SIZE = 16  # source texture size
SCALE = 4
OUT = SIZE * SCALE
WINDOW = 2 * SCALE  # a corner pair spans a 2x2 pixel window

Point = tuple[int, int]


def window_connects(final_labels: NDArray[np.int_], label: int, origin: Point, p: Point, q: Point) -> bool:
    """Are pixels ``p`` and ``q`` joined by output pixels of ``label`` inside the 2x2 window at ``origin``?"""
    oy, ox = origin
    win = np.array(
        [[final_labels[(oy + yy) % OUT, (ox + xx) % OUT] == label for xx in range(WINDOW)] for yy in range(WINDOW)]
    )
    components = ndi.label(win)[0]
    a1 = components[p[0] * SCALE + 2, p[1] * SCALE + 2]
    a2 = components[q[0] * SCALE + 2, q[1] * SCALE + 2]
    return bool(a1 != 0 and a1 == a2)


def local_check(src: Image.Image, params: RegenParams, seed: int = 7) -> list[tuple[Point, str]]:
    """Corner pairs of ``src`` that should read as a line but are not connected in the upscaled output."""
    a = np.asarray(src)
    debug: dict[str, NDArray[np.int_]] = {}
    regen4x(src, params, seed=seed, debug=debug)
    final_labels, lab = debug["final_L"], debug["lab"]
    cut = bool((a[..., 3] == 0).any())
    fc = a[..., :3].astype(float) / 255
    bad: list[tuple[Point, str]] = []

    def run_length(py: int, px: int, sy: int, sx: int) -> int:
        l0 = lab[py, px]
        steps = 0
        cy, cx = py, px
        for _ in range(4):
            ny, nx = cy + sy, cx + sx
            if cut and not (0 <= ny < SIZE and 0 <= nx < SIZE):
                break
            if lab[ny % SIZE, nx % SIZE] != l0:
                break
            if lab[ny % SIZE, cx % SIZE] == l0 or lab[cy % SIZE, nx % SIZE] == l0:
                break
            cy, cx = ny, nx
            steps += 1
        return steps

    def visible(p1: Point, p2: Point, s1: Point, s2: Point) -> bool:
        lc = (fc[p1] + fc[p2]) / 2
        con = min(
            np.abs(fc[s1] - lc).max() if a[s1][3] > 0 else 1,
            np.abs(fc[s2] - lc).max() if a[s2][3] > 0 else 1,
        )
        if con < params.line_contrast:
            return False
        sy, sx = p2[0] - p1[0], p2[1] - p1[1]
        return not (con < 0.1 and 2 + run_length(p1[0], p1[1], -sy, -sx) + run_length(p2[0], p2[1], sy, sx) < 3)

    for y in range(SIZE):
        for x in range(SIZE):
            if cut and (x + 1 > SIZE - 1 or y + 1 > SIZE - 1):
                continue
            y1, x1 = (y + 1) % SIZE, (x + 1) % SIZE
            top_left, top_right, bottom_left, bottom_right = lab[y, x], lab[y, x1], lab[y1, x], lab[y1, x1]
            backslash = (
                top_left == bottom_right
                and top_right != top_left
                and bottom_left != top_left
                and a[y, x, 3] > 0
                and visible((y, x), (y1, x1), (y, x1), (y1, x))
            )
            slash = (
                top_right == bottom_left
                and top_left != top_right
                and bottom_right != top_right
                and a[y, x1, 3] > 0
                and visible((y, x1), (y1, x), (y, x), (y1, x1))
            )
            origin = (y * SCALE, x * SCALE)
            if backslash and slash:
                if not (
                    window_connects(final_labels, top_left, origin, (0, 0), (1, 1))
                    or window_connects(final_labels, top_right, origin, (0, 1), (1, 0))
                ):
                    bad.append(((y, x), "crossing, neither connected"))
            elif backslash:
                if not window_connects(final_labels, top_left, origin, (0, 0), (1, 1)):
                    bad.append(((y, x), "\\ not connected"))
            elif slash and not window_connects(final_labels, top_right, origin, (0, 1), (1, 0)):
                bad.append(((y, x), "/ not connected"))
    return bad


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", type=Path, default=Path(), help="folder with 16x16 pngs (default: .)")
    args = parser.parse_args(argv)
    report = []
    checked = 0
    for path in sorted(args.folder.rglob("*.png")):
        with Image.open(path) as f:
            src = f.convert("RGBA")
        if src.size != (SIZE, SIZE):
            continue
        checked += 1
        bad = local_check(src, LINES_V1_0)
        if bad:
            report.append((path.name, len(bad), bad[:3]))
    print(checked, "textures; textures with a local diagonal link not connected:", len(report))
    for row in report:
        print("  ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
