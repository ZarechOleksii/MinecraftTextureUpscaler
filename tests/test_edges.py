import importlib
import io
import runpy
import sys
import tomllib
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from regen4x import presets, regen4x
from regen4x.params import RegenParams
from regen4x.tools import (
    check_links,
    ct_check,
    hole_check,
    make_docs,
    make_variant,
    run_pack,
    selftest,
    upscale,
    upscale_folder,
)
from regen4x.tools._io import ZipSink
from tests.golden_cases import textures
from tests.synthetic import png_bytes

REPO = Path(__file__).parents[1]
BLOCK = "assets/m/textures/block/"
type Pixels = NDArray[np.uint8]


def commands() -> dict[str, str]:
    """``[project.scripts]``: command name -> ``module:function``."""
    doc = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    scripts: dict[str, str] = doc["project"]["scripts"]
    return scripts


def write_jar(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def solid(size: tuple[int, int], colour: int = 120) -> bytes:
    a = np.full((size[1], size[0], 4), 255, np.uint8)
    a[..., :3] = colour
    return png_bytes(a)


# ---- the commands --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(commands()))
def test_every_registered_command_points_at_a_main_function(name: str) -> None:
    module, _, function = commands()[name].partition(":")
    assert callable(getattr(importlib.import_module(module), function))


@pytest.mark.parametrize("target", sorted(set(commands().values())))
def test_every_tool_runs_as_a_script(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = target.partition(":")[0]
    monkeypatch.setattr(sys, "argv", [module, "--help"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # the module is already imported; that is the point
        with pytest.raises(SystemExit) as stopped:
            runpy.run_module(module, run_name="__main__")
    assert stopped.value.code in (0, None)


def test_every_tool_is_registered() -> None:
    registered = {t.partition(":")[0] for t in commands().values()}
    tools = {f"regen4x.tools.{p.stem}" for p in (REPO / "src" / "regen4x" / "tools").glob("*.py") if p.stem[0] != "_"}
    assert tools - registered == set()


# ---- the small tools as commands -----------------------------------------------------------------------------


def test_hole_check_command_prints_the_count(
    mod_jar: Path, built_pack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hole_check.main([str(mod_jar), str(built_pack)]) == 0
    assert capsys.readouterr().out.splitlines() == ["0 models with new holes"]


def test_hole_check_lists_the_models_it_flags(
    mod_jar: Path, built_pack: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doctored = tmp_path / "holes.zip"
    with zipfile.ZipFile(built_pack) as src, zipfile.ZipFile(doctored, "w") as out:
        for name in src.namelist():
            clear = name.endswith(("layer_over.png", "layer_base.png"))
            out.writestr(name, png_bytes(np.zeros((64, 64, 4), np.uint8)) if clear else src.read(name))
    assert hole_check.main([str(mod_jar), str(doctored)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "1 models with new holes"
    assert "block/layered.json" in lines[1]


def test_hole_check_ignores_layers_that_are_not_16_pixels(tmp_path: Path) -> None:
    model = b'{"textures": {"a": "m:block/small", "b": "m:block/large"}}'
    jar = write_jar(
        tmp_path / "m.jar",
        {
            f"{BLOCK}small.png": solid((16, 16)),
            f"{BLOCK}large.png": solid((32, 32)),
            "assets/m/models/block/two.json": model,
        },
    )
    with zipfile.ZipFile(jar) as j, zipfile.ZipFile(jar) as same:
        assert hole_check.find_new_holes(j, same) == []


def test_selftest_command_and_its_limit(mod_jar: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert selftest.main([str(mod_jar)]) == 0
    assert capsys.readouterr().out.strip() == "14 block textures, combined hash c0eef90b1a83"
    count, digest = selftest.combined_hash(mod_jar, limit=3)
    assert count == 3
    assert digest != "c0eef90b1a83"


def test_make_variant_command(mod_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "v.zip"
    assert make_variant.main([str(mod_dir), str(out), "testmod", "items64"]) == 0
    assert capsys.readouterr().out.strip().endswith("items64 5 textures")
    assert out.is_file()


def test_upscale_folder_command_reports_what_it_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    Image.fromarray(textures()["blob0"]).save(src / "a.png")
    Image.fromarray(textures()["big32"]).save(src / "b.png")
    assert upscale_folder.main([str(src), str(tmp_path / "dst")]) == 0
    assert capsys.readouterr().out.strip() == "upscaled 1, skipped 1 (not 16x16)"


def test_check_links_command_skips_textures_that_are_not_16_pixels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Image.fromarray(textures()["flat"]).save(tmp_path / "ok.png")
    Image.fromarray(textures()["big32"]).save(tmp_path / "big.png")
    assert check_links.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 textures; textures with a local diagonal link not connected: 0"


# ---- ct_check on a pack that went wrong ----------------------------------------------------------------------


def doctor(pack: Path, target: Path, name: str, data: bytes) -> Path:
    """A copy of ``pack`` where the entry ending in ``name`` is replaced by ``data``."""
    with zipfile.ZipFile(pack) as src, zipfile.ZipFile(target, "w") as out:
        for entry in src.namelist():
            out.writestr(entry, data if entry.endswith(name) else src.read(entry))
    return target


def test_ct_check_flags_a_sheet_of_the_wrong_size(mod_dir: Path, built_pack: Path, tmp_path: Path) -> None:
    pack = doctor(built_pack, tmp_path / "small.zip", "wall_connected.png", solid((16, 16)))
    with zipfile.ZipFile(pack) as z:
        checked, bad, _ = ct_check.check_pack(z, mod_dir, ["testmod"])
    assert checked == 0
    assert [b[1] for b in bad] == ["wrong size"]


def test_ct_check_flags_a_sheet_whose_seams_got_worse(mod_dir: Path, built_pack: Path, tmp_path: Path) -> None:
    sheet = np.zeros((192, 256, 4), np.uint8)
    sheet[..., 3] = 255
    for ty in range(3):
        for tx in range(4):  # tiles that differ as much as they can: any wall made of them shows its seams
            sheet[ty * 64 : (ty + 1) * 64, tx * 64 : (tx + 1) * 64, :3] = 255 * ((tx + ty) % 2)
    pack = doctor(built_pack, tmp_path / "noisy.zip", "wall_connected.png", png_bytes(sheet))
    with zipfile.ZipFile(pack) as z:
        checked, bad, _ = ct_check.check_pack(z, mod_dir, ["testmod"])
    assert checked == 1
    assert len(bad) == 1
    assert str(bad[0][1]).startswith("seam ")


def test_ct_check_only_looks_at_the_jars_asked_for(mod_dir: Path, built_pack: Path) -> None:
    with zipfile.ZipFile(built_pack) as z:
        assert ct_check.check_pack(z, mod_dir, ["other"])[:2] == (0, [])


# ---- a run that meets bad input ------------------------------------------------------------------------------


def build(tmp_path: Path, entries: dict[str, bytes]) -> tuple[int, Path, str]:
    """Run ``regen4x-run-pack`` on a jar of ``entries``: (exit code, pack, summary line)."""
    mods = tmp_path / "mods"
    mods.mkdir()
    write_jar(mods / "m-1.jar", entries)
    out = tmp_path / "pack.zip"
    code = run_pack.main([str(mods), str(out), "m", "--cache-dir", str(tmp_path / "cache")])
    summary = out.with_name(out.name + ".done").read_text(encoding="utf-8")
    return code, out, summary


def test_a_broken_png_is_counted_and_does_not_stop_the_run(tmp_path: Path) -> None:
    code, out, summary = build(tmp_path, {f"{BLOCK}ok.png": solid((16, 16)), f"{BLOCK}bad.png": b"not a png"})
    assert code == 0
    assert "failed 1" in summary
    with zipfile.ZipFile(out) as z:
        assert f"{BLOCK}ok.png" in z.namelist()
        assert f"{BLOCK}bad.png" not in z.namelist()


def test_a_moving_texture_without_a_usable_still_stays_original(tmp_path: Path) -> None:
    """Still and strip are upscaled together or not at all: the still is 32px here, so the strip is dropped."""
    code, out, summary = build(
        tmp_path, {f"{BLOCK}belt.png": solid((32, 32)), f"{BLOCK}belt_scroll.png": solid((16, 32))}
    )
    assert code == 0
    assert "unpaired kept original 1" in summary
    with zipfile.ZipFile(out) as z:
        assert [n for n in z.namelist() if n.endswith(".png")] == []


def test_a_still_whose_strip_failed_stays_original_too(tmp_path: Path) -> None:
    code, out, summary = build(tmp_path, {f"{BLOCK}belt.png": solid((16, 16)), f"{BLOCK}belt_scroll.png": b"broken"})
    assert code == 0
    assert "failed 1" in summary
    assert "unpaired kept original 1" in summary
    with zipfile.ZipFile(out) as z:
        assert [n for n in z.namelist() if n.endswith(".png")] == []


def test_a_connected_sheet_that_is_not_a_whole_number_of_tiles_is_left_alone(tmp_path: Path) -> None:
    code, out, summary = build(
        tmp_path, {f"{BLOCK}wall.png": solid((16, 16)), f"{BLOCK}wall_connected.png": solid((20, 16))}
    )
    assert code == 0
    assert "connected sheets 0" in summary
    with zipfile.ZipFile(out) as z:
        assert f"{BLOCK}wall.png" in z.namelist()
        assert f"{BLOCK}wall_connected.png" not in z.namelist()


@pytest.mark.parametrize("args", [["--profile", "nope"], ["--scale", "99"], ["--presets", "missing.toml"]])
def test_run_pack_refuses_bad_settings(args: list[str], mod_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        run_pack.main([str(mod_dir), str(tmp_path / "o.zip"), "testmod", *args])
    assert stopped.value.code == 2


def test_only_belongs_to_a_folder_of_jars(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    folder.mkdir()
    Image.fromarray(textures()["flat"]).save(folder / "a.png")
    with pytest.raises(SystemExit) as stopped:
        upscale.main([str(folder), "-o", str(tmp_path / "out"), "--only", "x"])
    assert stopped.value.code == 2


def test_a_zip_sink_that_is_abandoned_before_it_wrote_anything_leaves_nothing(tmp_path: Path) -> None:
    target = tmp_path / "pack.zip"
    ZipSink(target).abort()
    assert list(tmp_path.iterdir()) == []


# ---- other corners -------------------------------------------------------------------------------------------


def test_a_profile_with_no_catch_all_rule_says_so() -> None:
    profile = presets.Profile("p", (presets.Rule("A", RegenParams(), path="*/textures/block/*"),))
    assert profile.choose_for("m/textures/block/x.png", False).preset == "A"
    with pytest.raises(LookupError, match="no rule for"):
        profile.choose_for("m/textures/item/x.png", False)


def test_a_preset_page_says_when_nothing_differs_from_the_parent() -> None:
    rows = make_docs.option_table(RegenParams(), RegenParams(), "parent", "child")
    assert rows == ["Nothing: it sets the same options as its parent."]


# ---- what every preset keeps true ----------------------------------------------------------------------------


def odd_textures() -> dict[str, Pixels]:
    """Hand-made shapes the synthetic set does not have: noise, few colours, see-through, diagonals, an outline."""
    rng = np.random.default_rng(2)

    def opaque() -> Pixels:
        a = np.zeros((16, 16, 4), np.uint8)
        a[..., 3] = 255
        return a

    out: dict[str, Pixels] = {}
    noise = opaque()
    noise[..., :3] = rng.integers(0, 256, (16, 16, 3))
    out["noise"] = noise
    palette = rng.integers(0, 256, (4, 3))
    few = opaque()
    few[..., :3] = palette[rng.integers(0, 4, (16, 16))]
    out["few"] = few
    cut = few.copy()
    cut[..., 3] = np.where(rng.random((16, 16)) < 0.3, 0, 255)
    out["cut"] = cut
    diagonals = opaque()
    diagonals[..., :3] = 40
    for i in range(16):
        diagonals[i, i, :3] = 220
        diagonals[i, (i + 5) % 16, :3] = 130
    out["diagonals"] = diagonals
    outline = np.zeros((16, 16, 4), np.uint8)
    outline[2:14, 2:14] = (200, 40, 40, 255)
    outline[5:9, 5:9, :3] = 90
    out["outline"] = outline
    flat = opaque()
    flat[..., :3] = 77
    out["flat"] = flat
    out["clear"] = np.zeros((16, 16, 4), np.uint8)
    return out


@pytest.mark.parametrize("preset", sorted(presets.BOOK.presets))
def test_every_preset_gives_a_full_size_deterministic_picture(preset: str) -> None:
    params = presets.BOOK.preset(preset)
    for name, a in odd_textures().items():
        im = Image.fromarray(a)
        first = np.asarray(regen4x(im, params, seed=3, scale=4))
        assert first.shape == (64, 64, 4), name
        assert first.dtype == np.uint8, name
        if name == "noise":
            assert np.array_equal(first, np.asarray(regen4x(im, params, seed=3, scale=4)))
        if name == "clear":
            assert (first[..., 3] == 0).all()
        if name == "flat":
            assert (first[..., 3] == 255).all()
            assert (first[..., :3] == 77).all()


@pytest.mark.parametrize("scale", [2, 3, 8])
def test_the_size_follows_the_scale(scale: int) -> None:
    im = Image.fromarray(odd_textures()["cut"])
    for preset in ("solid-v1.6", "cutout-v2.1"):
        out = regen4x(im, presets.BOOK.preset(preset), seed=1, scale=scale)
        assert out.size == (16 * scale, 16 * scale)


def test_the_seed_changes_the_grain_but_not_the_shape() -> None:
    im = Image.fromarray(odd_textures()["noise"])
    params = presets.BOOK.preset("solid-v1.6")
    a = np.asarray(regen4x(im, params, seed=1, scale=4))
    b = np.asarray(regen4x(im, params, seed=2, scale=4))
    assert a.shape == b.shape
    assert regen4x(im, params, seed=1, scale=4).tobytes() == a.tobytes()


def test_other_sizes_than_16_still_scale_by_the_factor() -> None:
    """The library does not insist on 16 pixels (the tools do): a 20x12 picture comes out at 80x48."""
    im = Image.new("RGBA", (20, 12), (90, 120, 60, 255))
    assert regen4x(im, presets.BOOK.preset("solid-v1.6"), seed=1, scale=4).size == (80, 48)


def test_png_round_trip_helper_is_lossless() -> None:
    a = odd_textures()["cut"]
    with Image.open(io.BytesIO(png_bytes(a))) as im:
        assert np.array_equal(np.asarray(im.convert("RGBA")), a)


def test_ct_check_command_prints_what_it_flags(
    mod_dir: Path, built_pack: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pack = doctor(built_pack, tmp_path / "small.zip", "wall_connected.png", solid((16, 16)))
    assert ct_check.main([str(pack), str(mod_dir), "testmod"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "0 sheets checked; 1 flagged"
    assert "wrong size" in lines[1]


def test_make_docs_refuses_a_broken_presets_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[preset.X]\nextends = 'NOPE'\n", encoding="utf-8")
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "samples.toml").write_text("[[sample]]\nfile = 'a.png'\nkind = 'block'\n", encoding="utf-8")
    Image.fromarray(textures()["flat"]).save(samples / "a.png")
    with pytest.raises(SystemExit) as stopped:
        make_docs.main(["--samples", str(samples), "--out", str(tmp_path / "out"), "--presets", str(bad)])
    assert stopped.value.code == 2


def test_a_connected_sheet_of_one_tile_is_still_upscaled(tmp_path: Path) -> None:
    """The sheet is itself a 16x16 texture, so it is first upscaled as one and then replaced by the sheet version."""
    code, out, summary = build(
        tmp_path, {f"{BLOCK}wall.png": solid((16, 16)), f"{BLOCK}wall_connected.png": solid((16, 16), 200)}
    )
    assert code == 0
    assert "connected sheets 1" in summary
    with zipfile.ZipFile(out) as z:
        assert {f"{BLOCK}wall.png", f"{BLOCK}wall_connected.png"} <= set(z.namelist())
        with Image.open(io.BytesIO(z.read(f"{BLOCK}wall_connected.png"))) as sheet:
            assert sheet.size == (64, 64)
