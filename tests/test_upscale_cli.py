import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from regen4x import presets, regen4x
from regen4x.tools import upscale
from regen4x.tools._io import CREDIT
from tests.golden_cases import textures
from tests.test_tools import EXPECTED_PACK, pack_fingerprints

BLOCK = "assets/testmod/textures/block/"
ITEM = "assets/testmod/textures/item/"


def pixels(data: bytes | Path) -> NDArray[np.uint8]:
    with Image.open(io.BytesIO(data) if isinstance(data, bytes) else data) as im:
        a: NDArray[np.uint8] = np.asarray(im.convert("RGBA")).copy()
    return a


def run(*args: object, cache: Path) -> int:
    return upscale.main([*map(str, args), "--cache-dir", str(cache)])


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def loose_png(tmp_path: Path) -> Path:
    path = tmp_path / "in" / "blob0.png"
    path.parent.mkdir()
    Image.fromarray(textures()["blob0"]).save(path)
    return path


# ---- inputs -> folder ------------------------------------------------------------------------------------------------


def test_one_png_into_a_folder(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "out"
    assert run(loose_png, "-o", out, cache=cache) == 0
    im = Image.fromarray(textures()["blob0"])
    expected = np.asarray(regen4x(im, presets.ship_for(im), seed=presets.seed_for("blob0.png")))
    assert np.array_equal(pixels(out / "blob0.png"), expected)
    assert (tmp_path / "out.done").read_text(encoding="utf-8").startswith("FINISHED upscaled 1")


def test_a_loose_png_with_kind_gets_the_result_of_the_same_texture_in_the_jar(
    loose_png: Path, built_pack: Path, tmp_path: Path, cache: Path
) -> None:
    out = tmp_path / "out"
    assert run(loose_png, "-o", out, "--kind", "block", "--namespace", "testmod", cache=cache) == 0
    with zipfile.ZipFile(built_pack) as pack:
        in_pack = pixels(pack.read(BLOCK + "blob0.png"))
    assert np.array_equal(pixels(out / (BLOCK + "blob0.png")), in_pack)


def test_a_folder_of_loose_pngs_keeps_its_sub_folders(tmp_path: Path, cache: Path) -> None:
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    Image.fromarray(textures()["blob0"]).save(src / "a.png")
    Image.fromarray(textures()["item1"]).save(src / "sub" / "b.png")
    Image.fromarray(textures()["big32"]).save(src / "c.png")
    out = tmp_path / "out"
    assert run(src, "-o", out, cache=cache) == 0
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*.png")) == ["a.png", "sub/b.png"]
    assert pixels(out / "sub" / "b.png").shape == (64, 64, 4)
    assert "skipped 1" in (tmp_path / "out.done").read_text(encoding="utf-8")


def test_a_jar_into_a_folder_gives_the_textures_of_the_pack(
    mod_jar: Path, built_pack: Path, tmp_path: Path, cache: Path
) -> None:
    out = tmp_path / "out"
    assert run(mod_jar, "-o", out, cache=cache) == 0
    with zipfile.ZipFile(built_pack) as pack:
        for name in pack.namelist():
            if name.endswith(".png"):
                assert np.array_equal(pixels(out / name), pixels(pack.read(name))), name
            elif name != "pack.mcmeta":
                assert (out / name).read_bytes() == pack.read(name)
    assert not (out / "pack.mcmeta").exists()  # a folder is no pack


def test_an_extracted_mod_gives_the_same_as_the_jar(mod_jar: Path, tmp_path: Path, cache: Path) -> None:
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(mod_jar) as z:
        z.extractall(extracted)
    from_jar, from_folder = tmp_path / "from_jar", tmp_path / "from_folder"
    assert run(mod_jar, "-o", from_jar, cache=cache) == 0
    assert run(extracted, "-o", from_folder, cache=cache) == 0
    names = sorted(p.relative_to(from_jar).as_posix() for p in from_jar.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(from_folder).as_posix() for p in from_folder.rglob("*") if p.is_file())
    assert any(n.endswith(".png") for n in names)
    for n in names:
        assert (from_jar / n).read_bytes() == (from_folder / n).read_bytes(), n


# ---- inputs -> zip ---------------------------------------------------------------------------------------------------


def test_a_mods_folder_into_a_new_zip_is_the_pack_of_regen4x_run_pack(
    mod_dir: Path, tmp_path: Path, cache: Path
) -> None:
    out = tmp_path / "pack.zip"
    assert run(mod_dir, "-o", out, "--only", "testmod", cache=cache) == 0
    got, want = pack_fingerprints(out), dict(EXPECTED_PACK)
    assert got.pop("pack.mcmeta") != want.pop("pack.mcmeta")  # only the description differs
    assert got == want
    assert Path(str(out) + ".log").read_text(encoding="utf-8").startswith("sources: ['testmod-1.0.jar']")


def test_a_jar_into_a_new_zip(mod_jar: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    assert run(mod_jar, "-o", out, cache=cache) == 0
    assert sorted(pack_fingerprints(out)) == sorted(EXPECTED_PACK)


def test_a_zip_that_exists_is_not_overwritten_unless_asked(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    out.write_bytes(b"precious")
    with pytest.raises(SystemExit) as refused:
        run(loose_png, "-o", out, cache=cache)
    assert refused.value.code == 2
    assert out.read_bytes() == b"precious"
    assert run(loose_png, "-o", out, "--force", cache=cache) == 0
    assert zipfile.ZipFile(out).namelist() == ["pack.mcmeta", "blob0.png"]


def test_a_new_pack_credits_regen4x_in_its_description(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    assert run(loose_png, "-o", out, cache=cache) == 0
    with zipfile.ZipFile(out) as z:
        description = json.loads(z.read("pack.mcmeta"))["pack"]["description"]
    assert CREDIT in description
    assert "https://github.com/ZarechOleksii/MinecraftTextureUpscaler" in description


def test_update_keeps_the_other_entries_and_replaces_the_upscaled_ones(
    loose_png: Path, tmp_path: Path, cache: Path
) -> None:
    out = tmp_path / "pack.zip"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("pack.mcmeta", '{"pack": {"pack_format": 99, "description": "mine"}}')
        z.writestr("assets/x/lang/en_us.json", "{}")
        z.writestr(ITEM + "old.png", b"keep me")
        z.writestr(BLOCK + "blob0.png", b"replace me")
    args = [loose_png, "-o", out, "--update", "--kind", "block", "--namespace", "testmod"]
    assert run(*args, cache=cache) == 0
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == sorted(
            ["pack.mcmeta", "assets/x/lang/en_us.json", ITEM + "old.png", BLOCK + "blob0.png"]
        )
        assert z.read("pack.mcmeta") == b'{"pack": {"pack_format": 99, "description": "mine"}}'
        assert z.read(ITEM + "old.png") == b"keep me"
        assert pixels(z.read(BLOCK + "blob0.png")).shape == (64, 64, 4)
        assert z.testzip() is None


def test_update_of_a_zip_without_pack_mcmeta_adds_one(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("other.txt", "x")
    assert run(loose_png, "-o", out, "--update", cache=cache) == 0
    assert sorted(zipfile.ZipFile(out).namelist()) == ["blob0.png", "other.txt", "pack.mcmeta"]


def test_update_adds_to_a_pack_one_texture_at_a_time(tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    for name in ("blob0", "item1"):
        png = tmp_path / f"{name}.png"
        Image.fromarray(textures()[name]).save(png)
        flags = ["--update"] if out.exists() else []
        assert run(png, "-o", out, *flags, "--kind", "item", "--namespace", "testmod", cache=cache) == 0
    assert sorted(zipfile.ZipFile(out).namelist()) == [
        "assets/testmod/textures/item/blob0.png",
        "assets/testmod/textures/item/item1.png",
        "pack.mcmeta",
    ]


def test_a_pack_zip_can_be_the_input(built_pack: Path, tmp_path: Path, cache: Path) -> None:
    """A pack made at 16px is upscaled like a jar would be (here: the 64px pack, whose textures are all skipped)."""
    out = tmp_path / "out"
    assert run(built_pack, "-o", out, cache=cache) == 0
    assert not list(out.rglob("*.png"))


def test_an_interrupted_update_leaves_the_zip_as_it_was(mod_jar: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "pack.zip"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("keep.txt", "x")
    before = out.read_bytes()
    assert run(mod_jar, "-o", out, "--update", "--budget", "-1", cache=cache) == 3
    assert out.read_bytes() == before
    assert Path(str(out) + ".done").read_text(encoding="utf-8").startswith("INCOMPLETE")


# ---- scale -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scale", [2, 3, 8])
def test_scale_sets_the_size_of_every_texture_in_the_pack(
    mod_jar: Path, tmp_path: Path, cache: Path, scale: int
) -> None:
    out = tmp_path / "pack.zip"
    assert run(mod_jar, "-o", out, "--scale", scale, cache=cache) == 0
    with zipfile.ZipFile(mod_jar) as jar, zipfile.ZipFile(out) as pack:
        checked = 0
        for name in pack.namelist():
            if not name.endswith(".png"):
                continue
            w, h = Image.open(io.BytesIO(jar.read(name))).size
            assert Image.open(io.BytesIO(pack.read(name))).size == (w * scale, h * scale), name
            checked += 1
        assert checked == 24
        assert "description" in pack.read("pack.mcmeta").decode()
        assert f"{16 * scale}x" in pack.read("pack.mcmeta").decode()


def test_scale_changes_the_cache_so_scales_do_not_mix(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    for scale, side in ((4, 64), (2, 32), (4, 64)):
        out = tmp_path / f"out{scale}"
        assert run(loose_png, "-o", out, "--scale", scale, cache=cache) == 0
        assert pixels(out / "blob0.png").shape[:2] == (side, side)


def test_hole_and_ct_checks_follow_the_scale(mod_dir: Path, mod_jar: Path, tmp_path: Path, cache: Path) -> None:
    from regen4x.tools import ct_check, hole_check

    out = tmp_path / "pack.zip"
    assert run(mod_jar, "-o", out, "--scale", 2, cache=cache) == 0
    with zipfile.ZipFile(mod_jar) as jar, zipfile.ZipFile(out) as pack:
        assert hole_check.find_new_holes(jar, pack, 2) == []
        checked, bad, _ = ct_check.check_pack(pack, mod_dir, ["testmod"], scale=2)
    assert (checked, bad) == (1, [])


# ---- presets and profiles --------------------------------------------------------------------------------------------


def test_blocks_option_replaces_the_preset_for_block_textures(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "out"
    args = [loose_png, "-o", out, "--kind", "block", "--namespace", "testmod", "--blocks", "base-v1.0"]
    assert run(*args, cache=cache) == 0
    im = Image.fromarray(textures()["blob0"])
    expected = regen4x(im, presets.BASE_V1_0, seed=presets.seed_for("testmod/textures/block/blob0.png"))
    assert np.array_equal(pixels(out / (BLOCK + "blob0.png")), np.asarray(expected))
    default = tmp_path / "default"
    assert run(loose_png, "-o", default, "--kind", "block", "--namespace", "testmod", cache=cache) == 0
    assert not np.array_equal(pixels(default / (BLOCK + "blob0.png")), np.asarray(expected))


def test_items_option_and_the_same_texture_as_a_block(tmp_path: Path, cache: Path) -> None:
    png = tmp_path / "item1.png"
    Image.fromarray(textures()["item1"]).save(png)
    base = ["-o", tmp_path / "o1", "--kind", "item", "--namespace", "testmod"]
    assert run(png, *base, "--items", "items-diag-v1.0", cache=cache) == 0
    im = Image.fromarray(textures()["item1"])
    seed = presets.seed_for("testmod/textures/item/item1.png")
    assert np.array_equal(
        pixels(tmp_path / "o1" / (ITEM + "item1.png")), np.asarray(regen4x(im, presets.ITEMS_DIAG_V1_0, seed=seed))
    )


def test_use_glob_and_order(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    out = tmp_path / "out"
    args = [loose_png, "-o", out, "--kind", "block", "--namespace", "testmod"]
    assert run(*args, "--use", "*/block/blob*=lines-v1.0", "--use", "*=base-v1.0", cache=cache) == 0
    im = Image.fromarray(textures()["blob0"])
    expected = regen4x(im, presets.LINES_V1_0, seed=presets.seed_for("testmod/textures/block/blob0.png"))
    assert np.array_equal(pixels(out / (BLOCK + "blob0.png")), np.asarray(expected))  # the first --use wins


def test_own_presets_and_profile_from_a_file(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    mine = tmp_path / "mine.toml"
    mine.write_text(
        "[preset.SMOOTHER]\nextends = 'solid-v1.6'\nsmooth = 3.0\n[profile.mine]\nrules = [{ preset = 'SMOOTHER' }]\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert run(loose_png, "-o", out, "--presets", mine, "--profile", "mine", cache=cache) == 0
    im = Image.fromarray(textures()["blob0"])
    params = presets.load_book([mine]).presets["SMOOTHER"]
    assert np.array_equal(
        pixels(out / "blob0.png"), np.asarray(regen4x(im, params, seed=presets.seed_for("blob0.png")))
    )


def test_another_profile_does_not_reuse_the_cache_of_the_default(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert run(loose_png, "-o", first, cache=cache) == 0
    assert run(loose_png, "-o", second, "--blocks", "base-v1.0", "--use", "*=base-v1.0", cache=cache) == 0
    assert not np.array_equal(pixels(first / "blob0.png"), pixels(second / "blob0.png"))


def test_list_and_describe(capsys: pytest.CaptureFixture[str]) -> None:
    assert upscale.main(["--list"]) == 0
    listing = capsys.readouterr().out
    assert "solid-v1.6" in listing
    assert "otherwise: solid-v1.6" in listing
    assert upscale.main(["--describe", "solid-v1.6"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("solid-v1.6: base-v1.0 -> solid-v1.0 -> solid-v1.1")
    assert "single_con = 0.26   [solid-v1.6]" in text


# ---- usage errors ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["{png}"],
        ["{png}", "-o", "{out}", "--scale", "1"],
        ["{png}", "-o", "{out}", "--scale", "9"],
        ["{png}", "-o", "{out}", "--profile", "nope"],
        ["{png}", "-o", "{out}", "--blocks", "NOPE"],
        ["{png}", "-o", "{out}", "--use", "no-equals-sign"],
        ["{png}", "-o", "{out}", "--presets", "{missing}"],
        ["{missing}", "-o", "{out}"],
        ["{png}", "-o", "{out}", "--only", "x"],
        ["{png}", "-o", "{out}", "--update"],
        ["{png}", "-o", "{out}.zip", "--update"],
        ["{png}", "-o", "{out}.zip", "--update", "--force"],
    ],
)
def test_usage_errors_exit_with_code_2(args: list[str], loose_png: Path, tmp_path: Path, cache: Path) -> None:
    fill = {"png": str(loose_png), "out": str(tmp_path / "out"), "missing": str(tmp_path / "missing")}
    with pytest.raises(SystemExit) as exit_info:
        run(*(a.format_map(fill) for a in args), cache=cache)
    assert exit_info.value.code == 2


def test_an_unknown_file_type_and_an_output_that_is_a_file(tmp_path: Path, loose_png: Path, cache: Path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as unknown:
        run(text, "-o", tmp_path / "out", cache=cache)
    assert unknown.value.code == 2
    with pytest.raises(SystemExit) as is_file:
        run(loose_png, "-o", text, cache=cache)
    assert is_file.value.code == 2


def test_no_jar_matching_only(mod_dir: Path, tmp_path: Path, cache: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(mod_dir, "-o", tmp_path / "out", "--only", "nomatch", cache=cache)
    assert exit_info.value.code == 2


def test_a_bare_family_name_picks_the_preset_of_the_profile(loose_png: Path, tmp_path: Path, cache: Path) -> None:
    by_family, by_name = tmp_path / "family", tmp_path / "name"
    args = ["--kind", "block", "--namespace", "testmod"]
    assert run(loose_png, "-o", by_family, *args, "--blocks", "solid", cache=cache) == 0
    assert run(loose_png, "-o", by_name, *args, "--blocks", "solid-v1.6", cache=cache) == 0
    assert np.array_equal(pixels(by_family / (BLOCK + "blob0.png")), pixels(by_name / (BLOCK + "blob0.png")))


def test_describe_accepts_a_family_name_and_shows_status_and_changes(capsys: pytest.CaptureFixture[str]) -> None:
    assert upscale.main(["--describe", "cutout"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("cutout-v2.1: ")
    assert "status: stable" in text
    assert "changes: " in text


def test_list_shows_status_and_aliases(capsys: pytest.CaptureFixture[str]) -> None:
    assert upscale.main(["--list"]) == 0
    listing = capsys.readouterr().out
    assert "lines-v1.0 [experimental]" in listing
    assert "standard  = standard-r1" in listing
