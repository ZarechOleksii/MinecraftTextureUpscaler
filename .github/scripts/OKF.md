---
okf: 1
path: .github/scripts
purpose: Small scripts the CI workflow runs; plain Python, not part of the installed package.
---

# CI scripts

## Files

- [docs_check.py](docs_check.py): run after `regen4x-docs` in CI; fails when a file under `docs/` differs from the
  commit or is new. PNGs are compared by pixels because their bytes depend on the zlib build of the platform.
  Related: [../../src/regen4x/tools/make_docs.py](../../src/regen4x/tools/make_docs.py).
- [junit_summary.py](junit_summary.py): turns the JUnit XML of the test run into the Markdown job summary.
- [okf_check.py](okf_check.py): the OKF documentation check (see [../../docs/open-knowledge-format.md](../../docs/open-knowledge-format.md) for the rules).
  Related: [../../tests/test_okf.py](../../tests/test_okf.py), [../workflows/ci.yml](../workflows/ci.yml).
