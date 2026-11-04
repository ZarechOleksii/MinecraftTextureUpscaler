---
okf: 1
path: .github/workflows
purpose: The CI workflow that every pull request must pass.
---

# Workflows

## Files

- [ci.yml](ci.yml): on pull requests and pushes to master, four jobs: `lint` (ruff format, ruff check, mypy), `tests`
  (full golden sweep under coverage, plus diff-cover on changed lines), `docs` (regenerates `docs/presets` and fails on
  any difference; images are compared by pixels) and `okf` (the documentation check). Keep the list of checks in
  [.claude/CLAUDE.md](../../.claude/CLAUDE.md) in step.
  Related: [../scripts/okf_check.py](../scripts/okf_check.py), [../scripts/junit_summary.py](../scripts/junit_summary.py).
