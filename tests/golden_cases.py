import functools
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from regen4x import ct, presets
from regen4x.params import RegenParams
from regen4x.upscaler import regen4x
from tests.synthetic import UInt8Array, make_textures

GOLDEN_DIR = Path(__file__).parent / "golden"
EXPECTED_FILE = GOLDEN_DIR / "expected.json"

CT_KEYS = ("ct_sheet", "ct_tiles", "ct_ops")
SCALE_TEXTURES = ("blob0", "item1", "lines1", "big32")
SCALE_PRESETS = ("base-v1.0", "solid-v1.6", "cutout-v2.1")
SCALES = (2, 3, 8)

# the cases run by a plain `pytest`; the rest are marked slow
FAST_TEXTURES = frozenset({"blob0", "blob3", "lines0", "lines1", "item1", "item5", "dither0", "rect1", "blobA0"})
FAST_PRESETS = frozenset(
    {
        "base-v1.0",
        "solid-v1.6",
        "cutout-v2.1",
        "lines-v1.0",
        "x_line_bands_mix",
        "x_bend_both",
        "x_splitundrawn",
        "x_diag_sel",
        "x_merge",
        "x_adaptive",
    }
)


@functools.cache
def textures() -> dict[str, UInt8Array]:
    return make_textures()


@functools.cache
def configs() -> dict[str, RegenParams]:
    """Every named preset plus extra combinations that reach the rarely used code paths."""
    current = presets.BASE_V1_0
    block, cutout = presets.SOLID_V1_6, presets.CUTOUT_V2_1
    cfg = dict(presets.PRESETS)
    cfg["x_line_bands"] = replace(current, line_bands=True)
    cfg["x_line_bands_mix"] = replace(current, line_bands=True, band_mix=0.5, diag_join=True)
    cfg["x_diag_blocks"] = replace(current, diag_blocks=True, diag_sigma=2.0)
    cfg["x_diag_sel"] = replace(current, diag_blocks=True, diag_selective=True, stair_min=2)
    cfg["x_merge"] = replace(current, merge_size=3, merge_thr=0.25, mean_mode=False)
    cfg["x_adaptive"] = replace(
        current, adaptive_smooth=3.5, soft_std=20.0, grey_full_blocks=True, rules_items_only=False
    )
    cfg["x_nogrens"] = replace(
        current, grain_rules=False, grain=1.0, keep_thin=False, keep_sharp=False, keep_dither=False
    )
    cfg["x_bend_skip"] = replace(block, line_bend="skip", line_min_len=4, line_strong=0.3)
    cfg["x_bend_both"] = replace(block, line_bend="both", line_min_len=4, line_strong=0.3)
    cfg["x_confine"] = replace(
        block, line_confine=True, line_area_diag=True, line_neighbours_diag=True, neighbour_max=30
    )
    cfg["x_skipedge"] = replace(cutout, skip_edge_lines=True, stair_grow=True, line_confine=True)
    cfg["x_splitundrawn"] = replace(cutout, split_undrawn=True, line_aa_merge=True, aa_max=3, line_neighbours_diag=True)
    cfg["x_splitundrawn_blk"] = replace(block, split_undrawn=True, line_aa_merge=True, aa_max=3)
    cfg["x_stair_cutout"] = replace(cutout, stair_local=True, stair_run=2, stair_grow=True, clip_end=2.0)
    return cfg


def fingerprint(im: Image.Image | np.ndarray) -> str:
    """Short hash of an image's (or array's) pixels, shape and dtype."""
    a = np.asarray(im)
    data = a.tobytes() + str(a.shape).encode() + str(a.dtype).encode()
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()[:16]


def all_case_keys() -> list[str]:
    """Every case: texture|preset, scale<N>|texture|preset, ship|texture and the three connected-texture ones."""
    texs, cfgs = textures(), configs()
    keys = [f"{t}|{c}" for t in sorted(texs) for c in sorted(cfgs)]
    keys += [f"scale{sc}|{t}|{c}" for t in SCALE_TEXTURES for sc in SCALES for c in SCALE_PRESETS]
    keys += [f"ship|{t}" for t in sorted(texs)]
    return sorted(keys + list(CT_KEYS))


def is_fast(key: str) -> bool:
    if key.startswith(("ship|", "scale")) or key in CT_KEYS:
        return True
    texture, preset = key.split("|")
    return texture in FAST_TEXTURES and preset in FAST_PRESETS


def compute_case(key: str) -> str:
    """The fingerprint of one case (everything except the connected-texture ones, see :func:`compute_ct`)."""
    texs, cfgs = textures(), configs()
    if key.startswith("ship|"):
        im = Image.fromarray(texs[key.split("|")[1]])
        out = regen4x(im, presets.ship_for(im), seed=presets.seed_for("m/textures/block/x.png"), scale=4)
        return fingerprint(presets.finish("m/textures/block/x.png", im, out)) + fingerprint(
            presets.finish("m/textures/item/x.png", im, out)
        )
    if key.startswith("scale"):
        label, texture, preset = key.split("|")
        out = regen4x(Image.fromarray(texs[texture]), cfgs[preset], seed=5, scale=int(label.removeprefix("scale")))
        return fingerprint(out)
    texture, preset = key.split("|")
    debug: dict[str, np.ndarray] = {}
    seed = presets.seed_for(f"mod/textures/block/{texture}.png")
    out = regen4x(Image.fromarray(texs[texture]), cfgs[preset], seed=seed, debug=debug)
    return "|".join([fingerprint(out), fingerprint(debug["final_L"]), fingerprint(debug["lab"])])


def compute_ct() -> dict[str, str]:
    """A connected-texture sheet run through ``ct.upscale_sheet``: pixels, tile set and open sides."""
    rng = np.random.default_rng(7)
    base = textures()["blob2"].copy()
    sheet = np.zeros((48, 64, 4), np.uint8)
    for ty in range(3):
        for tx in range(4):
            t = base.copy()
            if (ty, tx) != (0, 0):
                if tx % 2:
                    t[:, :2, :3] = rng.integers(0, 256, 3)
                if ty % 2:
                    t[:2] = rng.integers(0, 256, 4)
                    t[:2, :, 3] = 255
                if tx == 3:
                    t[:, -2:, :3] = 20
                if (ty, tx) == (2, 1):
                    t[...] = 0  # empty tile
            sheet[ty * 16 : (ty + 1) * 16, tx * 16 : (tx + 1) * 16] = t
    base_im = Image.fromarray(base)
    base_up = regen4x(base_im, presets.ship_for(base_im), seed=presets.seed_for("m/textures/block/c.png"), scale=4)
    out, tiles, op = ct.upscale_sheet(Image.fromarray(sheet), base_im, base_up, "m/textures/block/c_connected.png")
    return {
        "ct_sheet": fingerprint(out),
        "ct_tiles": repr(sorted(map(list, tiles.keys()))),
        "ct_ops": repr(sorted((k, sorted(v.items())) for k, v in op.items())),
    }


def load_expected() -> dict[str, str]:
    cases: dict[str, str] = json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))["cases"]
    return cases
