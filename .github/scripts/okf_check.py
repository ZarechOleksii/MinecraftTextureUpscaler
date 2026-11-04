import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

OKF = "OKF.md"
REQUIRED_KEYS = ("okf", "path", "purpose")
EXEMPT_DIRS = ("docs/presets",)
UNLISTED_SUFFIXES = (".png",)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout
    return [name for name in out.split("\0") if name]


def changed_files(root: Path, base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [name for name in out.splitlines() if name]


def front_matter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return None


def link_targets(text: str) -> list[str]:
    targets = []
    for match in LINK.finditer(FENCE.sub("", text)):
        target = match.group(1).split("#")[0]
        if target and "://" not in target and not target.startswith("mailto:"):
            targets.append(target)
    return targets


def resolve(directory: str, target: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(directory, target).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def is_exempt(directory: str) -> bool:
    return any(directory == d or directory.startswith(d + "/") for d in EXEMPT_DIRS)


def parent_of(directory: str) -> str:
    return str(PurePosixPath(directory).parent) if "/" in directory else ""


def documented_dirs(files: Sequence[str]) -> set[str]:
    dirs = {parent_of(f) if "/" in f else "" for f in files}
    return {d for d in dirs if not is_exempt(d)}


def check(root: Path, files: Sequence[str]) -> list[str]:
    errors: list[str] = []
    dirs = documented_dirs(files)
    entries: dict[str, set[str]] = {}

    for directory in sorted(dirs):
        okf_rel = f"{directory}/{OKF}" if directory else OKF
        okf_path = root / okf_rel
        if not okf_path.is_file():
            errors.append(
                f"{okf_rel}: missing, every directory with files needs one (see docs/open-knowledge-format.md)"
            )
            continue
        text = okf_path.read_text(encoding="utf-8")
        fields = front_matter(text)
        if fields is None or any(not fields.get(key) for key in REQUIRED_KEYS):
            errors.append(f"{okf_rel}: front matter must define {', '.join(REQUIRED_KEYS)}")
        elif fields["path"] != (directory or "."):
            errors.append(f"{okf_rel}: front matter path is {fields['path']!r}, expected {directory or '.'!r}")
        resolved = set()
        for target in link_targets(text):
            full = resolve(directory, target)
            if not (root / full).exists():
                errors.append(f"{okf_rel}: link to {target} points at nothing")
            resolved.add(full)
        entries[directory] = resolved

    for name in files:
        directory = parent_of(name) if "/" in name else ""
        if directory not in entries or name.endswith(UNLISTED_SUFFIXES) or name.rsplit("/", 1)[-1] == OKF:
            continue
        if name not in entries[directory]:
            errors.append(f"{directory + '/' if directory else ''}{OKF}: no entry for {name.rsplit('/', 1)[-1]}")

    for directory in sorted(dirs - {""}):
        owner = parent_of(directory)
        while owner not in dirs and owner:
            owner = parent_of(owner)
        if owner in entries and f"{directory}/{OKF}" not in entries[owner]:
            errors.append(f"{owner + '/' if owner else ''}{OKF}: no link to {directory}/{OKF}")
    return errors


def stale_warnings(files: Sequence[str], changed: Sequence[str]) -> list[str]:
    dirs = documented_dirs(files)
    touched = set(changed)
    warnings = []
    for name in changed:
        directory = parent_of(name) if "/" in name else ""
        okf = f"{directory}/{OKF}" if directory else OKF
        if directory in dirs and okf not in touched and name != okf and not name.endswith(UNLISTED_SUFFIXES):
            warnings.append(f"::warning file={name}::{name} changed but {okf} did not: check its entry is still true")
    return warnings


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    base = args[args.index("--base") + 1] if "--base" in args else None
    root = Path(__file__).resolve().parents[2]
    files = tracked_files(root)
    errors = check(root, files)
    for error in errors:
        print(f"::error::{error}")
    if base:
        for warning in stale_warnings(files, changed_files(root, base)):
            print(warning)
    if errors:
        print(f"{len(errors)} OKF problem(s). Rules: docs/open-knowledge-format.md")
        return 1
    print("OKF documentation is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
