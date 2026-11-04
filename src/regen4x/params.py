from dataclasses import dataclass
from typing import Literal

__all__ = ["RegenParams"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RegenParams:
    """All tunables of :func:`regen4x`. Presets are built with :func:`dataclasses.replace`."""

    # --- regions
    thr: float = 0.13
    mean_mode: bool = False
    mean_k: float = 1.0
    merge_size: int = 0
    merge_thr: float = 0.2
    diag_join: bool = False
    alpha_split: bool = False
    join_thin_only: bool = False

    # --- shapes
    shape_round: float = 1.6
    keep_thin: bool = True
    keep_sharp: bool = True
    sharp_max: int = 24
    sharp_contrast: float = 0.25
    sharp_flat: float = 0.06
    shape_groups: float = 0
    diag_items: bool = False
    diag_blocks: bool = False
    diag_sigma: float = 2.5
    diag_selective: bool = False
    stair_min: int = 8
    stair_local: bool = False
    stair_run: int = 3
    stair_grow: bool = True
    keep_gaps: bool = False

    # --- shading and grain
    grain: float = 1.0
    smooth: float = 2.2
    grain_rules: bool = True
    adaptive_smooth: float | None = None
    soft_std: float = 10.0
    grey_full_blocks: bool = False
    rules_items_only: bool = False

    # --- dithering
    keep_dither: bool = True
    dither_thr: float = 0.12
    dither_min: int = 2

    # --- 1px diagonal lines
    line_bands: bool = False
    band_mix: float = 1.0
    line_field: bool = False
    line_strength: float = 1.05
    line_aa_merge: bool = False
    aa_max: int = 2
    line_contrast: float = 0.1
    line_neighbours_diag: bool = False
    neighbour_max: int = 12
    line_area_diag: bool = False
    line_confine: bool = False
    line_clip: bool = False
    clip_end: float = 1.0
    line_min_len: int = 0
    line_strong: float = 1.0
    line_attach: bool = False
    line_thru: bool = False
    line_reach: bool = False
    reach_col: float = 0.06
    line_bend: Literal["skip", "both"] | None = None
    strong_thin: bool = False
    single_con: float = 1.0
    split_undrawn: bool = False
    skip_edge_lines: bool = False
    inner_min_len: int = 0
