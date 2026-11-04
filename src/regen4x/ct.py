from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from regen4x import presets
from regen4x.upscaler import regen4x

type Side = Literal["u", "d", "l", "r"]
type Tile = NDArray[np.uint8]
type Tiles = dict[tuple[int, int], Tile]  # (tile row, tile column) -> 16x16 RGBA tile
type OpenSides = dict[Side, bool]

T = 16
PAD = 6  # context kept around each tile (px of the 16px source); 6 gives the same shapes as a full 16px ring
# (0-0.1% of pixels change colour noticeably, seams equal) and is ~2.6x faster
DIRS: dict[Side, tuple[int, int]] = {"u": (-1, 0), "d": (1, 0), "l": (0, -1), "r": (0, 1)}
OPP: dict[Side, Side] = {"u": "d", "d": "u", "l": "r", "r": "l"}
SIDE_AT: dict[tuple[int, int], Side] = {step: side for side, step in DIRS.items()}


def edge(a: Tile, s: Side) -> NDArray[np.float32]:
    """The row/column of pixels along side ``s`` of tile ``a``."""
    pixels: NDArray[np.float32] = {"u": a[0], "d": a[-1], "l": a[:, 0], "r": a[:, -1]}[s].astype(np.float32)
    return pixels


def split(sheet: Image.Image) -> Tiles:
    """All non-empty 16x16 tiles of a CT sheet."""
    a = np.asarray(sheet.convert("RGBA"))
    out: Tiles = {}
    for ty in range(a.shape[0] // T):
        for tx in range(a.shape[1] // T):
            t = a[ty * T : (ty + 1) * T, tx * T : (tx + 1) * T]
            if (t[..., 3] > 0).any():
                out[ty, tx] = t
    return out


def opens(t: Tile, base: Tile, thr: float = 12) -> OpenSides:
    """Which sides of tile ``t`` differ from the single-block texture ``base`` (those sides connect to a neighbour)."""
    return {s: float(np.abs(edge(t, s) - edge(base, s)).mean()) > thr for s in DIRS}


def pick(t: Tile, s: Side, tiles: Tiles, op: dict[tuple[int, int], OpenSides]) -> Tile | None:
    """Best tile to put on side s of tile t (it must be open on the opposite side)."""
    best: Tile | None = None
    best_score = 1e9
    for key, n in tiles.items():
        if not op[key][OPP[s]]:
            continue
        score = float(np.abs(edge(t, s) - edge(n, OPP[s])).mean())
        score -= 0.5 * sum(op[key].values())  # tie-break: prefer the most open (plain middle) tile
        if score < best_score:
            best, best_score = n, score
    return best


def context(t: Tile, tiles: Tiles, op_t: OpenSides, op: dict[tuple[int, int], OpenSides]) -> Tile:
    """3x3 tiles around ``t``: its best-continuing neighbours on open sides, itself on closed ones."""
    c = np.zeros((3 * T, 3 * T, 4), np.uint8)
    nb: dict[Side, Tile] = {}
    for s in DIRS:
        n = pick(t, s, tiles, op) if op_t[s] else None
        nb[s] = n if n is not None else t
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                n = t
            elif dy == 0 or dx == 0:
                n = nb[SIDE_AT[dy, dx]]
            else:
                sv: Side = "u" if dy < 0 else "d"
                sh: Side = "l" if dx < 0 else "r"
                n = t
                if op_t[sv] and op_t[sh]:
                    horizontal = nb[sh]
                    cand = pick(horizontal, sv, tiles, op) if horizontal is not t else None
                    n = cand if cand is not None else t
            c[(dy + 1) * T : (dy + 2) * T, (dx + 1) * T : (dx + 2) * T] = n
    return c


def upscale_sheet(
    sheet: Image.Image,
    base: Image.Image,
    base_up: Image.Image,
    rel: str,
    scale: int = 4,
    profile: presets.Profile | None = None,
) -> tuple[Image.Image, Tiles, dict[tuple[int, int], OpenSides]]:
    """Upscale a CT sheet by ``scale``. ``base`` is the 16x16 single-block texture, ``base_up`` its upscaled output.

    The preset of every tile comes from ``profile`` (default: the standard profile), as for a single texture.
    """
    profile = profile or presets.STANDARD_PROFILE
    side = T * scale
    pad = PAD * scale
    tiles = split(sheet)
    b = np.asarray(base.convert("RGBA"))
    op = {k: opens(t, b) for k, t in tiles.items()}
    width, height = sheet.size
    out = np.zeros((height * scale, width * scale, 4), np.uint8)
    bu = np.asarray(base_up.convert("RGBA"))
    seed = presets.seed_for(rel)
    for (ty, tx), t in tiles.items():
        if np.array_equal(t, b):
            o = bu
        else:
            c = context(t, tiles, op[ty, tx], op)[T - PAD : 2 * T + PAD, T - PAD : 2 * T + PAD]
            ctx = Image.fromarray(np.ascontiguousarray(c))
            choice = profile.choose(rel, ctx)
            u = regen4x(ctx, choice.params, seed=seed, scale=scale)
            u = presets.finish_choice(choice, ctx, u)
            o = np.asarray(u)[pad : pad + side, pad : pad + side]
        out[ty * side : (ty + 1) * side, tx * side : (tx + 1) * side] = o
    return Image.fromarray(out), tiles, op
