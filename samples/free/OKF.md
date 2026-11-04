---
okf: 1
path: samples/free
purpose: Redistributable 16px sample textures that the generated docs and the integration test use.
---

# Free samples

Twenty PNGs (not listed one by one) from Minetest Game, CC BY-SA 3.0. Only textures that may be redistributed belong
here.

## Files

- [samples.toml](samples.toml): the manifest: per texture its file, kind (block or item), what geometry it shows and
  its credit. Related: [../../src/regen4x/tools/make_docs.py](../../src/regen4x/tools/make_docs.py).
- [NOTICE.md](NOTICE.md): where the textures come from and their license terms.
- [LICENSE-minetest_game.txt](LICENSE-minetest_game.txt): the upstream license text.
  Related: [../../tests/test_integration_samples.py](../../tests/test_integration_samples.py),
  [../../docs/OKF.md](../../docs/OKF.md).
