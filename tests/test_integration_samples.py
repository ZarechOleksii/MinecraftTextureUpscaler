import io
import os
import shutil
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from regen4x import presets, regen4x
from regen4x.tools import ct_check, hole_check, upscale

ROOT = Path(__file__).parents[1]
SAMPLES = ROOT / "samples" / "free"
OUT = Path(os.environ.get("REGEN_TEST_OUT", ROOT / "build" / "integration"))
FOLDERS = ("/textures/block/", "/textures/item/")


def build_samples_jar(path: Path) -> None:
    """A mod jar (namespace ``freesamples``) holding every texture of ``samples/free`` under block/ or item/."""
    manifest = tomllib.loads((SAMPLES / "samples.toml").read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for sample in manifest["sample"]:
            name = sample["file"]
            z.write(SAMPLES / name, f"assets/freesamples/textures/{sample['kind']}/{name}")


def _jar() -> Path:
    given = os.environ.get("REGEN_TEST_JAR")
    if given:
        return Path(given)
    jar = OUT / "freesamples-1.0.jar"
    build_samples_jar(jar)
    return jar


JAR = _jar()
NAME = JAR.stem.split("-")[0]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not JAR.is_file(), reason=f"mod jar not found: {JAR} (REGEN_TEST_JAR)"),
]


def rgba(data: bytes) -> NDArray[np.uint8]:
    with Image.open(io.BytesIO(data)) as im:
        a: NDArray[np.uint8] = np.asarray(im.convert("RGBA")).copy()
    return a


def expected_names(jar: zipfile.ZipFile) -> set[str]:
    """The textures the pack must hold: 16px squares, and 16-wide strips that have an .mcmeta."""
    names = set(jar.namelist())
    found = set()
    for n in names:
        if not (n.startswith("assets/") and n.endswith(".png") and any(f in n for f in FOLDERS)):
            continue
        w, h = Image.open(io.BytesIO(jar.read(n))).size
        stem = PurePosixPath(n).stem
        if (w, h) == (16, 16) or (
            w == 16 and h % 16 == 0 and (n + ".mcmeta" in names or stem.endswith(("_scroll", "_animated")))
        ):
            found.add(n)
    return found


def distance_from_original(original: NDArray[np.uint8], upscaled: NDArray[np.uint8]) -> tuple[float, float]:
    """(mean colour change of the pixels that are opaque in both, share of pixels whose see-through-ness changed)."""
    k = upscaled.shape[0] // original.shape[0]
    big = np.kron(original, np.ones((k, k, 1), np.uint8))
    both = (big[..., 3] > 0) & (upscaled[..., 3] > 0)
    colour = float(np.abs(big[..., :3].astype(int) - upscaled[..., :3].astype(int))[both].mean()) if both.any() else 0.0
    shape = float(((big[..., 3] > 0) != (upscaled[..., 3] > 0)).mean())
    return colour, shape


def write_report(jar: zipfile.ZipFile, pack: zipfile.ZipFile, path: Path) -> dict[str, tuple[float, float]]:
    lines = [f"{JAR.name} -> {pack.filename}", ""]
    distances: dict[str, tuple[float, float]] = {}
    upscaled = set(pack.namelist())
    for n in sorted(jar.namelist()):
        if not n.endswith(".png"):
            continue
        w, h = Image.open(io.BytesIO(jar.read(n))).size
        if n in upscaled:
            pw, ph = Image.open(io.BytesIO(pack.read(n))).size
            distances[n] = distance_from_original(rgba(jar.read(n)), rgba(pack.read(n)))
            lines.append(
                f"upscaled  {n}  {w}x{h} -> {pw}x{ph}  colour change {distances[n][0]:.1f}/255, "
                f"see-through changed on {distances[n][1]:.1%} of pixels"
            )
        else:
            in_scope = any(f in n for f in FOLDERS)
            lines.append(f"left as is  {n}  {w}x{h}  ({'size not handled' if in_scope else 'outside block / item'})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return distances


def write_preview(jar: zipfile.ZipFile, pack: zipfile.ZipFile, path: Path) -> None:
    names = [n for n in sorted(pack.namelist()) if n.endswith(".png")]
    cell = 128
    grey = (70, 70, 70, 255)
    sheet = Image.new("RGBA", (2 * cell + 30, len(names) * (cell + 10) + 10), grey)
    for row, n in enumerate(names):
        for col, data in enumerate((jar.read(n), pack.read(n))):
            tile = Image.open(io.BytesIO(data)).convert("RGBA")
            tile = tile.crop((0, 0, tile.width, tile.width))  # animation strips: first frame
            tile = tile.resize((cell, cell), Image.Resampling.NEAREST)
            bg = Image.new("RGBA", (cell, cell), grey)
            bg.alpha_composite(tile)
            sheet.paste(bg, (10 + col * (cell + 10), 10 + row * (cell + 10)))
    sheet.save(path)


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The whole jar through ``regen4x-upscale``, into a zip that is kept in OUT."""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{NAME}_64x.zip"
    cache = tmp_path_factory.mktemp("cache")
    assert upscale.main([str(JAR), "-o", str(out), "--force", "--cache-dir", str(cache)]) == 0
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(out) as built:
        write_report(jar, built, OUT / f"{NAME}_report.txt")
        write_preview(jar, built, OUT / f"{NAME}_preview.png")
    return out


def test_the_pack_holds_exactly_the_handled_textures_at_four_times_the_size(pack: Path) -> None:
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(pack) as built:
        want = expected_names(jar)
        assert want, "the jar has no 16px block / item textures"
        assert {n for n in built.namelist() if n.endswith(".png")} == want
        for n in want:
            w, h = Image.open(io.BytesIO(jar.read(n))).size
            assert Image.open(io.BytesIO(built.read(n))).size == (4 * w, 4 * h), n
        for n in jar.namelist():
            if n.endswith(".png.mcmeta") and n[: -len(".mcmeta")] in want:
                assert built.read(n) == jar.read(n), n
        assert built.testzip() is None
        assert "pack.mcmeta" in built.namelist()


def test_the_run_reports_no_failures(pack: Path) -> None:
    done = Path(str(pack) + ".done").read_text(encoding="utf-8")
    assert done.startswith("FINISHED upscaled ")
    assert "failed 0" in done


def test_every_texture_stays_close_to_its_original(pack: Path) -> None:
    """Not a pixel pin (the golden tests do that): catches garbage, such as a wrong preset or a broken post-step."""
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(pack) as built:
        distances = write_report(jar, built, OUT / f"{NAME}_report.txt")
    assert distances
    for n, (colour, shape) in distances.items():
        assert colour < 40, f"{n}: colour moved {colour:.1f}/255 from the original"
        assert shape < 0.12, f"{n}: see-through changed on {shape:.1%} of its pixels"


def test_no_new_holes_in_layered_blocks_and_connected_sheets_hold(pack: Path) -> None:
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(pack) as built:
        assert hole_check.find_new_holes(jar, built) == []
        checked, bad, _ = ct_check.check_pack(built, JAR.parent, [JAR.name])
    assert bad == []
    assert checked >= 0


def test_one_png_gives_the_same_texture_as_in_the_whole_run(pack: Path, tmp_path: Path) -> None:
    """The same texture as a loose file, into a folder, a new zip, and added to a copy of the full pack."""
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(pack) as built:
        singles = sorted(n for n in expected_names(jar) if Image.open(io.BytesIO(jar.read(n))).size == (16, 16))
        assert singles
        key = singles[0]
        namespace, kind = key.split("/")[1], key.split("/")[3]
        in_full_run = rgba(built.read(key))
        png = tmp_path / "in" / PurePosixPath(key).name
        png.parent.mkdir()
        png.write_bytes(jar.read(key))
    flags = ["--kind", kind, "--namespace", namespace, "--cache-dir", str(tmp_path / "cache")]

    folder = tmp_path / "folder"
    assert upscale.main([str(png), "-o", str(folder), *flags]) == 0
    assert np.array_equal(rgba((folder / key).read_bytes()), in_full_run)

    new_zip = tmp_path / "single.zip"
    assert upscale.main([str(png), "-o", str(new_zip), *flags]) == 0
    with zipfile.ZipFile(new_zip) as z:
        assert sorted(z.namelist()) == sorted(["pack.mcmeta", key])
        assert np.array_equal(rgba(z.read(key)), in_full_run)

    updated = tmp_path / "updated.zip"
    shutil.copyfile(pack, updated)
    with zipfile.ZipFile(updated) as z:
        before = sorted(z.namelist())
    assert upscale.main([str(png), "-o", str(updated), "--update", *flags]) == 0
    with zipfile.ZipFile(updated) as z:
        assert sorted(z.namelist()) == before
        assert np.array_equal(rgba(z.read(key)), in_full_run)


def test_a_texture_matches_the_library_called_directly(pack: Path) -> None:
    with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(pack) as built:
        key = sorted(n for n in expected_names(jar) if Image.open(io.BytesIO(jar.read(n))).size == (16, 16))[0]
        src = Image.open(io.BytesIO(jar.read(key))).convert("RGBA")
        rel = key.split("assets/", 1)[1]
        choice = presets.STANDARD_PROFILE.choose(rel, src)
        direct = presets.finish_choice(choice, src, regen4x(src, choice.params, seed=presets.seed_for(rel), scale=4))
        assert np.array_equal(rgba(built.read(key)), np.asarray(direct))


def test_other_scales_build_from_the_same_jar(tmp_path: Path) -> None:
    with zipfile.ZipFile(JAR) as jar:
        want = expected_names(jar)
        sizes = {n: Image.open(io.BytesIO(jar.read(n))).size for n in want}
    for scale in (2, 8):
        out = tmp_path / f"x{scale}.zip"
        assert upscale.main([str(JAR), "-o", str(out), "--scale", str(scale), "--cache-dir", str(tmp_path / "c")]) == 0
        with zipfile.ZipFile(out) as built:
            for n, (w, h) in sizes.items():
                assert Image.open(io.BytesIO(built.read(n))).size == (scale * w, scale * h), (scale, n)
