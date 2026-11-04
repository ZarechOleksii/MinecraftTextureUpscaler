import numpy as np

from regen4x._common import DIAGONALS, NEIGHBOURS_4, BoolArray, IntArray, UInt8Array

__all__ = ["merge_small", "regions", "staircase_mask"]


def regions(
    a: UInt8Array,
    thr: float,
    *,
    mean_mode: bool = False,
    mean_k: float = 1.0,
    diag_join: bool = False,
    alpha_split: bool = False,
    join_thin_only: bool = False,
) -> tuple[IntArray, int]:
    """Flood-fill the RGBA image ``a`` into areas of similar colour (textures tile, so the fill wraps)."""
    h, w = a.shape[:2]
    lab = -np.ones((h, w), int)
    n = 0
    f = a[..., :3].astype(np.float32) / 255
    al = a[..., 3]

    def has_same_edge_neighbour(py: int, px: int) -> bool:
        return any(
            (al[(py + ey) % h, (px + ex) % w] > 0) == (al[py, px] > 0)
            and np.abs(f[(py + ey) % h, (px + ex) % w] - f[py, px]).max() < thr
            for ey, ex in NEIGHBOURS_4
        )

    for y in range(h):
        for x in range(w):
            if lab[y, x] >= 0:
                continue
            stack = [(y, x)]
            lab[y, x] = n
            acc = f[y, x].copy()
            cnt = 1
            while stack:
                cy, cx = stack.pop()
                for dy, dx in NEIGHBOURS_4:
                    ny, nx = (cy + dy) % h, (cx + dx) % w  # wrap: textures tile
                    if (
                        lab[ny, nx] < 0
                        and (al[ny, nx] > 0) == (al[cy, cx] > 0)
                        and (not alpha_split or al[ny, nx] == al[cy, cx])
                        and np.abs(f[ny, nx] - f[cy, cx]).max() < thr
                        and (not mean_mode or np.abs(f[ny, nx] - acc / cnt).max() < thr * mean_k)
                    ):
                        lab[ny, nx] = n
                        stack.append((ny, nx))
                        acc += f[ny, nx]
                        cnt += 1
                if not diag_join:
                    continue
                # join same-coloured pixels touching only at a corner (1px diagonal lines),
                # but only when both pixels between them are clearly different (a real thin line)
                for dy, dx in DIAGONALS:
                    ny, nx = (cy + dy) % h, (cx + dx) % w
                    if lab[ny, nx] >= 0 or (al[ny, nx] > 0) != (al[cy, cx] > 0):
                        continue
                    if alpha_split and al[ny, nx] != al[cy, cx]:
                        continue
                    if np.abs(f[ny, nx] - f[cy, cx]).max() >= thr:
                        continue
                    s1, s2 = f[(cy + dy) % h, cx], f[cy, (cx + dx) % w]
                    # a see-through side pixel always counts as different (its leftover RGB is meaningless,
                    # and is often the outline colour itself)
                    a1, a2 = al[(cy + dy) % h, cx] > 0, al[cy, (cx + dx) % w] > 0
                    o0 = al[cy, cx] > 0
                    if (a1 == o0 and np.abs(s1 - f[cy, cx]).max() < thr) or (
                        a2 == o0 and np.abs(s2 - f[cy, cx]).max() < thr
                    ):
                        continue
                    if mean_mode and np.abs(f[ny, nx] - acc / cnt).max() >= thr * mean_k:
                        continue
                    # crossing: the two side pixels form the other diagonal. Only a thin line may jump across
                    # it, never a thick area (otherwise the background swallows the thin line it crosses)
                    if (
                        join_thin_only
                        and a1 == a2
                        and np.abs(s1 - s2).max() < thr
                        and (has_same_edge_neighbour(cy, cx) or has_same_edge_neighbour(ny, nx))
                    ):
                        continue
                    lab[ny, nx] = n
                    stack.append((ny, nx))
                    acc += f[ny, nx]
                    cnt += 1
            n += 1
    return lab, n


def merge_small(a: UInt8Array, lab: IntArray, max_size: int, mthr: float) -> tuple[IntArray, int]:
    """Merge tiny speckle regions into the most similar neighbouring region (same opacity)."""
    f = a[..., :3].astype(np.float32) / 255
    op = a[..., 3] > 0
    h, w = lab.shape
    changed = True
    while changed:
        changed = False
        ids, counts = np.unique(lab, return_counts=True)
        means = {i: f[lab == i].mean(0) for i in ids}
        for i, c in zip(ids, counts, strict=True):
            if c > max_size:
                continue
            ys, xs = np.nonzero(lab == i)
            best, best_d = None, mthr
            for y, x in zip(ys, xs, strict=True):
                for dy, dx in NEIGHBOURS_4:
                    ny, nx = (y + dy) % h, (x + dx) % w
                    j = lab[ny, nx]
                    if j == i or op[ny, nx] != op[y, x]:
                        continue
                    d = np.abs(means[j] - means[i]).max()
                    if d < best_d:
                        best, best_d = j, d
            if best is not None:
                lab[lab == i] = best
                changed = True
                break
    # relabel 0..n-1
    u, lab2 = np.unique(lab, return_inverse=True)
    return lab2.reshape(lab.shape), len(u)


def staircase_mask(lab: IntArray, n: int, min_run: int = 3) -> BoolArray:
    """16px pixels on a real staircase diagonal: >= min_run consecutive 1px steps in the same direction.

    A step = convex corner (pixel in region, its vertical and horizontal neighbour on one side outside);
    consecutive steps sit diagonally next to each other. Lone corners / short notches are not included.
    """
    h, w = lab.shape
    out = np.zeros((h, w), bool)

    def shifted(arr: BoolArray, dy: int, dx: int) -> BoolArray:
        """``shifted(arr, dy, dx)[y, x] == arr[y + dy, x + dx]`` (wrapping)."""
        return np.roll(np.roll(arr, -dy, 0), -dx, 1)

    for i in range(n):
        m = lab == i
        for dy in (-1, 1):
            for dx in (-1, 1):
                corners = m & ~shifted(m, dy, 0) & ~shifted(m, 0, dx)  # convex corner facing (dy, dx)
                vy, vx = -dy, dx  # next step along the edge
                # mark pixels that belong to a chain of >= min_run corners along (vy, vx)
                chain = np.zeros_like(corners)
                for off in range(-(min_run - 1), 1):
                    ok = np.ones_like(corners)
                    for t in range(min_run):
                        ok &= shifted(corners, (off + t) * vy, (off + t) * vx)
                    chain |= ok
                out |= chain
    return out
