# regen4x

Edge-aware 16px → 64px upscaler for modded Minecraft block and item textures, plus tools to build and check resource
packs.

Requires Python 3.12+. Install it (this also puts the `regen4x-*` commands on your path):

```
pip install .            # or: pip install -e .   while developing
```

## Not sure about the options? `regen4x-wizard`
```
regen4x-wizard
```
Asks for the input, the size (2-8x), the profile, the output and, for an existing zip, whether to update or replace it,
with a default for every question. It then prints the one `regen4x-upscale` command that does it and runs it, so you
can repeat the same run later without the questions. `--dry-run` only prints the command; `--presets FILE` adds your
own presets to the choices.

## Upscale anything: `regen4x-upscale`
```
regen4x-upscale INPUT -o OUTPUT [--update | --force] [--scale N] [--profile NAME] [--blocks P] [--items P] [--use GLOB=P]
```
| INPUT | meaning |
|---|---|
| `x.png` | one texture |
| folder of PNGs | loose textures (sub-folders kept) |
| folder with `assets/` | an extracted mod or pack |
| `x.jar` / `x.zip` | a mod, or a resource pack |
| folder of jars | every mod in it (`--only PREFIX` narrows it) |

| OUTPUT | meaning |
|---|---|
| a folder | the upscaled PNGs (+ `.mcmeta`); same-named files are replaced |
| new `x.zip` | a resource pack; an existing zip is refused unless `--force` |
| `x.zip --update` | keeps the pack's other entries and its `pack.mcmeta`, adds or replaces the upscaled ones |

- `--scale N` (2-8, default 4) sets the output size, so 16px becomes 16*N px. Every preset was tuned at 4.
- `--profile` / `--blocks` / `--items` / `--use GLOB=PRESET` choose the preset per texture (see below); `--list` shows
  what exists, `--describe PRESET` shows what a preset sets and which parent it comes from.
- Loose PNGs have no mod path: add `--kind block|item --namespace <mod>` and they get the seed and the rules of the same
  texture inside that mod's jar (identical pixels).
- `--budget`, `--cache-dir` and the `.log` / `.done` files work as for `regen4x-run-pack` below.

### Presets and profiles are data
`src/regen4x/presets.toml` holds every preset and profile; add your own in a file of your own with `--presets my.toml`,
no code change needed. A preset builds on another one and can also undo things:
```toml
[preset.MY_BLOCK]
extends = "solid-v1.6"            # start from this preset
reset   = ["line_thru"]           # put an option back to its default
smooth  = 2.6                     # change an option

[profile.mine]                    # first matching rule wins; the last one must have no condition
rules = [
    { path = "*/textures/block/*", transparent = true, preset = "cutout-v2.1", keep_opaque = true },
    { path = "*/textures/item/*", preset = "cutout-v2.1" },
    { preset = "MY_BLOCK" },
]
```
Built-in presets are named `family-vMAJOR.MINOR` (`solid-v1.6`, `cutout-v2.1`) and never edited once published; a
profile is a numbered release (`standard-r1`) and `standard` always points at the newest. `--blocks solid` and
`--items cutout` mean "whatever the profile uses". How the names and numbers work, and when each one changes, is in
[docs/versioning.md](docs/versioning.md).

Unknown options, wrong types, unknown parents and cycles are refused with a message. Presets can only recombine
existing `RegenParams` options; a new behaviour still needs a new option in `params.py`.

### Preset documentation
`docs/presets/` has a page for every preset (what it changes against its parent, all its settings, before / after
screenshots) and comparison sheets; see [docs/presets/README.md](docs/presets/README.md). It is generated, not written:
```
regen4x-docs        # rebuilds docs/presets from samples/free
```
- `samples/free/` holds textures that may be redistributed: 20 textures from Minetest Game (CC BY-SA 3.0), with their
  credit in `samples.toml` and `NOTICE.md`. Its docs are committed; the images in them are adaptations and share that
  license.
- For textures of your own, use `regen4x-docs --samples DIR --out DIR`; `DIR` holds a `samples.toml` in the same
  format (see `regen4x-docs --help`). Do not commit textures you may not redistribute.
- After editing `presets.toml` or a sample list, run `regen4x-docs` and commit `docs/presets`: a test fails if the
  committed pages are out of date.

## Build a pack from a mods folder
```
regen4x-run-pack <instance>/mods <instance>/resourcepacks/MyPack_64x.zip mymod- othermod ...   # same code as regen4x-upscale
regen4x-hole-check <instance>/mods/<mod>.jar <instance>/resourcepacks/MyPack_64x.zip   # must print 0
regen4x-ct-check <instance>/resourcepacks/MyPack_64x.zip <instance>/mods mymod- othermod ...  # 0 flagged
```
(`python -m regen4x.tools.run_pack ...` works too, for every tool.)

`regen4x-run-pack` reads `assets/*/textures/block|item/**.png` from every jar whose file name starts with one of the
prefixes. It upscales:
- 16×16 textures
- 16-wide animation strips, frame by frame
- the scrolling or animated versions that pair with a still texture (conveyor belts and the like), always at the same
  scale as their still texture
- `<X>_connected.png` connected-texture sheets of an upscaled `X`, tile by tile with neighbouring context
  (`regen4x.ct`)

It writes `pack.mcmeta` (pack_format 34), copies `.mcmeta` files, and updates the zip in place. Progress goes to
`<zip>.log`; a summary goes to `<zip>.done`.

### Long builds in short runs
- `--budget SECONDS` stops cleanly before that time and writes `INCOMPLETE` to `.done`. Run the same command again
  to continue. Finished textures are cached, and the pack is only written once everything is done.
- The cache lives in `<cache dir>/<code hash>/`. The cache dir is `--cache-dir DIR`, else `$REGEN_CACHE`, else `./cache`.
  Use a fast local folder when the output is on a slow network share. Any change to the upscaler's source (the modules
  directly in `src/regen4x/`, not the tools) starts a fresh cache.

## Layout
Every directory has an `OKF.md` that says what each file in it contains and does and links to the related files; start
at [OKF.md](OKF.md). The format is described in [docs/open-knowledge-format.md](docs/open-knowledge-format.md).

| Command | Purpose |
|---|---|
| `regen4x-upscale` | any input (png, folder, mod, jar, pack) to any output (folder, new zip, updated zip) |
| `regen4x-wizard` | asks the questions, prints and runs the `regen4x-upscale` command |
| `regen4x-docs` | builds the preset documentation (pages and before / after sheets) from sample textures |
| `regen4x-run-pack` | builds a resource pack from a folder of mod jars |
| `regen4x-ct-check` | seam check of every connected sheet in a pack (3×3 wall, original vs 64px); `--sheet out.png a,b,c` renders a comparison |
| `regen4x-hole-check` | checks layered block models for see-through holes |
| `regen4x-check-links` | checks that diagonal 1px links stay connected |
| `regen4x-make-variant` | diagnostic packs (original textures / items only / blocks only) |
| `regen4x-upscale-folder` | upscale a folder of 16px PNGs (older, `regen4x-upscale` does this and more) |
| `regen4x-selftest` | determinism self-test: `regen4x-selftest <jar>` |

Output is deterministic: the seed comes from each texture's path.

## Using the upscaler from Python
```python
from dataclasses import replace
from PIL import Image
from regen4x import presets, regen4x

im = Image.open("stone.png").convert("RGBA")
out = regen4x(im, presets.ship_for(im), seed=presets.seed_for("minecraft/textures/block/stone.png"))
custom = replace(presets.SOLID_V1_6, smooth=2.6)  # presets are frozen; derive new ones with replace()
```

## Development
```
pip install -e . ruff mypy pytest coverage diff-cover
ruff format . && ruff check .      # format + lint
mypy                               # types (src and tests)
pytest                             # about a minute
pytest -m "slow or not slow"       # the full golden sweep, about two minutes
python .github/scripts/okf_check.py   # every file is documented in its directory's OKF.md
```
The code targets Python 3.12+ and is fully type-annotated. CI (`.github/workflows/ci.yml`) runs the same checks on every
pull request. It also fails when the docs under `docs/presets` are out of date, when a file is missing from its directory's `OKF.md`, or when the lines a pull request changes
are not covered by tests; the run's summary page shows the test results and the coverage, and the HTML report is attached.

### Making a change
Branch, change, run the checks above, open a pull request. Fix bugs test-first. What else to do depends on the change:

| You want to... | Do this |
|---|---|
| change how textures are upscaled | edit the modules in `src/regen4x/`. The output is pinned by `tests/golden/expected.json`: a refactor must leave it untouched. A change that is *meant* to alter the output re-records it with `python -m tests.make_golden`, then `regen4x-docs`, and says so in the commit message |
| add a tunable | add a field to `RegenParams` (default = today's behaviour), a case using it in `configs()` in `tests/golden_cases.py`, re-record the golden file |
| add or change a preset or profile | edit `src/regen4x/presets.toml` (every preset needs a `description`, `status` and `changelog`; a change that alters output is a new version, see [docs/versioning.md](docs/versioning.md)), re-record the golden file for a new or changed preset, run `regen4x-docs`, commit `docs/presets` |
| add a sample texture | only if it may be redistributed: PNG in `samples/free/`, an entry with its credit in `samples.toml` and `NOTICE.md`, run `regen4x-docs`, commit `docs/presets` |
| add a command | module in `src/regen4x/tools/` with `main(argv) -> int`, an entry in `[project.scripts]`, a row in the table above, tests |
| change CI | edit `.github/workflows/ci.yml` |
| add, remove, rename or change what a file does | update the entry in that directory's `OKF.md` (a new directory needs its own `OKF.md`, linked from its parent); `python .github/scripts/okf_check.py` checks it, and CI fails otherwise |

`tests/test_integration_samples.py` packs the textures of `samples/free` into a mod jar, builds it through the command
line and keeps the pack, a per-texture report and a before/after preview in `build/integration/` (set `REGEN_TEST_JAR`
to use a real mod jar instead, `REGEN_TEST_OUT` to keep the results elsewhere).

The golden file also records the numpy / scipy / pillow versions it was made with; a failure that only appears after
upgrading them is an environment difference to look into. Any edit to the upscaler's source rebuilds the pack cache once.
For the full list of conventions (types, lint rules, line endings, which test goes where) see
[.claude/CLAUDE.md](.claude/CLAUDE.md).

## License

The code is released under the [Apache License 2.0](LICENSE); commercial use is allowed. Redistributions must keep the
[NOTICE](NOTICE) file. If you use regen4x or publish packs made with it, please credit it with a link to
<https://github.com/ZarechOleksii/MinecraftTextureUpscaler>. A new pack zip gets that credit in the `description` of its
`pack.mcmeta` (an existing pack's `pack.mcmeta` is left as it is); please leave it there. The sample textures in `samples/free/` and the images generated
from them in `docs/presets/img/` are CC BY-SA 3.0 (see [samples/free/NOTICE.md](samples/free/NOTICE.md)).

The tool upscales textures you supply. Upscaled textures are adaptations of the originals, so only redistribute a
resource pack built from a mod if that mod's license allows it.
