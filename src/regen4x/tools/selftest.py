"""Determinism self-test: regen4x-selftest <jar>

Upscales the first 25 16x16 block textures of a mod jar and prints a combined hash. The hash must be the same on
every run (and on every machine with the same numpy / scipy / pillow versions).
"""

import argparse
import hashlib
import io
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from regen4x import presets
from regen4x.upscaler import regen4x

LIMIT = 25


def combined_hash(jar: Path, limit: int = LIMIT) -> tuple[int, str]:
    """(textures hashed, short hash of their upscaled pixels)."""
    digest = hashlib.sha1(usedforsecurity=False)
    count = 0
    with zipfile.ZipFile(jar) as z:
        todo = [
            n
            for n in sorted(z.namelist())
            if n.startswith("assets/") and n.endswith(".png") and "/textures/block/" in n
        ]
        for n in todo:
            with Image.open(io.BytesIO(z.read(n))) as f:
                im = f.convert("RGBA")
            if im.size != (16, 16):
                continue
            out = regen4x(im, presets.ship_for(im), seed=presets.seed_for(n.split("assets/", 1)[1]))
            digest.update(np.asarray(out).tobytes())
            count += 1
            if count == limit:
                break
    return count, digest.hexdigest()[:12]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jar", type=Path)
    args = parser.parse_args(argv)
    count, digest = combined_hash(args.jar)
    print(count, "block textures, combined hash", digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
