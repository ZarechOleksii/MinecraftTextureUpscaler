---
okf: 1
path: .github
purpose: GitHub automation: the CI workflow and its helper scripts.
---

# GitHub

## Files

- [dependabot.yml](dependabot.yml): weekly update pull requests for pip (numpy, scipy and pillow grouped, since they
  can change the golden output) and for the GitHub Actions used by CI.
- [PULL_REQUEST_TEMPLATE.md](PULL_REQUEST_TEMPLATE.md): the checklist shown in new pull requests.
  Related: [../CONTRIBUTING.md](../CONTRIBUTING.md).

## Subdirectories

- [ISSUE_TEMPLATE/](ISSUE_TEMPLATE/OKF.md): the issue forms.
- [workflows/](workflows/OKF.md): the CI workflow.
- [scripts/](scripts/OKF.md): helpers the workflow runs.
