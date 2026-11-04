# Project instructions

regen4x: edge-aware upscaler for 16px modded Minecraft textures (2x to 8x, default 4x), plus resource-pack build/check tools.
See `README.md` for usage. Everything is configured in `pyproject.toml`.

## Layout and documentation (OKF)

The repository documents itself in the Open Knowledge Format: every directory that holds files has an `OKF.md` that says
what each file contains and does and links to the related files. Start at `OKF.md` in the repository root; the format
and the rules the check enforces are in `docs/open-knowledge-format.md`. Directories: `src/regen4x/` (library),
`src/regen4x/tools/` (commands), `tests/` (with `golden/`), `docs/` (`docs/presets/` is generated), `samples/free/`,
`.github/`, `.claude/`.

**Keep it current.** Any change that adds, removes, renames, or changes what a file contains or does updates that
directory's `OKF.md` in the same commit; a new directory gets an `OKF.md` linked from its parent's. Describe what a
file is for in the `OKF.md`, not in a header comment: do not add module docstrings or file-header comments (a tool's
module docstring is the exception, it is its `--help` text). Keep comments only for the *why* of a non-obvious line.
`docs/presets/` is generated and described in `docs/OKF.md`.

Keep the library (modules directly in `src/regen4x/`) free of CLI concerns, and put anything with `argparse` or a
`main()` in `tools/`. The tools may import the library, never the other way round.

## Before every commit: run the code standards check

Run these from the repository root and fix everything they report. **Do not commit while any of them fails.**

```bash
pip install -e . ruff mypy pytest   # once
ruff format .                       # 1. format (rewrites files; stage the result)
ruff check .                        # 2. lint
mypy                                # 3. type check (src and tests)
pytest                              # 4. tests, about a minute (includes the OKF check)
python .github/scripts/okf_check.py # 5. documentation: every file described in its OKF.md
```

To check without rewriting files: `ruff format --check . && ruff check . && mypy && pytest`.

`.github/workflows/ci.yml` runs these on every pull request (and on pushes to master): format, lint and types; the OKF
documentation check (it also warns on a pull request when a changed file's `OKF.md` was not touched); the full
golden sweep under coverage (`fail_under` in `pyproject.toml`, and 90% of the lines a pull request changes must be
covered, checked by diff-cover); and `regen4x-docs` followed by `.github/scripts/docs_check.py`, which fails when
anything under `docs/` changed (PNGs by pixels: their bytes differ between Windows and Linux). The job
summary shows the test results and coverage, and the HTML report is an artifact. Keep it in step with this list.

If you touched anything under `src/regen4x/` other than `tools/`, run the full golden sweep as well (about two minutes):

```bash
pytest -m "slow or not slow"
```

Prefer fixing the cause over silencing a rule. Use `# noqa: <code>` or `# type: ignore[<code>]` only with a short reason,
and never to hide a real problem. `ruff check --fix` is fine for safe fixes; read what it changed.

### What the standards are

Everything is configured in `pyproject.toml`; that file is the source of truth. In short:

- **Python 3.12+** (`requires-python`, ruff `target-version = "py312"`). Use modern syntax: `X | None` (not `Optional`),
  built-in generics (`list[int]`, `dict[str, int]`), PEP 695 `type` aliases (not `TypeAlias`), `zip(..., strict=True)`.
- **Formatting**: `ruff format`, line length 120. Never hand-format around it.
- **Lint rule sets** (ruff): pycodestyle `E`/`W`, pyflakes `F`, isort `I`, pep8-naming `N`, pyupgrade `UP`, bugbear `B`,
  comprehensions `C4`, simplify `SIM`, `PTH` (use `pathlib`, not `os.path`), `RET`, `RUF`, `PERF`, and `S324`
  (hashes need `usedforsecurity=False`). The one standing exception: `N806` is ignored in `upscaler.py`, where `H`/`W`
  (output size) sit next to `h`/`w` (source size).
- **Types**: every function is annotated (`disallow_untyped_defs`), `check_untyped_defs` and `warn_return_any` are on.
  scipy has no stubs, so values coming out of `scipy.ndimage` are annotated at the assignment
  (`x: FloatArray = ndi.gaussian_filter(...)`) rather than returned directly.
- **Structure conventions**:
  - Tools expose `main(argv: Sequence[str] | None = None) -> int`, use `argparse`, end with
    `if __name__ == "__main__": raise SystemExit(main())`, and are listed in `[project.scripts]`.
  - Imports are absolute (`from regen4x.params import RegenParams`). No `sys.path` hacks.
  - No mutable module globals. Pass state explicitly (see `Budget`, `Cache`, `Stats` in `tools/run_pack.py`).
  - Upscaler settings live in the frozen `RegenParams` dataclass. Derive presets with `dataclasses.replace`; never add
    loose keyword arguments to `regen4x`.
  - Paths are `pathlib.Path`; zip files, images and other handles are used in `with` blocks.
  - One statement per line (no `if x: continue` one-liners, no `;`).
- **Line endings**: CRLF in the working tree on every platform, LF inside the repository. This is set by
  `.gitattributes` (`* text=auto eol=crlf`), `.editorconfig` and ruff's `line-ending = "cr-lf"`; do not convert
  files to LF. If git suddenly shows every file as modified after line-ending rules change, run
  `git add --renormalize <files>` (it stages nothing when only the line endings differ).

## Names and versions

Presets are `family-vMAJOR.MINOR`, profiles are `name-rN` plus the alias `standard`; `docs/versioning.md` says what the
parts mean and when each number changes. In short: a published preset is never edited (a change that alters pixels is a
new version that `extends` the old one), every preset has a `status` and a one-line `changelog`, shipping a new version
means a new profile release and marking the replaced presets `superseded`. `tests/test_presets_toml.py` checks the
naming. Keep the document in step when the rules change.

## Preset documentation is generated

After changing `presets.toml` (a preset, its `description`, a profile) or `samples/free/samples.toml`, run `regen4x-docs`
and commit `docs/presets`; `tests/test_make_docs.py` fails when the committed pages are stale. Every preset needs a
`description`. Only textures that may be redistributed go into `samples/free` (give their author and license as `credit`);
anything else must not be committed.

## Output must stay deterministic

The upscaler's output is deterministic (seed comes from the texture path), and the pack cache is keyed by a hash of the
library's source. A refactor must not change a single pixel.

`tests/golden/expected.json` pins this: it holds a fingerprint of the output for every preset (and some extra option
combinations) on a set of synthetic textures. `pytest` runs a representative subset; the full sweep is
`pytest -m "slow or not slow"`. If a golden test fails, the code is wrong, not the test.

Only for a change that is *meant* to alter the output (new preset, algorithm tweak):

```bash
python -m tests.make_golden          # re-records tests/golden/expected.json from the current code
```

and say so in the commit message. Then run `regen4x-docs` too: the documentation images change with the output.
The recorded fingerprints also depend on the numpy / scipy / pillow versions
(`expected.json` notes which); a failure that only appears after upgrading those is an environment difference to
investigate, not something to silence.

When adding an option to `RegenParams`, also add a case that exercises it to `configs()` in `tests/golden_cases.py`
(otherwise nothing pins its behaviour), then re-record.

## How to make a change

Whatever the change: work on a branch, make it, run the four checks above (plus the golden sweep and `regen4x-docs` where
the sections below say so), and open a pull request. CI runs the same checks; a pull request merges when it is green.
Fix a bug test-first: write the test that fails, then the fix. Keep a change to one concern.

| You want to... | Do this |
|---|---|
| **Change how a texture is upscaled** (the modules directly in `src/regen4x/`) | Edit the code. If the output must stay the same (refactor, speed-up), the golden sweep must pass untouched. If it is meant to change: `python -m tests.make_golden`, then `regen4x-docs`, commit `tests/golden/expected.json` and `docs/presets`, and say in the commit message that the output changes and why. |
| **Add a tunable** | Add the field to `RegenParams` in `params.py` (with a default that keeps today's output) and say what it does in a comment next to it. Add a case that uses it to `configs()` in `tests/golden_cases.py` and re-record the golden file. Use it from a preset in `presets.toml` if it is meant to ship. |
| **Add or change a preset or profile** | Edit `presets.toml` only (no code). Every preset needs a `description`, a `status` and a `changelog`, and a change that alters output is a new version, never an edit (`docs/versioning.md`). A new preset is picked up by the golden cases automatically, so re-record the golden file; then run `regen4x-docs` and commit `docs/presets`. A change to an existing preset changes its output: follow the first row. |
| **Add a sample texture for the docs** | Only if it may be redistributed. Put the PNG in `samples/free/`, add an entry to `samples/free/samples.toml` (with author and license as `credit`) and to `samples/free/NOTICE.md`, run `regen4x-docs`, commit `docs/presets`. |
| **Add a command-line tool** | New module in `src/regen4x/tools/` with `main(argv) -> int` and the `__main__` guard (see the structure conventions), a line in `[project.scripts]`, a row in the README's command table, and tests for its `main`. `tests/test_edges.py` fails if a tool is not registered. |
| **Change a dependency or the Python version** | Edit `requirements.txt` / `pyproject.toml`. If the golden sweep then fails on tiny differences, treat it as an environment difference (see above), not something to silence. |
| **Add, move, delete or change the role of a file** | Update the `OKF.md` of its directory (entry with what it contains and does, plus `Related:` links), and the parent's if a directory appears or goes. `python .github/scripts/okf_check.py` must pass. |
| **Change CI** | Edit `.github/workflows/ci.yml` and keep the list of checks in this file in step with it. |
| **Change the docs** | Prose: edit `README.md` or this file. The pages under `docs/presets/` are generated: never edit them by hand. |

### Which test goes where

- `test_golden.py` pins the upscaler's pixels (see above). `test_upscaler_and_ct.py`, `test_regions_and_lines.py`,
  `test_params_and_presets.py` and `test_presets_toml.py` cover the library's behaviour.
- `test_upscale_cli.py`, `test_tools.py`, `test_wizard.py` and `test_make_docs.py` cover the command-line tools.
- `test_edges.py` holds what the others do not reach: every command starts, runs that meet broken input, and the
  invariants every preset must keep (size, determinism, clear stays clear).
- `test_integration_samples.py` builds a jar from `samples/free` and runs the whole pipeline (results in
  `build/integration/`).
- `synthetic.py` builds the test textures and the test mod jar (`conftest.py` shares them): extend those instead of
  adding binary files. Do not change what `make_textures()` produces; the golden file was recorded from it.

### Test coverage

CI runs the full sweep under coverage. It fails when the library's branch coverage drops below `fail_under` in
`pyproject.toml`, or when less than 90% of the lines a pull request adds or changes are executed by tests. New code
comes with tests; a branch that cannot be reached by a test gets a comment saying why, not a silent gap. To see what is
missing locally:

```bash
coverage run -m pytest -m "slow or not slow" && coverage report
```

## Commit hygiene

- Commit messages: short imperative subject; explain *why* in the body when it is not obvious.
- Do not commit generated files: `cache/`, `*.zip`, `*.log`, `*.done`, `*.partial` (already in `.gitignore`).
