import numpy as np
import pytest
from PIL import Image

import regen4x
from regen4x import ct, presets
from regen4x.params import RegenParams
from tests.golden_cases import textures


def _img(name: str) -> Image.Image:
    return Image.fromarray(textures()[name])


def test_package_exports_the_public_api() -> None:
    assert regen4x.RegenParams is RegenParams
    assert callable(regen4x.regen4x)


def test_output_size_follows_the_scale() -> None:
    assert regen4x.regen4x(_img("blob0")).size == (64, 64)
    assert regen4x.regen4x(_img("blob0"), scale=2).size == (32, 32)
    assert regen4x.regen4x(_img("big32")).size == (64, 64)  # 32px sources default to x2
    assert regen4x.regen4x(_img("blob0")).mode == "RGBA"


def test_same_seed_same_output_different_seed_different_grain() -> None:
    im = _img("blob0")
    a = regen4x.regen4x(im, presets.SOLID_V1_6, seed=1)
    b = regen4x.regen4x(im, presets.SOLID_V1_6, seed=1)
    c = regen4x.regen4x(im, RegenParams(grain=2.0), seed=2)
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert not np.array_equal(np.asarray(a), np.asarray(c))


def test_params_none_means_defaults() -> None:
    im = _img("blob0")
    assert np.array_equal(np.asarray(regen4x.regen4x(im)), np.asarray(regen4x.regen4x(im, RegenParams())))


def test_source_image_is_not_modified() -> None:
    im = _img("lines0")
    before = im.tobytes()
    regen4x.regen4x(im, presets.LINES_V1_0)
    assert im.tobytes() == before


def test_flat_texture_stays_flat() -> None:
    out = np.asarray(regen4x.regen4x(_img("flat")))
    assert (out == (120, 80, 40, 255)).all()


def test_output_only_uses_colours_of_the_source() -> None:
    im = _img("blob0")
    out = np.asarray(regen4x.regen4x(im, presets.BASE_V1_0)).reshape(-1, 4)
    source_colours = {tuple(c) for c in np.asarray(im).reshape(-1, 4)}
    assert {tuple(c) for c in out} <= source_colours


def test_cutout_keeps_its_transparent_background() -> None:
    im = _img("item0")
    out = np.asarray(regen4x.regen4x(im, presets.SHIP_CUTOUT))
    assert (out[..., 3] == 0).any()
    assert (out[..., 3] == 255).any()
    assert set(np.unique(out[..., 3])) <= set(np.unique(np.asarray(im)[..., 3]))  # no new opacity levels appear


def test_debug_maps_have_the_expected_shapes() -> None:
    debug: dict[str, np.ndarray] = {}
    regen4x.regen4x(_img("lines1"), presets.LINES_V1_0, debug=debug)
    assert debug["lab"].shape == (16, 16)
    assert debug["final_L"].shape == (64, 64)
    assert debug["final_L"].max() <= debug["lab"].max()


# ---- connected textures ---------------------------------------------------------------------------------------------


def _sheet() -> tuple[np.ndarray, np.ndarray]:
    """A 2x2 sheet: the plain block, and three tiles whose left / top edges differ from it."""
    base = textures()["blob2"].copy()
    sheet = np.zeros((32, 32, 4), np.uint8)
    for ty in range(2):
        for tx in range(2):
            t = base.copy()
            if tx:
                t[2:-2, :2, :3] = (250, 10, 10)  # differs along the left edge (not the corners: top/bottom stay closed)
            if ty:
                t[:2, 2:-2, :3] = (10, 10, 250)
            sheet[ty * 16 : (ty + 1) * 16, tx * 16 : (tx + 1) * 16] = t
    return sheet, base


def test_split_skips_empty_tiles() -> None:
    sheet, _ = _sheet()
    sheet[16:, 16:] = 0
    assert set(ct.split(Image.fromarray(sheet))) == {(0, 0), (0, 1), (1, 0)}


def test_opens_marks_the_sides_that_differ_from_the_block() -> None:
    sheet, base = _sheet()
    tiles = ct.split(Image.fromarray(sheet))
    assert not any(ct.opens(tiles[0, 0], base).values())
    assert ct.opens(tiles[0, 1], base) == {"u": False, "d": False, "l": True, "r": False}
    assert ct.opens(tiles[1, 0], base) == {"u": True, "d": False, "l": False, "r": False}


def test_pick_only_offers_tiles_open_on_the_matching_side() -> None:
    sheet, base = _sheet()
    tiles = ct.split(Image.fromarray(sheet))
    op = {k: ct.opens(t, base) for k, t in tiles.items()}
    # a neighbour to the right of the plain tile must be open on its left side: only tile (0, 1) or (1, 1) are
    chosen = ct.pick(tiles[0, 0], "r", tiles, op)
    assert chosen is not None
    assert any(np.array_equal(chosen, tiles[k]) for k in ((0, 1), (1, 1)))
    assert ct.pick(tiles[0, 0], "l", {(0, 0): tiles[0, 0]}, {(0, 0): op[0, 0]}) is None


def test_context_is_three_by_three_tiles() -> None:
    sheet, base = _sheet()
    tiles = ct.split(Image.fromarray(sheet))
    op = {k: ct.opens(t, base) for k, t in tiles.items()}
    c = ct.context(tiles[1, 1], tiles, op[1, 1], op)
    assert c.shape == (48, 48, 4)
    assert np.array_equal(c[16:32, 16:32], tiles[1, 1])


@pytest.mark.parametrize("name", ["blob2"])
def test_upscale_sheet_reuses_the_block_output_for_the_plain_tile(name: str) -> None:
    sheet, base = _sheet()
    base_im = Image.fromarray(base)
    base_up = regen4x.regen4x(base_im, presets.ship_for(base_im), seed=3, scale=4)
    out, tiles, _ = ct.upscale_sheet(Image.fromarray(sheet), base_im, base_up, "m/textures/block/x_connected.png")
    assert out.size == (128, 128)
    assert len(tiles) == 4
    assert np.array_equal(np.asarray(out)[:64, :64], np.asarray(base_up))  # tile (0, 0) == the single block
    assert not np.array_equal(np.asarray(out)[:64, 64:], np.asarray(base_up))
