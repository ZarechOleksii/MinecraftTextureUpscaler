from collections import Counter
from typing import Any

import numpy as np

from regen4x._common import NEIGHBOURS_4, BoolArray, FloatArray, IntArray, Pair, UInt8Array

__all__ = ["line_pairs", "real_lines"]


def line_pairs(
    lab: IntArray,
    n: int,
    cut: bool,
    opq: BoolArray,
    fc: FloatArray,
    min_contrast: float = 0.1,
) -> list[Pair]:
    """(label, y, x, dx) for same-area pixels touching only at a corner (p=(y,x), q=(y+1,x+dx)).

    At crossings the locally thinner diagonal wins.
    """
    h, w = lab.shape
    rsize = np.bincount(lab.ravel(), minlength=n)

    def thick(py: int, px: int) -> int:
        l0 = lab[py, px]
        return sum(lab[(py + ey) % h, (px + ex) % w] == l0 for ey, ex in NEIGHBOURS_4)

    def run(py: int, px: int, sy: int, sx: int) -> int:
        # how far a 1px LINE continues from (py,px) along (sy,sx): count steps where the next same-area pixel
        # touches only at the corner (the two pixels beside that corner are a different area). Thick areas
        # (planks, stone) continue through shared edges and therefore don't count as a long line.
        l0 = lab[py, px]
        steps = 0
        cy, cx = py, px
        for _ in range(4):
            ny, nx = cy + sy, cx + sx
            if cut and not (0 <= ny < h and 0 <= nx < w):
                break
            if lab[ny % h, nx % w] != l0:
                break
            if lab[ny % h, cx % w] == l0 or lab[cy % h, nx % w] == l0:
                break
            cy, cx = ny, nx
            steps += 1
        return steps

    def visible(py: int, px: int, qy: int, qx: int, s1y: int, s1x: int, s2y: int, s2x: int, ddx: int) -> bool:
        # a corner pair counts as a visible line if it contrasts with the two pixels beside it;
        # weak contrast only counts when the diagonal continues to >= 3 pixels (isolated speckle pairs don't)
        lc = (fc[py, px] + fc[qy, qx]) / 2
        con = min(
            np.abs(fc[s1y, s1x] - lc).max() if opq[s1y, s1x] else 1.0,
            np.abs(fc[s2y, s2x] - lc).max() if opq[s2y, s2x] else 1.0,
        )
        if con < min_contrast:
            return False
        return not (con < 0.1 and 2 + run(py, px, -1, -ddx) + run(qy, qx, 1, ddx) < 3)

    out: list[Pair] = []
    for y in range(h):
        for x in range(w):
            for dx in (1, -1):
                y2, x2 = y + 1, x + dx
                if cut and not (0 <= y2 < h and 0 <= x2 < w):
                    continue
                y2 %= h
                x2 %= w
                li = lab[y, x]
                if lab[y2, x2] != li or lab[y2, x] == li or lab[y, x2] == li or not opq[y, x]:
                    continue
                # only a visible line: the pair must clearly contrast with the two pixels beside it
                if not visible(y, x, y2, x2, y2, x, y, x2, dx):
                    continue
                oa, ob = lab[y2, x], lab[y, x2]
                # the other diagonal only competes if it would itself be drawn
                if oa == ob and opq[y2, x] and visible(y, x2, y2, x, y, x, y2, x2, -dx):
                    # crossing: connect the more line-like diagonal = continues further, penalised for thickness
                    t_me = thick(y, x) + thick(y2, x2)
                    t_other = thick(y2, x) + thick(y, x2)
                    c_me = run(y, x, 1, dx) + run(y, x, -1, -dx)
                    c_other = run(y, x2, 1, -dx) + run(y, x2, -1, dx)
                    s_me = c_me - t_me
                    s_other = c_other - t_other
                    if s_other > s_me:
                        continue
                    if s_other == s_me and (rsize[oa], oa) < (rsize[li], li):
                        continue
                out.append((li, y, x, dx))
    return out


def _pair_contrast(f: FloatArray, y: int, x: int, dx: int) -> np.floating[Any]:
    """Contrast between a corner pair and the two pixels beside it (smaller of the two)."""
    h, w = f.shape[:2]
    y2, x2 = (y + 1) % h, (x + dx) % w
    lc = (f[y, x] + f[y2, x2]) / 2
    contrast: np.floating[Any] = min(np.abs(f[y2, x] - lc).max(), np.abs(f[y, x2] - lc).max())
    return contrast


def real_lines(
    pairs: list[Pair],
    a: UInt8Array,
    cut: bool,
    min_len: int,
    strong: float,
    *,
    attach: bool = False,
    lab: IntArray | None = None,
    bend_mode: str | None = None,
    strong_thin: bool = False,
    single_con: float = 1.0,
) -> list[Pair]:
    """Keep only diagonal links that read as real lines: a chain of >= min_len pixels, or contrast >= strong."""
    h, w = a.shape[:2]
    f = a[..., :3].astype(np.float32) / 255
    pset = {(int(y), int(x), int(dx)) for _, y, x, dx in pairs}
    keep: list[Pair] = []
    long_: list[Pair] = []

    def step_ok(cy: int, cx: int, ny: int, nx: int, li: int) -> bool:
        if cut and not (0 <= ny < h and 0 <= nx < w):
            return False
        if lab is None:
            return False
        ny, nx = ny % h, nx % w
        # same area at the diagonal, touching only at the corner (a crossing line between them doesn't break the chain)
        return bool(lab[ny, nx] == li and lab[cy % h, nx] != li and lab[ny, cx % w] != li)

    for li, y, x, dx in pairs:
        c = 2
        yy, xx = int(y), int(x)
        while c < 32:
            py, px = yy - 1, xx - dx
            if not ((py % h, px % w, int(dx)) in pset or step_ok(yy, xx, py, px, li)):
                break
            if cut and not (0 <= py < h and 0 <= px < w):
                break
            yy, xx = py % h, px % w
            c += 1
        yy, xx = (int(y) + 1) % h, (int(x) + dx) % w
        while c < 32:
            ny, nx = yy + 1, xx + dx
            if not ((yy, xx, int(dx)) in pset or step_ok(yy, xx, ny, nx, li)):
                break
            if cut and not (0 <= ny < h and 0 <= nx < w):
                break
            yy, xx = ny % h, nx % w
            c += 1
        if c >= min_len or _pair_contrast(f, y, x, dx) >= strong:
            keep.append((li, y, x, dx))
        if c >= min_len:
            long_.append((li, y, x, dx))

    if strong_thin and lab is not None:
        # short pairs kept only for their contrast must be a real 1px line: neither pixel may have a same-area edge
        # neighbour (otherwise it's a corner of a small pixel-art shape, e.g. the curve of an arch)
        longs = set(long_)
        label_map = lab

        def thin(py: int, px: int, li: int) -> bool:
            return not any(label_map[(py + ey) % h, (px + ex) % w] == li for ey, ex in NEIGHBOURS_4)

        keep = [
            p
            for p in keep
            if p in longs or (thin(int(p[1]), int(p[2]), p[0]) and thin((p[1] + 1) % h, (p[2] + p[3]) % w, p[0]))
        ]
    if single_con < 1.0:
        # a drawn line that is just ONE corner pair (its area has no other drawn link) is only kept if its contrast is
        # very high; lone 2px pairs on textures without real lines (speckled stone, sign details) stay as base-v1.0
        per_area = Counter(int(p[0]) for p in keep)
        keep = [p for p in keep if per_area[int(p[0])] > 1 or _pair_contrast(f, p[1], p[2], p[3]) >= single_con]
    if bend_mode:
        keep = _resolve_bends(keep, pairs, long_, bend_mode, h, w)
    if attach:
        keep = _attach_short_pieces(keep, pairs, long_, h, w)
    return keep


def _resolve_bends(
    keep: list[Pair], pairs: list[Pair], long_: list[Pair], bend_mode: str, h: int, w: int
) -> list[Pair]:
    """Short pairs kept only for their contrast: if one of their pixels also has a diagonal link of the same area in the
    other direction (a 1px curve bending, like the legs of a small arch), straightening only one leg breaks the shape.

    ``bend_mode='skip'``: don't draw such a short pair; ``'both'``: also draw the other leg so the bend stays symmetric.
    """
    longs = set(long_)
    kept = set(keep)
    ends: dict[tuple[int, int, int], list[Pair]] = {}
    for p in pairs:
        li, y, x, dx = p
        for e in ((int(y), int(x)), ((y + 1) % h, (x + dx) % w)):
            ends.setdefault((int(li), *e), []).append(p)
    new_keep = set(kept)
    for p in keep:
        if p in longs:
            continue
        li, y, x, dx = p
        others = [
            q
            for e in ((int(y), int(x)), ((y + 1) % h, (x + dx) % w))
            for q in ends.get((int(li), *e), [])
            if q != p and int(q[3]) != int(dx)
        ]
        if not others:
            continue
        if bend_mode == "skip":
            if not any(q in kept for q in others):
                new_keep.discard(p)
        else:
            new_keep.update(others)
    return [p for p in pairs if p in new_keep]


def _attach_short_pieces(keep: list[Pair], pairs: list[Pair], long_: list[Pair], h: int, w: int) -> list[Pair]:
    """A short piece of the SAME area that touches a LONG line (or a piece already attached to one) is part of it.

    Example: a 3px seam segment between two junctions in double herringbone. Repeated so whole short pieces are added.
    """
    kept = set(keep)
    anchor = set(long_)
    changed = True
    while changed:
        changed = False
        anchor_pixels: dict[int, set[tuple[int, int]]] = {}
        for li, y, x, dx in anchor:
            anchor_pixels.setdefault(int(li), set()).update({(int(y), int(x)), ((y + 1) % h, (x + dx) % w)})
        for p in pairs:
            li, y, x, dx = p
            if p in anchor:
                continue
            pixels = anchor_pixels.get(int(li), ())
            if (int(y), int(x)) in pixels or ((y + 1) % h, (x + dx) % w) in pixels:
                kept.add(p)
                anchor.add(p)
                changed = True
    return [p for p in pairs if p in kept]
