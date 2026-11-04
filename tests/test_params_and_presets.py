import dataclasses

import numpy as np
import pytest
from PIL import Image

from regen4x import presets
from regen4x.params import RegenParams

# Every default, as it was in the signature of the original regen4x(); nothing but a deliberate change may alter these.
ORIGINAL_DEFAULTS: dict[str, object] = {
    "thr": 0.13,
    "shape_round": 1.6,
    "grain": 1.0,
    "mean_mode": False,
    "mean_k": 1.0,
    "merge_size": 0,
    "merge_thr": 0.2,
    "keep_thin": True,
    "smooth": 2.2,
    "grain_rules": True,
    "keep_sharp": True,
    "sharp_max": 24,
    "sharp_contrast": 0.25,
    "keep_dither": True,
    "dither_thr": 0.12,
    "sharp_flat": 0.06,
    "adaptive_smooth": None,
    "soft_std": 10.0,
    "grey_full_blocks": False,
    "rules_items_only": False,
    "diag_items": False,
    "diag_blocks": False,
    "diag_sigma": 2.5,
    "diag_selective": False,
    "stair_min": 8,
    "diag_join": False,
    "dither_min": 2,
    "line_bands": False,
    "band_mix": 1.0,
    "line_field": False,
    "line_strength": 1.05,
    "line_aa_merge": False,
    "aa_max": 2,
    "line_contrast": 0.1,
    "line_neighbours_diag": False,
    "neighbour_max": 12,
    "alpha_split": False,
    "join_thin_only": False,
    "keep_gaps": False,
    "line_area_diag": False,
    "stair_local": False,
    "stair_run": 3,
    "stair_grow": True,
    "line_confine": False,
    "line_clip": False,
    "clip_end": 1.0,
    "line_min_len": 0,
    "line_strong": 1.0,
    "line_attach": False,
    "line_thru": False,
    "line_reach": False,
    "reach_col": 0.06,
    "line_bend": None,
    "strong_thin": False,
    "single_con": 1.0,
    "shape_groups": 0,
    "split_undrawn": False,
    "skip_edge_lines": False,
    "inner_min_len": 0,
}


def test_every_default_is_unchanged() -> None:
    assert dataclasses.asdict(RegenParams()) == ORIGINAL_DEFAULTS


def test_defaults() -> None:
    p = RegenParams()
    assert (p.thr, p.shape_round, p.smooth, p.grain) == (0.13, 1.6, 2.2, 1.0)
    assert p.line_bend is None
    assert p.keep_thin is True


def test_params_are_frozen_and_keyword_only() -> None:
    p = RegenParams()
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.thr = 0.5  # type: ignore[misc]
    with pytest.raises(TypeError):
        RegenParams(0.5)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RegenParams(no_such_option=1)  # type: ignore[call-arg]


def test_every_named_preset_is_a_params_object() -> None:
    assert presets.PRESETS
    assert all(isinstance(p, RegenParams) for p in presets.PRESETS.values())


def test_presets_build_on_each_other() -> None:
    assert presets.SOLID_V1_6.single_con == 0.26
    assert presets.SOLID_V1_6.shape_groups == 0.2
    assert presets.SOLID_V1_6.line_attach is True  # inherited from solid-v1.3
    assert presets.CUTOUT_V2_1.inner_min_len == 3
    assert presets.CUTOUT_V2_1.diag_items is True  # inherited from items-diag-v1.0
    assert presets.BASE_V1_0.diag_items is False  # the base preset is untouched by those that derive from it


def test_ship_for_picks_by_transparency() -> None:
    solid = Image.new("RGBA", (16, 16), (10, 20, 30, 255))
    cutout = solid.copy()
    cutout.putpixel((0, 0), (0, 0, 0, 0))
    assert presets.ship_for(solid) is presets.SHIP_BLOCK
    assert presets.ship_for(cutout) is presets.SHIP_CUTOUT
    assert presets.has_transparency(cutout)
    assert not presets.has_transparency(solid)


def test_seed_is_stable() -> None:
    assert presets.seed_for("minecraft/textures/block/stone.png") == 384337978
    assert presets.seed_for("") == 3661210606
    assert presets.seed_for("a") != presets.seed_for("b")


def _lossy_pair() -> tuple[Image.Image, Image.Image]:
    """A 16x16 source with one opaque pixel and an upscale (x4) that lost that pixel's transparency."""
    src = np.zeros((16, 16, 4), np.uint8)
    src[3, 5] = (200, 100, 50, 255)
    out = np.zeros((64, 64, 4), np.uint8)  # everything see-through
    return Image.fromarray(src), Image.fromarray(out)


def test_keep_opaque_restores_lost_pixels() -> None:
    src, out = _lossy_pair()
    fixed, count = presets.keep_opaque(src, out)
    assert count == 16  # the 4x4 block of the one opaque source pixel
    a = np.asarray(fixed)
    assert (a[12:16, 20:24] == (200, 100, 50, 255)).all()
    assert a[..., 3].sum() == 16 * 255


def test_finish_only_touches_cutout_block_textures() -> None:
    src, out = _lossy_pair()
    block = presets.finish("m/textures/block/x.png", src, out)
    item = presets.finish("m/textures/item/x.png", src, out)
    assert np.asarray(block)[..., 3].any()
    assert item is out
    solid = Image.new("RGBA", (16, 16), (1, 2, 3, 255))
    assert presets.finish("m/textures/block/x.png", solid, out) is out
