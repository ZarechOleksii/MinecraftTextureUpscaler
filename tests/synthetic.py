import io
import json
import zipfile
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

type UInt8Array = NDArray[np.uint8]


def make_textures() -> dict[str, UInt8Array]:
    rng = np.random.default_rng(12345)
    texs = {}

    def blob_block(i: int, ncol: int, size: int = 16, alpha: bool = False) -> UInt8Array:
        pal = rng.integers(0, 256, (ncol, 3))
        # smooth-ish field: low-res random labels upsampled + noise
        low = rng.integers(0, ncol, (size // 4, size // 4))
        lab = np.kron(low, np.ones((4, 4), int))
        flip = rng.random((size, size)) < 0.12
        lab = np.where(flip, rng.integers(0, ncol, (size, size)), lab)
        rgb = pal[lab] + rng.integers(-6, 7, (size, size, 1))
        a = np.concatenate([np.clip(rgb, 0, 255), np.full((size, size, 1), 255)], -1).astype(np.uint8)
        if alpha:
            m = rng.random((size, size)) < 0.25
            a[m] = 0
        return a

    for i in range(10):
        texs[f"blob{i}"] = blob_block(i, 3 + i % 4)
    for i in range(4):
        texs[f"blobA{i}"] = blob_block(i, 3 + i, alpha=True)

    # diagonal lines on background (herringbone-like), solid
    for i in range(6):
        a = np.zeros((16, 16, 4), np.uint8)
        a[..., :3] = rng.integers(60, 200, 3)
        a[..., 3] = 255
        col = rng.integers(0, 256, 3)
        for d in range(16):
            for off in rng.choice([-8, -3, 0, 4, 7], size=2, replace=False):
                if i % 2:
                    a[d, (d + off) % 16, :3] = col
                else:
                    a[d, (15 - d + off) % 16, :3] = col
        # crossing for some
        if i % 3 == 0:
            for d in range(16):
                a[d, (15 - d) % 16, :3] = col
        texs[f"lines{i}"] = a

    # item silhouettes with staircase edges and semi-transparency
    for i in range(8):
        a = np.zeros((16, 16, 4), np.uint8)
        yy, xx = np.mgrid[0:16, 0:16]
        cy, cx = rng.integers(5, 11, 2)
        if i % 2:
            m = (np.abs(yy - cy) + np.abs(xx - cx)) < rng.integers(4, 8)
        else:
            m = ((yy - cy) ** 2 + (xx - cx) ** 2) < rng.integers(10, 40)
        m |= (np.abs((yy - xx) - rng.integers(-3, 3)) <= 0) & (yy > 2) & (yy < 14)
        col = rng.integers(40, 230, 3)
        a[m, :3] = col + rng.integers(-25, 26, (int(m.sum()), 3))
        a[m, 3] = 255
        edge = m & ~np.roll(m, 1, 0)
        a[edge, :3] = np.clip(col // 3, 0, 255)
        if i % 3 == 0:
            semi = m & (rng.random((16, 16)) < 0.15)
            a[semi, 3] = 128
        # 1px diagonal gap between two opaque areas (sai)
        if i == 5:
            for d in range(4, 12):
                a[d, d, 3] = 0
        texs[f"item{i}"] = np.clip(a, 0, 255).astype(np.uint8)

    # checker / dither
    for i in range(3):
        a = np.zeros((16, 16, 4), np.uint8)
        c1, c2 = rng.integers(0, 256, 3), rng.integers(0, 256, 3)
        chk = (np.indices((16, 16)).sum(0) % 2).astype(bool)
        a[..., :3] = np.where(chk[..., None], c1, c2)
        a[..., 3] = 255
        a[:6] = 255 - a[:6] * 0 if i == 0 else a[:6]
        a[8:, :8, :3] = rng.integers(0, 256, 3)
        texs[f"dither{i}"] = a

    # small high-contrast rects on flat bg (sharp shapes) incl. next to alpha
    for i in range(3):
        a = np.zeros((16, 16, 4), np.uint8)
        a[..., :3] = 90
        a[..., 3] = 255
        a[3:6, 4:9, :3] = 240
        a[9:11, 2:4, :3] = 10
        if i == 1:
            a[0:2, :, 3] = 0
        if i == 2:
            a[12:, 12:, :3] = rng.integers(0, 256, 3)
        texs[f"rect{i}"] = a

    # greys / pale / near-black
    g = np.zeros((16, 16, 4), np.uint8)
    g[..., 3] = 255
    g[:8, :, :3] = 200
    g[8:, :, :3] = 100
    g[::5, :, :3] = 20
    g[:, ::7, :3] = 240
    texs["greys"] = g
    # 32px textures
    texs["big32"] = blob_block(0, 5, size=32)
    texs["big32a"] = blob_block(1, 4, size=32, alpha=True)
    # flat
    f = np.zeros((16, 16, 4), np.uint8)
    f[...] = (120, 80, 40, 255)
    texs["flat"] = f
    # fully transparent + single pixel
    t = np.zeros((16, 16, 4), np.uint8)
    t[7, 7] = (255, 0, 0, 255)
    texs["dot"] = t
    return texs


def png_bytes(a: UInt8Array) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, "PNG")
    return buf.getvalue()


def build_mod_jar(path: Path) -> None:
    """A small mod jar with every kind of entry the pack builder handles (blocks, items, animations, CT sheet...)."""
    texs = make_textures()
    block, item = "assets/testmod/textures/block/", "assets/testmod/textures/item/"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["blob0", "blob3", "lines0", "lines1", "dither0", "rect1", "greys", "flat"]:
            z.writestr(f"{block}{name}.png", png_bytes(texs[name]))
        for name in ["item0", "item1", "item5", "blobA0", "dot"]:
            z.writestr(f"{item}{name}.png", png_bytes(texs[name]))
        z.writestr(f"{block}big32.png", png_bytes(texs["big32"]))  # 32px: skipped
        # animation strip with mcmeta
        strip = np.concatenate([texs["blob1"], texs["blob2"], texs["blob4"]], 0)
        z.writestr(f"{block}anim.png", png_bytes(strip))
        z.writestr(f"{block}anim.png.mcmeta", json.dumps({"animation": {"frametime": 2}}))
        # Conveyor-belt-like: still + scroll strip whose top is the still; a strip without a still; a pair; an orphan
        still = texs["blob5"]
        z.writestr(f"{block}belt.png", png_bytes(still))
        z.writestr(f"{block}belt_scroll.png", png_bytes(np.concatenate([still, texs["blob6"]], 0)))
        z.writestr(f"{block}gear_animated.png", png_bytes(np.concatenate([texs["blob7"], texs["blob8"]], 0)))
        z.writestr(f"{block}fan.png", png_bytes(texs["blob9"]))
        z.writestr(f"{block}fan_blades_scroll.png", png_bytes(np.concatenate([texs["lines2"], texs["lines3"]], 0)))
        z.writestr(f"{block}orphan_scroll.png", png_bytes(texs["lines4"]))
        # connected texture sheet (3x4 tiles) and one that is not a multiple of 16 (skipped)
        rng = np.random.default_rng(3)
        base = texs["blob2"].copy()
        sheet = np.zeros((48, 64, 4), np.uint8)
        for ty in range(3):
            for tx in range(4):
                t = base.copy()
                if (ty, tx) != (0, 0):
                    if tx % 2:
                        t[:, :2, :3] = rng.integers(0, 256, 3)
                    if ty % 2:
                        t[:2, :, :3] = rng.integers(0, 256, 3)
                    if tx == 3:
                        t[:, -2:, :3] = 20
                    if (ty, tx) == (2, 1):
                        t[...] = 0
                sheet[ty * 16 : (ty + 1) * 16, tx * 16 : (tx + 1) * 16] = t
        z.writestr(f"{block}wall.png", png_bytes(base))
        z.writestr(f"{block}wall_connected.png", png_bytes(sheet))
        z.writestr(f"{block}odd_connected.png", png_bytes(np.zeros((20, 16, 4), np.uint8)))
        # layered model (base + overlay with clear pixels) for hole_check
        z.writestr(f"{block}layer_base.png", png_bytes(texs["rect1"]))
        z.writestr(f"{block}layer_over.png", png_bytes(texs["blobA1"]))
        models = "assets/testmod/models/block/"
        z.writestr(f"{models}parent.json", json.dumps({"textures": {"base": "testmod:block/layer_base"}}))
        layered = {
            "parent": "testmod:block/parent",
            "textures": {"over": "testmod:block/layer_over", "particle": "testmod:block/flat", "x": "#base"},
        }
        z.writestr(f"{models}layered.json", json.dumps(layered))
        z.writestr("pack.mcmeta", "{}")
