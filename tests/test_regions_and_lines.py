import numpy as np

from regen4x.lines import line_pairs, real_lines
from regen4x.regions import merge_small, regions, staircase_mask


def _image(size: int = 8, bg: tuple[int, int, int] = (100, 100, 100)) -> np.ndarray:
    a = np.zeros((size, size, 4), np.uint8)
    a[..., :3] = bg
    a[..., 3] = 255
    return a


def _diagonal() -> np.ndarray:
    """A red 1px diagonal on a grey background."""
    a = _image()
    for i in range(8):
        a[i, i, :3] = (255, 0, 0)
    return a


def test_two_colour_halves_are_two_regions() -> None:
    a = _image(16)
    a[:, 8:, :3] = (0, 0, 200)
    lab, n = regions(a, 0.1)
    assert n == 2
    assert len(np.unique(lab)) == 2
    assert lab[0, 0] != lab[0, 15]


def test_regions_wrap_around_the_edges() -> None:
    a = _image(16)
    a[:, 4:12, :3] = (0, 0, 200)  # the grey stripe is split by the image edge but touches itself when tiled
    _, n = regions(a, 0.1)
    assert n == 2


def test_threshold_decides_whether_similar_colours_merge() -> None:
    a = _image(8)
    a[:, 4:, :3] = (110, 100, 100)  # 10/255 ~ 0.04 apart
    assert regions(a, 0.1)[1] == 1
    assert regions(a, 0.02)[1] == 2


def test_see_through_and_opaque_pixels_never_share_a_region() -> None:
    a = _image(8)
    a[2:4, 2:4, 3] = 0
    lab, n = regions(a, 0.5)
    assert n == 2
    assert lab[2, 2] != lab[0, 0]


def test_diag_join_links_corner_touching_pixels() -> None:
    a = _diagonal()
    assert regions(a, 0.1)[1] == 9  # 8 separate red pixels + the background
    lab, n = regions(a, 0.1, diag_join=True)
    assert n == 2
    assert len({lab[i, i] for i in range(8)}) == 1


def test_merge_small_absorbs_a_speckle() -> None:
    a = _image(8)
    a[4, 4, :3] = (110, 100, 100)
    lab, n = regions(a, 0.02)
    assert n == 2
    merged, m = merge_small(a, lab, max_size=1, mthr=0.2)
    assert m == 1
    assert len(np.unique(merged)) == 1


def test_staircase_mask_finds_diagonal_edges_only() -> None:
    triangle = np.tri(16, dtype=int)  # lower-left triangle: a long 1px staircase along the diagonal
    assert staircase_mask(triangle, 2).any()
    rect = np.zeros((16, 16), int)
    rect[4:12, 4:12] = 1
    assert staircase_mask(rect, 2).sum() == 0


def test_line_pairs_follow_the_diagonal() -> None:
    a = _diagonal()
    lab, n = regions(a, 0.1, diag_join=True)
    fc = a[..., :3].astype(np.float32) / 255
    pairs = line_pairs(lab, n, True, a[..., 3] > 0, fc, 0.05)
    assert len(pairs) == 7  # (i, i) -> (i + 1, i + 1) for i in 0..6 (no wrap when the image is a cut-out)
    assert {(y, x, dx) for _, y, x, dx in pairs} == {(i, i, 1) for i in range(7)}
    assert len(line_pairs(lab, n, False, a[..., 3] > 0, fc, 0.05)) == 8  # tiling adds the wrap-around link


def test_real_lines_keeps_long_chains_and_drops_weak_short_ones() -> None:
    a = _diagonal()
    lab, n = regions(a, 0.1, diag_join=True)
    fc = a[..., :3].astype(np.float32) / 255
    pairs = line_pairs(lab, n, True, a[..., 3] > 0, fc, 0.05)
    assert real_lines(pairs, a, True, 5, 1.0, lab=lab) == pairs  # the whole 8px chain counts as one line
    assert real_lines(pairs, a, True, 20, 1.0, lab=lab) == []  # chain too short, contrast (0.6) below "strong"
    assert real_lines(pairs, a, True, 20, 0.5, lab=lab) == pairs  # ...but kept when the contrast alone is strong
