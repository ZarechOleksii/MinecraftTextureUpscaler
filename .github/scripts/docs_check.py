import subprocess
import sys
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

from PIL import Image


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def same_pixels(committed: bytes, current: Path) -> bool:
    with Image.open(BytesIO(committed)) as a, Image.open(current) as b:
        return a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def stale_paths(root: Path, folder: str) -> list[str]:
    changed = [p for p in git(root, "diff", "--name-only", "-z", "HEAD", "--", folder).decode().split("\0") if p]
    added = [
        p for p in git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", folder).decode().split("\0") if p
    ]
    stale = list(added)
    for name in changed:
        path = root / name
        # PNG bytes depend on the zlib build (Windows and Linux differ); only the pixels are the product.
        if name.endswith(".png") and path.is_file() and same_pixels(git(root, "show", f"HEAD:{name}"), path):
            continue
        stale.append(name)
    return sorted(stale)


def main(argv: Sequence[str] | None = None) -> int:
    folder = (argv if argv is not None else sys.argv[1:] or ["docs"])[0]
    stale = stale_paths(Path.cwd(), folder)
    for name in stale:
        print(f"stale: {name}")
    if stale:
        print(f"::error::{folder} is out of date. Run regen4x-docs and commit the result.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
