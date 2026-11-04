---
okf: 1
path: src/regen4x
purpose: The regen4x library: the edge-aware upscaler, its tunables, the named presets and the connected-texture sheets.
---

# regen4x library

Turns a 16px RGBA texture into a 64px one (any scale 2-8). The output is deterministic for a given texture and seed;
[tests/golden/expected.json](../../tests/golden/OKF.md) pins it. Nothing here parses command lines: that is
[tools/](tools/OKF.md), which imports this package, never the other way round. The pipeline, in order: split the source
into areas of similar colour, find 1px diagonal lines, upscale the area shapes with consistent rounding, interpolate
shading inside each area, then add grain and quantise to the area's own palette.

## Files

- [\_\_init\_\_.py](__init__.py): re-exports `regen4x` and `RegenParams`, the whole public entry point.
- [\_common.py](_common.py): numpy type aliases (`IntArray`, `FloatArray`, ...), the `Pair` link type, and the
  neighbour-order constants every scan uses (the order matters for tie-breaking, so output depends on it).
- [params.py](params.py): `RegenParams`, the frozen dataclass of every tunable, grouped as regions, shapes, shading
  and grain, dithering, and 1px diagonal lines. Presets are built from it with `dataclasses.replace`; a new option
  needs a golden case.
  Related: [presets.toml](presets.toml), [../../tests/golden_cases.py](../../tests/golden_cases.py).
- [regions.py](regions.py): step 1. Flood-fills the source into same-colour areas (wrapping, since textures tile),
  merges speckle regions, and finds pixels on real staircase diagonals.
  Related: [lines.py](lines.py), [../../tests/test_regions_and_lines.py](../../tests/test_regions_and_lines.py).
- [lines.py](lines.py): finds same-area pixels that touch only at a corner and keeps the ones that read as real 1px
  lines (by chain length or contrast), resolving bends and attaching short pieces to long lines.
  Related: [regions.py](regions.py), [upscaler.py](upscaler.py).
- [upscaler.py](upscaler.py): `regen4x()` and the `_Upscaler` class, one method per stage: labelling, shape fields,
  line fields, silhouette and gaps, despeckle, shading render, grain, dither restore.
  Related: [params.py](params.py), [../../tests/test_upscaler_and_ct.py](../../tests/test_upscaler_and_ct.py).
- [presets.toml](presets.toml): every named preset (`extends` / `reset` over `RegenParams`) and every profile (rules
  that pick a preset per texture), as data. Its header is the format reference. Published presets are never edited.
  Related: [../../docs/versioning.md](../../docs/versioning.md), [../../docs/presets/README.md](../../docs/presets/README.md).
- [presets.py](presets.py): loads that TOML (and user files) into `Book`s of presets and profiles with validation,
  and exposes `PRESETS`, `ship_for()`, `finish()` (restores source-opaque pixels where a rule asks), `seed_for()`
  (the per-texture seed derived from its path) and `has_transparency()`.
  Related: [../../tests/test_presets_toml.py](../../tests/test_presets_toml.py),
  [../../tests/test_params_and_presets.py](../../tests/test_params_and_presets.py).
- [ct.py](ct.py): connected-texture sheets. Upscales each 16px tile inside a 3x3 context of its best-continuing
  neighbour tiles (open sides only) and keeps the centre, so seams match; a tile equal to the single block reuses that
  block's output. Related: [tools/run_pack.py](tools/run_pack.py), [tools/ct_check.py](tools/ct_check.py).

## Subdirectories

- [tools/](tools/OKF.md): the command-line tools built on this library.
