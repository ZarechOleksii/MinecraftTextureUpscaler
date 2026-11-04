---
okf: 1
path: .
purpose: Entry point to the repository documentation: what regen4x is and where each part is described.
---

# regen4x

An edge-aware upscaler that turns 16px modded Minecraft textures into crisp higher-resolution ones, plus tools to build and check resource packs.
Every directory has an `OKF.md` like this one (format and rules: [docs/open-knowledge-format.md](docs/open-knowledge-format.md)); read the one for the
directory you are working in, and update it when a file's contents or role change.

## Where to look

- [src/regen4x/](src/regen4x/OKF.md): the library. [src/regen4x/tools/](src/regen4x/tools/OKF.md): the commands.
- [tests/](tests/OKF.md): the test suite and golden data.
- [docs/](docs/OKF.md): versioning rules, the OKF spec, generated preset docs.
- [samples/free/](samples/free/OKF.md): redistributable sample textures.
- [.github/](.github/OKF.md): CI. [.claude/](.claude/OKF.md): assistant instructions.

## Files

- [README.md](README.md): the user-facing documentation: usage of every command, presets and profiles, development.
- [OKF.md](OKF.md): this file.
- [pyproject.toml](pyproject.toml): package metadata, the `regen4x-*` entry points, and the ruff, mypy, pytest and
  coverage settings (the source of truth for code standards).
- [requirements.txt](requirements.txt): runtime dependencies (numpy, scipy, pillow), read by `pyproject.toml`.
- [LICENSE](LICENSE): Apache License 2.0 of the code.
- [NOTICE](NOTICE): copyright and the credit request (link to the repository) that redistributions must keep.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to report a bug and make a change; points at the full rules in
  [.claude/CLAUDE.md](.claude/CLAUDE.md).
- [SECURITY.md](SECURITY.md): how to report a vulnerability privately and what is in scope.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): expected behaviour and how it is enforced.
- [.editorconfig](.editorconfig), [.gitattributes](.gitattributes): CRLF line endings in the working tree, LF in git.
- [.gitignore](.gitignore): caches, packs, logs and other generated files that must not be committed.
