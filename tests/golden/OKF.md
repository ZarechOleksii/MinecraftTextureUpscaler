---
okf: 1
path: tests/golden
purpose: Recorded expected output that the tests compare against.
---

# Golden data

Re-record only for a change that is meant to alter output, with `python -m tests.make_golden`
([make_golden.py](../make_golden.py)), then run `regen4x-docs`.

## Files

- [expected.json](expected.json): a fingerprint of the upscaler output per preset and option combination on the
  synthetic textures, plus the numpy / scipy / pillow versions it was made with.
  Related: [../test_golden.py](../test_golden.py), [../golden_cases.py](../golden_cases.py).
- [pack_expected.json](pack_expected.json): the entries (and their hashes) of the pack built from the synthetic mod jar.
  Related: [../test_tools.py](../test_tools.py), [../synthetic.py](../synthetic.py).
