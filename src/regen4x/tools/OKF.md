---
okf: 1
path: src/regen4x/tools
purpose: The command-line tools (one module per command) and the shared texture sources and sinks they use.
---

# Command-line tools

Each module exposes `main(argv) -> int`, uses `argparse` and is registered under `[project.scripts]` in
[pyproject.toml](../../../pyproject.toml); the module docstring doubles as the command's `--help` text. Usage is in
the command table of the [README](../../../README.md). Tools import the [library](../OKF.md); the library never imports
them. Tests: [tests/test_tools.py](../../../tests/test_tools.py), [tests/test_edges.py](../../../tests/test_edges.py).

## Files

- [\_\_init\_\_.py](__init__.py): marks the package.
- [\_io.py](_io.py): where textures come from and go to. Sources (`ZipSource` for jars and packs, `DirSource` for
  folders, extracted mods or one PNG) address everything by jar-style keys; sinks (`FolderSink`, `ZipSink`, which can
  merge into an existing zip) write the result only when the `with` block ends without error.
- [upscale.py](upscale.py): `regen4x-upscale`, the general command: any input to any output, with `--profile`,
  `--blocks`, `--items`, `--use` rules in front of the profile. Related: [run_pack.py](run_pack.py).
- [run_pack.py](run_pack.py): `regen4x-run-pack` and the engine `regen4x-upscale` also uses: `PackBuilder` upscales
  stills, animation strips, scroll targets and connected sheets in worker processes, with a time `Budget`, an
  on-disk `Cache` keyed by `code_hash()` of the library source (any edit to the library starts a fresh cache), and
  `.log` / `.done` progress files; it writes `pack.mcmeta` (pack_format 34, with a credit line linking to the repository) and copies `.mcmeta` files unchanged.
  Related: [../ct.py](../ct.py), [../presets.py](../presets.py).
- [wizard.py](wizard.py): `regen4x-wizard`, asks the questions and prints and runs the matching
  `regen4x-upscale` command. Related: [upscale.py](upscale.py).
- [make_docs.py](make_docs.py): `regen4x-docs`, renders the generated preset pages, sheets and images from
  `samples.toml`, removing what an earlier run wrote.
  Related: [../../../docs/OKF.md](../../../docs/OKF.md), [../../../samples/free/OKF.md](../../../samples/free/OKF.md).
- [make_variant.py](make_variant.py): `regen4x-make-variant`, diagnostic packs (modes `identity16`: original textures,
  `items64`: only items upscaled, `blocks64`: only blocks upscaled).
- [upscale_folder.py](upscale_folder.py): `regen4x-upscale-folder`, the older folder-to-folder batch command: keeps the folder
  structure, skips non-16x16 images, seeds from the path relative to the source folder.
- [hole_check.py](hole_check.py): `regen4x-hole-check`, counts pixels clear in every layer of a block model, ours
  against the original.
- [ct_check.py](ct_check.py): `regen4x-ct-check`, measures seam steps on a 3x3 wall of each connected sheet and flags
  worse ones. Related: [../ct.py](../ct.py).
- [check_links.py](check_links.py): `regen4x-check-links`, checks that 1px diagonal links stay connected in the
  output. Related: [../lines.py](../lines.py).
- [selftest.py](selftest.py): `regen4x-selftest`, hashes the output for 25 textures of a jar to confirm determinism.
