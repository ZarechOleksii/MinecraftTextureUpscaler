---
okf: 1
path: .github/scripts
purpose: Small scripts the CI workflow runs; plain Python, not part of the installed package.
---

# CI scripts

## Files

- [junit_summary.py](junit_summary.py): turns the JUnit XML of the test run into the Markdown job summary.
- [okf_check.py](okf_check.py): the OKF documentation check (see [../../docs/open-knowledge-format.md](../../docs/open-knowledge-format.md) for the rules).
  Related: [../../tests/test_okf.py](../../tests/test_okf.py), [../workflows/ci.yml](../workflows/ci.yml).
