from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage as ndi

from regen4x._common import (
    DIAGONALS,
    NEIGHBOURS_4,
    BoolArray,
    FloatArray,
    IntArray,
    Pair,
    UInt8Array,
)
from regen4x.lines import line_pairs, real_lines
from regen4x.params import RegenParams
from regen4x.regions import merge_small, regions, staircase_mask

__all__ = ["regen4x"]

_FULL_3X3 = np.ones((3, 3), bool)


def regen4x(
    im: Image.Image,
    params: RegenParams | None = None,
    *,
    seed: int = 1,
    scale: int | None = None,
    debug: dict[str, IntArray] | None = None,
) -> Image.Image:
    """Upscale ``im`` (default scale: to 64px). Output is deterministic for a given ``seed``.

    If ``debug`` is given it is filled with the final per-pixel area map (``final_L``, output size) and the
    source area map (``lab``), for the diagnostic scripts.
    """
    return _Upscaler(im, RegenParams() if params is None else params, seed, scale).run(debug)


class _Upscaler:
    """One upscale run. Each ``_stage`` method mirrors one step of the algorithm described in the module docstring."""

    def __init__(self, im: Image.Image, params: RegenParams, seed: int, scale: int | None) -> None:
        self.p = params
        self.seed = seed
        self.a: UInt8Array = np.asarray(im.convert("RGBA"))
        self.h, self.w = self.a.shape[:2]
        self.r = scale if scale else max(1, 64 // self.h)
        self.H, self.W = self.h * self.r, self.w * self.r
        self.k = self.r / 4
        self.cut = bool((self.a[..., 3] == 0).any())
        self.blur_mode = "nearest" if self.cut else "wrap"
        self.lab: IntArray
        self.n = 0
        self.masks: FloatArray
        self.up: FloatArray
        self.stair_w: BoolArray | None = None
        self.line_core: BoolArray | None = None
        self.line_areas: set[int] = set()
        self.cutout = False
        self.diag = False
        self.sharp_list: list[tuple[int, BoolArray]] = []
        self.owner: IntArray  # final area label of every output pixel
        self.overlay: BoolArray | None = None
        self.overlay_label: IntArray | None = None

    # -- helpers ------------------------------------------------------------------------------------------------------

    def blur(self, x: FloatArray, sigma: float) -> FloatArray:
        """Gaussian blur that wraps for tiling textures and clamps for cut-outs."""
        blurred: FloatArray = ndi.gaussian_filter(x, sigma, mode=self.blur_mode)
        return blurred

    def upsample(self, x: NDArray[Any]) -> NDArray[Any]:
        return x.repeat(self.r, 0).repeat(self.r, 1)

    def source_colours(self) -> FloatArray:
        colours: FloatArray = self.a[..., :3].astype(np.float32) / 255
        return colours

    def real_lines_of(self, pairs: list[Pair], min_len: int) -> list[Pair]:
        p = self.p
        return real_lines(
            pairs,
            self.a,
            self.cut,
            min_len,
            p.line_strong,
            attach=p.line_attach,
            lab=self.lab if p.line_thru else None,
            bend_mode=p.line_bend,
            strong_thin=p.strong_thin,
            single_con=p.single_con,
        )

    def run(self, debug: dict[str, IntArray] | None) -> Image.Image:
        p = self.p
        self.label_regions()
        self.masks = np.stack([(self.lab == i).astype(np.float32) for i in range(self.n)])
        self.shape_fields()
        self.owner = self.up.argmax(0)
        if p.keep_thin and self.r >= 2:
            self.thin_features()
        for i, nm in self.sharp_list:
            self.owner[nm] = i  # protected shapes win over later bridges
        if p.line_bands and not p.line_field and self.r >= 2:
            self.legacy_line_bands()
        self.despeckle()
        if debug is not None:
            debug["final_L"] = self.owner.copy()
            debug["lab"] = self.lab.copy()
        out = self.render()
        if self.overlay is not None and self.overlay.any():
            self.blend_overlay(out)
        if p.keep_dither:
            self.restore_dither(out)
        return Image.fromarray(out.round().clip(0, 255).astype(np.uint8))

    # -- 1. regions ---------------------------------------------------------------------------------------------------

    def label_regions(self) -> None:
        p = self.p
        self.lab, self.n = regions(
            self.a,
            p.thr,
            mean_mode=p.mean_mode,
            mean_k=p.mean_k,
            diag_join=p.diag_join,
            alpha_split=p.alpha_split,
            join_thin_only=p.join_thin_only,
        )
        if p.merge_size:
            self.lab, self.n = merge_small(self.a, self.lab, p.merge_size, p.merge_thr)
        if p.line_field and p.line_aa_merge:
            self.merge_antialiased_pixels()
        if p.split_undrawn and p.diag_join and p.line_field:
            self.split_undrawn_areas()

    def merge_antialiased_pixels(self) -> None:
        """Lone 1px mid-tone pixels touching a diagonal line (hand-made anti-aliasing).

        They are merged into the most similar edge-neighbour area, so they get redrawn smoothly instead of staying
        4x4 squares.
        """
        p, h, w = self.p, self.h, self.w
        lab = self.lab
        opq = self.a[..., 3] > 0
        fcol = self.source_colours()
        line_areas = {q[0] for q in line_pairs(lab, self.n, self.cut, opq, fcol, p.line_contrast)}
        if not line_areas:
            return
        sizes = np.bincount(lab.ravel(), minlength=self.n)
        small = {l0 for l0 in range(self.n) if 1 <= sizes[l0] <= p.aa_max and l0 not in line_areas}
        todo: list[tuple[int, int, int]] = []
        for y in range(h):
            for x in range(w):
                l0 = lab[y, x]
                if l0 not in small or not opq[y, x]:
                    continue
                nb8 = [lab[(y + dy) % h, (x + dx) % w] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
                if not any(q in line_areas for q in nb8):
                    continue
                best, best_d = None, 1e9
                for dy, dx in NEIGHBOURS_4:
                    yy, xx = (y + dy) % h, (x + dx) % w
                    q = lab[yy, xx]
                    if not opq[yy, xx] or q == l0 or q in small:
                        continue
                    d = np.abs(fcol[yy, xx] - fcol[y, x]).max()
                    if d < best_d:
                        best, best_d = q, d
                if best is not None:
                    todo.append((y, x, best))
        for y, x, best in todo:
            lab[y, x] = best
        # the smooth line edge now does the anti-aliasing: give merged pixels the colour of their new area's neighbours
        if todo:
            a = self.a.copy()
            merged = {(t[0], t[1]) for t in todo}
            for y, x, best in todo:
                nb = [
                    a[(y + dy) % h, (x + dx) % w]
                    for dy, dx in NEIGHBOURS_4
                    if lab[(y + dy) % h, (x + dx) % w] == best and ((y + dy) % h, (x + dx) % w) not in merged
                ]
                if nb:
                    a[y, x] = np.round(np.mean(nb, 0)).astype(a.dtype)
            self.a = a
        self.relabel()

    def relabel(self) -> None:
        """Make the area labels contiguous (0..n-1) again."""
        u, inverse = np.unique(self.lab, return_inverse=True)
        self.lab = inverse.reshape(self.lab.shape)
        self.n = len(u)

    def split_undrawn_areas(self) -> None:
        """Areas joined only through diagonal links that will NOT be drawn as lines are split back apart.

        Those pixels then render like normal pixels instead of beads of one area (dotted patterns).
        """
        p, h, w = self.p, self.h, self.w
        lab = self.lab
        pairs = line_pairs(lab, self.n, self.cut, self.a[..., 3] > 0, self.source_colours(), p.line_contrast)
        if p.line_min_len or p.line_strong < 1.0:
            pairs = self.real_lines_of(pairs, p.line_min_len)
        parent = list(range(h * w))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def unite(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for y in range(h):
            for x in range(w):
                for dy, dx in ((1, 0), (0, 1)):
                    yy, xx = (y + dy) % h, (x + dx) % w
                    if lab[yy, xx] == lab[y, x]:
                        unite(y * w + x, yy * w + xx)
        for _, y, x, dx in pairs:
            unite(int(y) * w + int(x), ((y + 1) % h) * w + (x + dx) % w)
        roots = np.array([find(i) for i in range(h * w)]).reshape(h, w)
        u, inverse = np.unique(roots, return_inverse=True)
        self.lab = inverse.reshape(h, w)
        self.n = len(u)

    # -- 2. shapes ----------------------------------------------------------------------------------------------------

    def shape_fields(self) -> None:
        """Build ``self.up``: per area, a field over the output grid; the highest field owns each output pixel."""
        p, r, k, cut = self.p, self.r, self.k, self.cut
        masks, lab, n = self.masks, self.lab, self.n
        self.diag = bool(p.diag_items and cut and r >= 2)
        diag_b = bool(p.diag_blocks and not cut and r >= 2)
        repeated = masks.repeat(r, 1).repeat(r, 2)
        if self.diag:
            # items/plants: wide smoothing of shapes so runs of 1px steps become real diagonal lines
            up = np.stack([ndi.gaussian_filter(m, p.diag_sigma * k, mode="nearest") for m in repeated])
        elif diag_b:
            # blocks: diagonal smoothing (wrapping so tiling stays seamless)
            # (diag_selective: per texture, only textures with clear staircase diagonals get diagonal smoothing)
            if p.diag_selective and staircase_mask(lab, n).sum() < p.stair_min:
                up = np.stack([self.blur(m, p.shape_round * k) for m in repeated])
            else:
                up = np.stack([ndi.gaussian_filter(m, p.diag_sigma * k, mode="wrap") for m in repeated])
        else:
            up = np.stack([self.blur(m, p.shape_round * k) for m in repeated])
        self.up = up
        if p.stair_local and r >= 2:
            self.local_staircases(repeated)
        if p.line_field and r >= 2:
            self.line_fields()
        if p.keep_sharp:
            self.protect_sharp_shapes()
        self.shape_silhouette()
        if p.shape_groups:
            self.group_shapes()

    def local_staircases(self, repeated: FloatArray) -> None:
        """Local diagonal smoothing: only around real 1px staircases (>= stair_run steps).

        ALL areas there get the same wide smoothing so the boundary between them becomes a diagonal edge;
        corners elsewhere stay as they are.
        """
        p, r, k = self.p, self.r, self.k
        st = staircase_mask(self.lab, self.n, min_run=p.stair_run)
        if p.stair_grow:
            st = ndi.binary_dilation(st, structure=_FULL_3X3)
        stair_w = st.repeat(r, 0).repeat(r, 1)
        self.stair_w = stair_w
        if stair_w.any():
            up_d = np.stack([ndi.gaussian_filter(m, p.diag_sigma * k, mode=self.blur_mode) for m in repeated])
            self.up = np.where(stair_w[None], up_d, self.up)

    def line_fields(self) -> None:
        """Line bands drawn at the SHAPE stage.

        Each band is added to its line area's shape field before owners are picked, so it goes through the same
        rounding as everything else.
        """
        p, a, lab, n = self.p, self.a, self.lab, self.n
        h, w, k, cut = self.h, self.w, self.k, self.cut
        up, masks = self.up, self.masks
        opq = a[..., 3] > 0
        pairs = line_pairs(lab, n, cut, opq, self.source_colours(), p.line_contrast)
        if p.line_min_len or p.line_strong < 1.0:
            all_pairs = pairs
            pairs = self.real_lines_of(all_pairs, p.line_min_len)
            if p.inner_min_len and cut:
                # items: inside the item (both pixels beside the diagonal opaque) shorter lines count as real lines too
                inner = self.real_lines_of(all_pairs, p.inner_min_len)
                have = {(int(q[0]), int(q[1]), int(q[2]), int(q[3])) for q in pairs}
                pairs = list(pairs) + [
                    q
                    for q in inner
                    if (int(q[0]), int(q[1]), int(q[2]), int(q[3])) not in have
                    and opq[(q[1] + 1) % h, q[2]]
                    and opq[q[1], (q[2] + q[3]) % w]
                ]
        if p.skip_edge_lines and cut:
            # diagonals running along the item outline (a see-through pixel beside them) are left to the outline
            # smoothing (diag_items), which rounds them better than a thin band
            pairs = [q for q in pairs if opq[(q[1] + 1) % h, q[2]] and opq[q[1], (q[2] + q[3]) % w]]

        bands, core = self.paint_bands(pairs, opq)

        # pure line pixels (no same-area edge neighbour) must not keep their full square: rebuild that area's field
        # without them, so only the band represents them and their outer corners go to the neighbouring colour
        pure = np.zeros((h, w), bool)
        for li, y, x, dx in pairs:
            for py, px in ((y, x), ((y + 1) % h, (x + dx) % w)):
                if not any(lab[(py + ey) % h, (px + ex) % w] == li for ey, ex in NEIGHBOURS_4):
                    pure[py, px] = True
        if p.line_neighbours_diag:
            # areas running alongside a drawn line (shadows, mid-tone strips) get diagonal smoothing too,
            # so their staircase edges follow the line instead of keeping 4x4 steps
            drawn = {q[0] for q in pairs}
            near: set[int] = set()
            for li in drawn:
                ring = ndi.binary_dilation(lab == li, structure=_FULL_3X3) & (lab != li)
                near |= set(np.unique(lab[ring]).tolist())
            near -= drawn
            sizes = np.bincount(lab.ravel(), minlength=n)
            for q in near:
                if sizes[q] > p.neighbour_max:
                    continue
                up[q] = ndi.gaussian_filter(self.upsample(masks[q]), p.diag_sigma * k, mode=self.blur_mode)
        line_labels = sorted({q[0] for q in pairs})
        for li in line_labels:
            rep = self.upsample(masks[li] * (~pure))
            # line_area_diag: the thick parts of a line area (2px staircases, junctions) get the wide diagonal
            # smoothing, so their 4x4 steps become a diagonal edge like the drawn 1px band next to them
            sigma = (p.diag_sigma if p.line_area_diag else p.shape_round) * k
            up[li] = ndi.gaussian_filter(rep, sigma, mode=self.blur_mode)
            if self.stair_w is not None and self.stair_w.any():
                wide = ndi.gaussian_filter(rep, p.diag_sigma * k, mode=self.blur_mode)
                up[li] = np.where(self.stair_w, wide, up[li])
        for li in line_labels:
            soft = ndi.gaussian_filter(bands[li], p.shape_round * k, mode=self.blur_mode)
            up[li] = np.maximum(up[li], np.maximum(soft * p.line_strength, core[li] * 1e3))  # centre always wins
            if p.line_confine:
                # the line may only take its own band and its own (non-pure) pixels: where a seam ends against another
                # seam, the rounded-off plank corners go back to the planks instead of growing a blob at the junction
                own = self.upsample(masks[li] * (~pure)) > 0
                up[li] = np.where((bands[li] > 0) | own, up[li], -1.0)
        self.line_core = np.asarray(core.any(0), dtype=bool)
        self.line_areas = {int(q[0]) for q in pairs}

    def paint_bands(self, pairs: list[Pair], opq: BoolArray) -> tuple[FloatArray, FloatArray]:
        """Stamp a diagonal band (and a thinner always-winning core) per line pair onto per-area fields."""
        p, lab, h, w, r, H, W = self.p, self.lab, self.h, self.w, self.r, self.H, self.W
        half = r // 2
        yb, xb = np.mgrid[0 : 2 * r, 0 : 2 * r]
        bands = np.zeros_like(self.up)
        core = np.zeros_like(self.up)
        cw = max(1, r // 4)

        def stamp(field: FloatArray, li: int, oy: int, ox: int, sel: BoolArray) -> None:
            field[li, (oy + yb[sel]) % H, (ox + xb[sel]) % W] = 1.0

        def diagonal(dx: int) -> IntArray:
            window_diagonal: IntArray = (xb - yb) if dx == 1 else (xb + yb - (2 * r - 1))
            return window_diagonal

        pset = {(int(li), int(y), int(x), int(dx)) for li, y, x, dx in pairs}
        for li, y, x, dx in pairs:
            oy = y * r
            ox = (x if dx == 1 else x - 1) * r
            dd = diagonal(dx)
            band = np.abs(dd) <= half
            cen = np.abs(dd) <= cw
            if p.line_clip:
                # along-line position in the 2x2 window: p's centre at r/2-0.5, q's centre at 1.5r-0.5. The band only
                # runs past a pixel's centre (to its outer edge) when the line continues the same way; otherwise it
                # stops just past the centre, so a seam ending against another seam doesn't poke through it as a stub
                along = ((xb + yb) if dx == 1 else (yb - xb + (2 * r - 1))) / 2.0
                yp, xp = (y - 1) % h, (x - dx) % w
                yq, xq = (y + 1) % h, (x + dx) % w
                cont_p = (int(li), yp, xp, int(dx)) in pset
                cont_q = (int(li), yq, xq, int(dx)) in pset
                lo = (r / 2 - 0.5) - (r / 2 if cont_p else p.clip_end)
                hi = (1.5 * r - 0.5) + (r / 2 if cont_q else p.clip_end)
                inside = (along >= lo) & (along <= hi)
                band &= inside
                cen &= inside
            stamp(bands, li, oy, ox, band)
            stamp(core, li, oy, ox, cen)
        if p.line_reach:
            # a line that ends diagonally against a different feature (e.g. the arms of an X against its dark centre
            # squares) is extended into that pixel, so it visibly reaches it instead of stopping at its own centre
            for li, y, x, dx in pairs:
                for end, sgn in (((int(y), int(x)), -1), (((y + 1) % h, (x + dx) % w), 1)):
                    ey, ex = end
                    ny, nx = ey + sgn, ex + sgn * dx
                    if self.cut and not (0 <= ny < h and 0 <= nx < w):
                        continue
                    ny %= h
                    nx %= w
                    nxt = (int(li), ey, ex, int(dx)) if sgn == 1 else (int(li), ny, nx, int(dx))
                    if nxt in pset or lab[ny, nx] == li or not opq[ny, nx]:
                        continue
                    s1, s2 = lab[ey, nx], lab[ny, ex]
                    if lab[ny, nx] in (s1, s2) or s1 == li or s2 == li:
                        continue  # just background beside the line: a real end
                    if s1 == s2:
                        continue  # never cut across another diagonal line
                    # only reach into a pixel of (nearly) the line's own colour: an X into its dark squares,
                    # not a herringbone seam into the next plank
                    line_colour = self.a[..., :3][lab == li].astype(np.float32).mean(0) / 255
                    if np.abs(self.a[ny, nx, :3].astype(np.float32) / 255 - line_colour).max() >= p.reach_col:
                        continue
                    # window spanned by end pixel and feature pixel
                    ty, tx = (ey, ex) if sgn == 1 else (ny, nx)
                    oy = ty * r
                    ox = (tx if dx == 1 else tx - 1) * r
                    dd = diagonal(dx)
                    along = ((xb + yb) if dx == 1 else (yb - xb + (2 * r - 1))) / 2.0
                    seg = (along >= r / 2 - 0.5) & (along <= 1.5 * r - 0.5)  # centre to centre
                    stamp(bands, li, oy, ox, (np.abs(dd) <= half) & seg)
                    stamp(core, li, oy, ox, (np.abs(dd) <= cw) & seg)
        return bands, core

    def protect_sharp_shapes(self) -> None:
        """Small, high-contrast regions made only of straight edges keep their exact pixel shape."""
        p, a, lab, n, h, w, r = self.p, self.a, self.lab, self.n, self.h, self.w, self.r
        up = self.up
        fcol = self.source_colours()
        for i in range(n):
            mi = lab == i
            count = mi.sum()
            if count > p.sharp_max or count < 2 or not a[..., 3][mi].any():
                continue
            ys, xs = np.nonzero(mi)
            rect = True
            for y, x in zip(ys, xs, strict=True):
                for dy, dx in ((1, 1), (1, -1)):
                    y2, x2 = y + dy, x + dx
                    if 0 <= y2 < h and 0 <= x2 < w and mi[y2, x2] and not mi[y, x2] and not mi[y2, x]:
                        rect = False
                        break
                if not rect:
                    break
            if not rect:
                continue
            ring_all = ndi.binary_dilation(mi, structure=_FULL_3X3) & ~mi
            if (a[..., 3][ring_all] == 0).any():
                continue  # touches the see-through outline -> organic art, keep smoothing
            ring = ndi.binary_dilation(mi) & ~mi & (a[..., 3] > 0)
            if not ring.any():
                continue
            contrast = np.abs(fcol[mi].mean(0) - fcol[ring].mean(0)).max()
            ring_colours = fcol[ring_all & (a[..., 3] > 0)]
            if (ring_colours.max(0) - ring_colours.min(0)).max() > p.sharp_flat:
                continue  # background must be one flat colour (UI-style symbol)
            if contrast < p.sharp_contrast:
                continue
            nm = mi.repeat(r, 0).repeat(r, 1)
            self.sharp_list.append((i, nm))
            up[i] = np.where(nm, 1e3, -1e3)
            others = np.arange(n) != i
            up[others] = np.where(nm[None], -1e3, up[others])

    def shape_silhouette(self) -> None:
        """Silhouette of cut-out textures: may only GROW (smooth diagonal steps), never erode."""
        p, a, lab, n, h, w, r, k = self.p, self.a, self.lab, self.n, self.h, self.w, self.r, self.k
        H, W = self.H, self.W
        opq = a[..., 3] > 0
        self.cutout = bool((~opq).any())
        if not ((~opq).any() and opq.any()):
            return
        near = opq.repeat(r, 0).repeat(r, 1)
        if self.diag:
            # outline may now also lose outer staircase corners; every opaque pixel keeps its centre core
            sil = ndi.gaussian_filter(near.astype(np.float32), p.diag_sigma * k, mode="nearest") > 0.5
            c0, c1 = r // 2 - r // 4, r // 2 + r // 4 + (r % 2)
            core = np.zeros((H, W), bool)
            for y, x in zip(*np.nonzero(opq), strict=True):
                core[y * r + c0 : y * r + c1, x * r + c0 : x * r + c1] = True
            sil |= core
        else:
            grow = self.blur(near.astype(np.float32), p.shape_round * k) > 0.5
            sil = near | grow
        if self.sharp_list:  # don't grow the outline next to protected sharp shapes
            sharp = np.zeros((H, W), bool)
            for _, nm in self.sharp_list:
                sharp |= nm
            sil &= ~(ndi.binary_dilation(sharp, structure=_FULL_3X3) & ~near)
        bb = max(1, r // 2) if self.diag else max(1, r // 4)
        for y in range(h):
            for x in range(w):
                y2, x2 = (y + 1) % h, (x + 1) % w
                if y2 == 0 or x2 == 0:
                    continue
                if (opq[y, x] and opq[y2, x2] and not opq[y, x2] and not opq[y2, x]) or (
                    opq[y, x2] and opq[y2, x] and not opq[y, x] and not opq[y2, x2]
                ):
                    cy, cx = y2 * r, x2 * r
                    sil[(cy - bb) % H : (cy - bb) % H + 2 * bb, (cx - bb) % W : (cx - bb) % W + 2 * bb] = True
        if p.keep_gaps and r >= 2:
            self.carve_gaps(sil, opq)
        up = self.up
        reg_opq = np.array([opq[lab == i].any() for i in range(n)])
        up[reg_opq] = np.where(sil[None], up[reg_opq], -1)
        up[~reg_opq] = np.where(sil[None], -1, up[~reg_opq])

    def carve_gaps(self, sil: BoolArray, opq: BoolArray) -> None:
        """1px see-through diagonal gaps (e.g. between the prongs of a fork) are lines too.

        Where the two opaque pixels across the gap belong to different areas, carve the gap's centre band so the
        outline doesn't fill it. Skipped where carving would split the item into more pieces.
        """
        lab, h, w, r = self.lab, self.h, self.w, self.r
        yb, xb = np.mgrid[0 : 2 * r, 0 : 2 * r]
        cw = max(1, r // 4)
        base = ndi.label(sil, structure=np.ones((3, 3)))[1]
        for y in range(h - 1):
            for x in range(w - 1):
                tl, tr, bl, br = opq[y, x], opq[y, x + 1], opq[y + 1, x], opq[y + 1, x + 1]
                if not tl and not br and tr and bl and lab[y, x + 1] != lab[y + 1, x]:
                    dd = xb - yb  # gap runs '\'
                elif not tr and not bl and tl and br and lab[y, x] != lab[y + 1, x + 1]:
                    dd = xb + yb - (2 * r - 1)  # gap runs '/'
                else:
                    continue
                cen = np.abs(dd) <= cw
                ys, xs = y * r + yb[cen], x * r + xb[cen]
                old = sil[ys, xs].copy()
                sil[ys, xs] = False
                if ndi.label(sil, structure=np.ones((3, 3)))[1] > base:
                    sil[ys, xs] = old

    def group_shapes(self) -> None:
        """Two-level shapes: first decide between GROUPS of similar colours, then between the areas inside the winner.

        E.g. all the blue shades of a painted sign's background vs its white paint. A background split into many small
        shade areas otherwise loses its edges to one big neighbouring area, which grows bumps into it.
        """
        p, a, lab, n, k = self.p, self.a, self.lab, self.n, self.k
        group_lab, group_n = regions(a, p.shape_groups, alpha_split=p.alpha_split)
        area_group = np.array([np.bincount(group_lab[lab == i], minlength=group_n).argmax() for i in range(n)])
        group_masks = np.stack(
            [np.isin(lab, np.nonzero(area_group == g)[0]).astype(np.float32) for g in range(group_n)]
        )
        group_up = np.stack([self.blur(self.upsample(m), p.shape_round * k) for m in group_masks])
        # never let the group step change opacity (cutouts): only groups with the same opacity as the current
        # winner compete
        winner = self.up.argmax(0)
        area_opaque = np.array([(a[..., 3][lab == i] > 0).any() for i in range(n)])
        group_opaque = np.array(
            [area_opaque[area_group == g].any() if (area_group == g).any() else True for g in range(group_n)]
        )
        group_up = np.where(group_opaque[:, None, None] == area_opaque[winner][None], group_up, -1e9)
        win = group_up.argmax(0)
        exempt = np.zeros(n, bool)
        if self.line_core is not None:
            for li in self.line_areas:
                exempt[li] = True  # drawn lines keep their own smooth bands
        penalty = (area_group[:, None, None] != win[None]) & ~exempt[:, None, None]
        if self.stair_w is not None:
            penalty &= ~self.stair_w[None]  # local staircase smoothing decides there
        self.up = np.where(penalty, self.up - 1e2, self.up)

    # -- 3. owner map -------------------------------------------------------------------------------------------------

    def thin_features(self) -> None:
        """Every source pixel keeps its centre core; diagonal-only links of the same area are bridged."""
        lab, h, w, r, H, W = self.lab, self.h, self.w, self.r, self.H, self.W
        owner, opq = self.owner, self.a[..., 3] > 0
        c0, c1 = r // 2 - (r // 4), r // 2 + (r // 4) + (r % 2)
        for y in range(h):
            for x in range(w):
                owner[y * r + c0 : y * r + c1, x * r + c0 : x * r + c1] = lab[y, x]
        # bridge diagonal-only links of the same region (thin stems, outlines)
        b = max(1, r // 4)
        for y in range(h):
            for x in range(w):
                y2, x2 = (y + 1) % h, (x + 1) % w
                if self.cutout and (y2 == 0 or x2 == 0):
                    continue
                cy, cx = y2 * r, x2 * r  # corner point between the four pixels
                sl = (slice((cy - b) % H, (cy - b) % H + 2 * b), slice((cx - b) % W, (cx - b) % W + 2 * b))
                if self.line_core is not None and self.line_core[sl].any():
                    continue  # a line passes here; don't bridge over it
                if lab[y, x] == lab[y2, x2] and lab[y, x2] != lab[y, x] and lab[y2, x] != lab[y, x] and opq[y, x]:
                    owner[sl] = lab[y, x]
                if lab[y, x2] == lab[y2, x] and lab[y, x] != lab[y, x2] and lab[y2, x2] != lab[y, x2] and opq[y, x2]:
                    owner[sl] = lab[y, x2]

    def legacy_line_bands(self) -> None:
        """1px diagonal lines (same colour touching only at corners) -> continuous diagonal band in 1px steps.

        As wide as the original pixel; pure line pixels lose their off-band corners to the neighbouring colour.
        """
        p, a, lab, n, h, w, r, H, W = self.p, self.a, self.lab, self.n, self.h, self.w, self.r, self.H, self.W
        owner, opq = self.owner, a[..., 3] > 0
        half = r // 2
        yb, xb = np.mgrid[0 : 2 * r, 0 : 2 * r]
        linked: dict[tuple[int, int], list[int]] = {}
        ov_m = np.zeros((H, W), bool)
        ov_l = np.zeros((H, W), int)
        rsize = np.bincount(lab.ravel(), minlength=n)

        def thick(py: int, px: int) -> int:
            l0 = lab[py, px]
            return sum(lab[(py + ey) % h, (px + ex) % w] == l0 for ey, ex in NEIGHBOURS_4)

        for y in range(h):
            for x in range(w):
                for dx in (1, -1):
                    y2, x2 = y + 1, x + dx
                    if self.cut and not (0 <= y2 < h and 0 <= x2 < w):
                        continue
                    y2 %= h
                    x2 %= w
                    li = lab[y, x]
                    if lab[y2, x2] != li or lab[y2, x] == li or lab[y, x2] == li:
                        continue
                    if not opq[y, x]:
                        continue
                    # crossing: the other diagonal of this 2x2 also touches only at corners -> connect the smaller shape
                    oa, ob = lab[y2, x], lab[y, x2]
                    if oa == ob and opq[y2, x]:
                        t_me = thick(y, x) + thick(y2, x2)
                        t_other = thick(y2, x) + thick(y, x2)
                        if t_other < t_me:
                            continue  # the other diagonal is the thinner line
                        if t_other == t_me and (rsize[oa], oa) < (rsize[li], li):
                            continue
                    linked.setdefault((y, x), []).append(dx)
                    linked.setdefault((y2, x2), []).append(dx)
                    # band over the 2x2-pixel window spanned by the pair
                    oy = y * r
                    ox = (x if dx == 1 else x - 1) * r
                    band = (np.abs(xb - yb) <= half) if dx == 1 else (np.abs(xb + yb - (2 * r - 1)) <= half)
                    ys = (oy + yb[band]) % H
                    xs = (ox + xb[band]) % W
                    if p.band_mix < 1.0:
                        # cells inside the two line pixels -> line; cells in the neighbours' pixels -> blended overlay
                        by, bx = ys // r, xs // r
                        own = ((by == y) & (bx == x)) | ((by == y2) & (bx == x2))
                        owner[ys[own], xs[own]] = li
                        ov_m[ys[~own], xs[~own]] = True
                        ov_l[ys[~own], xs[~own]] = li
                    else:
                        owner[ys, xs] = li
        self.overlay, self.overlay_label = ov_m, ov_l
        # trim off-band corners of pure line pixels (no same-colour edge neighbour)
        up = self.up.copy()
        yc, xc = np.mgrid[0:r, 0:r]
        for (y, x), dirs in linked.items():
            li = lab[y, x]
            if any(lab[(y + dy) % h, (x + dx) % w] == li for dy, dx in NEIGHBOURS_4):
                continue
            if len(set(dirs)) != 1:
                continue
            dx = dirs[0]
            band = (np.abs(xc - yc) <= half) if dx == 1 else (np.abs(xc + yc - (r - 1)) <= half)
            for yy, xx in zip(*np.nonzero(~band), strict=True):
                py, px = y * r + yy, x * r + xx
                vals = up[:, py, px].copy()
                vals[li] = -1e9
                owner[py, px] = vals.argmax()

    def despeckle(self) -> None:
        """A 1px label island can't be real detail at this scale -> give it the most common neighbour label."""
        owner, H, W = self.owner, self.H, self.W
        for _ in range(2):
            padded = np.pad(owner, 1, mode="edge")
            neighbours = np.stack(
                [padded[1 + dy : 1 + dy + H, 1 + dx : 1 + dx + W] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
            )
            lone = np.all(neighbours != owner[None], 0)
            if not lone.any():
                break
            for y, x in zip(*np.nonzero(lone), strict=True):
                values, counts = np.unique(neighbours[:, y, x], return_counts=True)
                owner[y, x] = values[counts.argmax()]

    # -- 4. colour ----------------------------------------------------------------------------------------------------

    def render(self) -> FloatArray:
        """Colour every output pixel: smooth shading + grain, quantised to the owning area's own palette."""
        p, lab, n, H, W, k = self.p, self.lab, self.n, self.H, self.W, self.k
        rng = np.random.default_rng(self.seed)
        out = np.zeros((H, W, 4), np.float32)
        src = self.a.astype(np.float32)
        for i in range(n):
            m = self.masks[i]
            cols = src[lab == i]
            # normalised-convolution smooth interpolation of this region's shading
            num = self.upsample(np.stack([src[..., c] * m for c in range(4)], -1))
            den = self.upsample(m)
            s = p.smooth * k
            if p.adaptive_smooth is not None and len(cols) > 1 and cols[:, :3].mean(1).std() < p.soft_std:
                # soft, low-contrast areas (bevels, rims, gradients) get strong smoothing so 16px steps vanish;
                # areas with strong internal detail keep the lighter 'more detail' smoothing
                s = p.adaptive_smooth * k
            num = np.stack([self.blur(num[..., c], s) for c in range(4)], -1)
            den = self.blur(den, s)[..., None]
            smooth = num / np.maximum(den, 1e-4)
            # fine grain: amplitude from region's own shading spread
            lum = cols[:, :3].mean(1)
            spread = max(lum.std(), 4.0) if len(cols) > 1 else 0
            noise = rng.standard_normal((H, W)) * spread * 0.9 * p.grain * self.grain_multiplier(m, cols)
            noise = 0.65 * noise + 0.35 * self.blur(noise, 0.7) * 2.0
            shaded = smooth.copy()
            shaded[..., :3] += noise[..., None]
            # quantise to region palette (unique colours of the region)
            palette = np.unique(cols.astype(np.uint8), axis=0).astype(np.float32)
            sel = self.owner == i
            px = shaded[sel]
            if len(palette) > 1:
                d = ((px[:, None, :3] - palette[None, :, :3]) ** 2).sum(-1)
                px = palette[d.argmin(1)]
            else:
                px = np.repeat(palette, len(px), 0)
            out[sel] = px
        return out

    def grain_multiplier(self, m: FloatArray, cols: FloatArray) -> float:
        """Grain strength for one area: outlines / near-black stay solid, pale greys and metals get less."""
        p, cut = self.p, self.cut
        gmul = 1.0
        if p.grain_rules and (cut or not p.rules_items_only):
            rgb = cols[:, :3].mean(0)
            brightness = rgb.mean()
            sat = (rgb.max() - rgb.min()) / max(float(rgb.max()), 1.0)
            thin = not ndi.binary_erosion(m > 0, structure=ndi.generate_binary_structure(2, 1)).any()
            if brightness < 50 or thin:
                gmul = 0.0  # outlines / near-black: solid
            elif sat < 0.18 and brightness > 150 and (cut or not p.grey_full_blocks):
                gmul = 0.3  # white / pale grey / pale metal
            elif sat < 0.18 and (cut or not p.grey_full_blocks):
                gmul = 0.55  # mid greys / metal
            if cut:
                gmul *= 0.7  # items & plants are seen small
        return gmul

    def blend_overlay(self, out: FloatArray) -> None:
        """Blend line colour over what is underneath -> midtone joins between the original line pixels."""
        assert self.overlay is not None and self.overlay_label is not None
        mix = self.p.band_mix
        src = self.a.astype(np.float32)
        for li in np.unique(self.overlay_label[self.overlay]):
            sel = self.overlay & (self.overlay_label == li) & (self.owner != li)
            col = src[self.lab == li].mean(0)
            out[sel, :3] = out[sel, :3] * (1 - mix) + col[:3] * mix

    def restore_dither(self, out: FloatArray) -> None:
        """Checkerboard areas keep their exact 16px pixels (smoothing would blur the pattern away)."""
        p, a, cut = self.p, self.a, self.cut
        fc = self.source_colours()
        opaque = a[..., 3] > 0

        def colour_at(dy: int, dx: int) -> FloatArray:
            return np.roll(np.roll(fc, -dy, 0), -dx, 1)

        def opaque_at(dy: int, dx: int) -> BoolArray:
            return np.roll(np.roll(opaque, -dy, 0), -dx, 1)

        def diff(q: FloatArray) -> FloatArray:
            worst: FloatArray = np.abs(fc - q).max(-1)
            return worst

        sides = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        diagonals = list(DIAGONALS)
        side_diff = np.all([(diff(colour_at(*d)) > p.dither_thr) | ~opaque_at(*d) for d in sides], 0)
        diag_same = (
            np.sum([(diff(colour_at(*d)) < p.dither_thr * 0.5) & opaque_at(*d) for d in diagonals], 0) >= p.dither_min
        )
        dither = opaque & side_diff & diag_same
        # a checker area needs several such pixels together
        dither &= ndi.convolve(dither.astype(int), np.ones((3, 3), int), mode="constant" if cut else "wrap") >= 3
        if dither.any():
            big = self.upsample(dither)
            out[big] = self.upsample(a.astype(np.float32))[big]
