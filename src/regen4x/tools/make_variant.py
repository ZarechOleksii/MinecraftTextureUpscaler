import argparse
import io
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from regen4x import presets
from regen4x.tools.run_pack import PACK_FORMAT
from regen4x.upscaler import regen4x

MODES = ("identity16", "items64", "blocks64")


def make_variant(jar: Path, out_zip: Path, mode: str) -> int:
    """Write the diagnostic pack for ``jar``. Returns the number of textures in it."""
    count = 0
    with zipfile.ZipFile(jar) as z, zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr(
            "pack.mcmeta", json.dumps({"pack": {"pack_format": PACK_FORMAT, "description": f"diagnostic {mode}"}})
        )
        for n in sorted(z.namelist()):
            if not (
                n.startswith("assets/") and n.endswith(".png") and ("/textures/block/" in n or "/textures/item/" in n)
            ):
                continue
            if mode == "items64" and "/textures/item/" not in n:
                continue
            if mode == "blocks64" and "/textures/block/" not in n:
                continue
            data = z.read(n)
            with Image.open(io.BytesIO(data)) as f:
                im = f.convert("RGBA")
            if im.size != (16, 16):
                continue
            if mode == "identity16":
                out.writestr(n, data)
            else:
                upscaled = regen4x(im, presets.ship_for(im), seed=presets.seed_for(n.split("assets/", 1)[1]))
                buf = io.BytesIO()
                upscaled.save(buf, "PNG")
                out.writestr(n, buf.getvalue())
            count += 1
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a diagnostic resource pack from one mod jar.")
    parser.add_argument("mods_dir", type=Path)
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("jar_prefix", help="the first jar whose file name starts with this is used")
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args(argv)
    jar = next((j for j in sorted(args.mods_dir.glob("*.jar")) if j.name.startswith(args.jar_prefix)), None)
    if jar is None:
        parser.error(f"no jar starting with {args.jar_prefix!r} in {args.mods_dir}")
    count = make_variant(jar, args.out_zip, args.mode)
    print(args.out_zip, args.mode, count, "textures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
