---
okf: 1
path: docs
purpose: Hand-written documentation about versioning and OKF, and the generated preset documentation.
---

# Docs

## Files

- [versioning.md](versioning.md): what `family-vMAJOR.MINOR`, `name-rN` and the package version mean and when each
  changes. Related: [../src/regen4x/presets.toml](../src/regen4x/presets.toml),
  [../tests/test_presets_toml.py](../tests/test_presets_toml.py).
- [open-knowledge-format.md](open-knowledge-format.md): the Open Knowledge Format this repository documents itself in, and what the CI check enforces.

## Generated

`presets/` is written by `regen4x-docs` ([make_docs.py](../src/regen4x/tools/make_docs.py)) from `presets.toml` and
[samples.toml](../samples/free/samples.toml): [presets/README.md](presets/README.md) is the index with the comparison
sheets, `presets/<preset>.md` is one page per preset (changes against its parent, all settings, before / after images)
and `presets/img/` holds the images. Never edit by hand; CI fails when a regeneration changes anything.
