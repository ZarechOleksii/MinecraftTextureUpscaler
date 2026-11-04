import argparse
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from regen4x import presets
from regen4x.upscaler import regen4x

SHIP = "SHIP"  # per texture: cut-outs -> SHIP_CUTOUT, solid blocks -> SHIP_BLOCK


def upscale_folder(src: Path, dst: Path, preset: str = SHIP) -> tuple[int, int]:
    """Upscale all 16x16 pngs below ``src`` into ``dst``. Returns (upscaled, skipped)."""
    done = skipped = 0
    for path in sorted(src.rglob("*.png")):
        rel = path.relative_to(src).as_posix()
        with Image.open(path) as f:
            im = f.convert("RGBA")
        if im.size != (16, 16):
            skipped += 1
            continue
        params = presets.ship_for(im) if preset == SHIP else presets.PRESETS[preset]
        out = regen4x(im, params, seed=presets.seed_for(rel))
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
        done += 1
    return done, skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upscale a folder of 16px PNGs to 64px.")
    parser.add_argument("src", type=Path, help="folder with the 16x16 PNGs")
    parser.add_argument("dst", type=Path, help="output folder")
    parser.add_argument("preset", nargs="?", default=SHIP, choices=[SHIP, *presets.PRESETS], help="default: SHIP")
    args = parser.parse_args(argv)
    done, skipped = upscale_folder(args.src, args.dst, args.preset)
    print(f"upscaled {done}, skipped {skipped} (not 16x16)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
