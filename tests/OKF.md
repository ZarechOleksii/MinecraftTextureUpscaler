---
okf: 1
path: tests
purpose: The pytest suite: golden pixel tests for the upscaler plus behaviour tests for the library and every tool.
---

# Tests

`pytest` runs a fast subset (about a minute); `pytest -m "slow or not slow"` is the full golden sweep CI runs. There are
no binary fixtures: textures and a mod jar are built in code. Data pinned for the upscaler lives in
[golden/](golden/OKF.md). Coverage rules are in [.claude/CLAUDE.md](../.claude/CLAUDE.md).

## Support

- [\_\_init\_\_.py](__init__.py): marks the package so `python -m tests.make_golden` works.
- [conftest.py](conftest.py): session fixtures: a synthetic mod jar and the pack `regen4x-run-pack` builds from it.
- [synthetic.py](synthetic.py): `make_textures()` (the golden file was recorded from it; never change its output)
  and `build_mod_jar()`, a jar with every entry kind the pack builder handles.
- [golden_cases.py](golden_cases.py): the case list (every preset plus extra option combinations, scales, ship and
  connected-texture cases), `compute_case()` and `fingerprint()`. A new `RegenParams` option needs a case in `configs()`.
- [make_golden.py](make_golden.py): re-records `golden/expected.json` from current code; only for an intended output
  change. Related: [golden_cases.py](golden_cases.py).

## Tests

- [test_golden.py](test_golden.py): compares every golden case with `golden/expected.json`.
- [test_upscaler_and_ct.py](test_upscaler_and_ct.py): the public `regen4x()` and connected-texture sheets.
  Related: [../src/regen4x/upscaler.py](../src/regen4x/upscaler.py), [../src/regen4x/ct.py](../src/regen4x/ct.py).
- [test_regions_and_lines.py](test_regions_and_lines.py): region and diagonal-line detection on tiny images.
  Related: [../src/regen4x/regions.py](../src/regen4x/regions.py), [../src/regen4x/lines.py](../src/regen4x/lines.py).
- [test_params_and_presets.py](test_params_and_presets.py): `RegenParams`, the built-in presets and their helpers.
- [test_presets_toml.py](test_presets_toml.py): `extends` / `reset`, profile rules, refusals, and the naming rules of
  [../docs/versioning.md](../docs/versioning.md). Related: [../src/regen4x/presets.toml](../src/regen4x/presets.toml).
- [test_upscale_cli.py](test_upscale_cli.py): `regen4x-upscale` for every input and output kind.
- [test_wizard.py](test_wizard.py): `regen4x-wizard` questions and the command it builds.
- [test_make_docs.py](test_make_docs.py): `regen4x-docs`, including that the committed pages under
  [../docs/](../docs/OKF.md) `presets/` are not stale.
- [test_tools.py](test_tools.py): the other tools end to end on the synthetic jar, against `golden/pack_expected.json`.
- [test_edges.py](test_edges.py): what the others miss: every command is registered and starts, broken input, and the
  invariants every preset keeps (size, determinism, clear stays clear).
- [test_integration_samples.py](test_integration_samples.py): builds a jar from
  [../samples/free/](../samples/free/OKF.md) and runs the whole pipeline, leaving results (pack, per-texture report, before / after preview) in
  `build/integration/`; `REGEN_TEST_JAR` runs it on a real mod jar instead.
- [test_okf.py](test_okf.py): runs the OKF documentation check on the repository.
  Related: [../docs/open-knowledge-format.md](../docs/open-knowledge-format.md).
