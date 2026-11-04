"""Count real holes: pixels clear in every texture layered on one block model (base + cutouts), ours vs original.

usage: regen4x-hole-check <jar> <pack_zip> [--scale N]     (a good pack reports 0 models with new holes)
"""

import argparse
import io
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

TILE = 16  # side of a source texture (px)
MAX_PARENT_DEPTH = 8


def split_ref(ref: str) -> tuple[str, str]:
    """'ns:path' -> ('ns', 'path'); a bare path belongs to the minecraft namespace."""
    if ":" in ref:
        namespace, path = ref.split(":", 1)
        return namespace, path
    return "minecraft", ref


def texture_file(ref: str) -> str:
    namespace, path = split_ref(ref)
    return f"assets/{namespace}/textures/{path}.png"


def opaque_mask(zf: zipfile.ZipFile, name: str, size: int) -> NDArray[np.bool_]:
    """Which pixels of the first frame of texture ``name`` are not fully clear, scaled up to ``size`` x ``size``."""
    with Image.open(io.BytesIO(zf.read(name))) as f:
        a = np.asarray(f.convert("RGBA"))
    w = a.shape[1]
    opaque = a[:w, :, 3] > 0  # animation strips: only the first frame
    return np.kron(opaque, np.ones((size // w, size // w), bool))


def model_textures(zf: zipfile.ZipFile, names: set[str], name: str, depth: int = 0) -> dict[str, str]:
    """Textures of a block model, with the ones inherited from its parent chain."""
    model = json.loads(zf.read(name))
    textures: dict[str, str] = dict(model.get("textures", {}))
    parent = model.get("parent", "")
    if parent and depth < MAX_PARENT_DEPTH:
        namespace, path = split_ref(parent)
        parent_file = f"assets/{namespace}/models/{path}.json"
        if parent_file in names:
            textures = {**model_textures(zf, names, parent_file, depth + 1), **textures}
    return textures


def find_new_holes(jar: zipfile.ZipFile, pack: zipfile.ZipFile, scale: int = 4) -> list[tuple[int, str, list[str]]]:
    """(new hole pixels, model, textures) for every layered block model whose pack textures add see-through holes."""
    size = TILE * scale
    jar_names, pack_names = set(jar.namelist()), set(pack.namelist())
    found: list[tuple[int, str, list[str]]] = []
    for n in jar.namelist():
        if not ("/models/block/" in n and n.endswith(".json")):
            continue
        refs = [v for k, v in model_textures(jar, jar_names, n).items() if k != "particle" and not v.startswith("#")]
        layers = sorted({texture_file(r) for r in refs if texture_file(r) in jar_names})
        if len(layers) < 2:
            continue
        original = np.zeros((size, size), bool)
        ours = np.zeros((size, size), bool)
        layers = [x for x in layers if _size(jar, x) == (TILE, TILE)]
        if len(layers) < 2:
            continue
        for x in layers:
            original |= opaque_mask(jar, x, size)
            ours |= opaque_mask(pack, x, size) if x in pack_names else opaque_mask(jar, x, size)
        holes_original, holes_ours = int((~original).sum()), int((~ours).sum())
        if holes_ours > holes_original:
            found.append(
                (holes_ours - holes_original, n.split("models/")[1], [x.split("textures/")[1] for x in layers])
            )
    found.sort(reverse=True)
    return found


def _size(zf: zipfile.ZipFile, name: str) -> tuple[int, int]:
    with Image.open(io.BytesIO(zf.read(name))) as im:
        return im.size


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jar", type=Path)
    parser.add_argument("pack_zip", type=Path)
    parser.add_argument("--scale", type=int, default=4, help="the scale the pack was built with (default 4)")
    args = parser.parse_args(argv)
    with zipfile.ZipFile(args.jar) as jar, zipfile.ZipFile(args.pack_zip) as pack:
        found = find_new_holes(jar, pack, args.scale)
    print(len(found), "models with new holes")
    for row in found[:30]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
