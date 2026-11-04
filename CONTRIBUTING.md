# Contributing to regen4x

Thanks for helping. Bug reports, ideas and pull requests are welcome.

## Reporting a bug or asking for a feature

Open an issue and pick the matching template. For a bug, include the command you ran, the Python and package versions
(`python -m pip list`), and, if a texture looks wrong, the 16px original (only if you may share it).

Security problems go through [SECURITY.md](SECURITY.md), not a public issue.

## Making a change

1. Fork the repository and work on a branch.
2. Make one change per pull request. Fix a bug test-first: write the test that fails, then the fix.
3. Run the checks from the repository root and fix everything they report:

   ```bash
   pip install -e . ruff mypy pytest
   ruff format .
   ruff check .
   mypy
   pytest
   python .github/scripts/okf_check.py
   ```

4. Open a pull request. CI runs the same checks plus the full golden sweep and a check that the generated preset
   documentation is current; a pull request merges when it is green.

The full rules (code standards, which test goes where, how to add a preset, a tunable or a command, what must never
change a pixel of the output, line endings) are in [.claude/CLAUDE.md](.claude/CLAUDE.md). The documentation lives in
`OKF.md` files, one per directory, starting at [OKF.md](OKF.md); a change that adds, removes or changes the role of a
file updates its directory's `OKF.md` in the same pull request.

## Textures and licenses

Only add textures that may be redistributed (see [samples/free/NOTICE.md](samples/free/NOTICE.md)). Do not commit
textures from mods or games you do not have the right to share.

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE), like the rest
of the code.

Please follow the [code of conduct](CODE_OF_CONDUCT.md).
