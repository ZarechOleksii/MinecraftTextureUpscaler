import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from regen4x import presets
from regen4x.tools import check_links, ct_check, hole_check, make_variant, run_pack, selftest, upscale_folder
from tests.golden_cases import fingerprint, textures

EXPECTED_PACK = json.loads((Path(__file__).parent / "golden" / "pack_expected.json").read_text(encoding="utf-8"))


def pack_fingerprints(path: Path) -> dict[str, str]:
    """sha1 per pack entry; PNGs are compared by decoded pixels so the encoder version does not matter."""
    import hashlib

    out = {}
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            data = z.read(name)
            if name.endswith(".png"):
                with Image.open(io.BytesIO(data)) as im:
                    rgba = im.convert("RGBA")
                    data = str(rgba.size).encode() + rgba.tobytes()
            out[name] = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    return out


# ---- run_pack -------------------------------------------------------------------------------------------------------


def test_pack_matches_the_one_the_original_script_built(built_pack: Path) -> None:
    assert pack_fingerprints(built_pack) == EXPECTED_PACK


def test_pack_summary_and_log(built_pack: Path) -> None:
    done = Path(str(built_pack) + ".done").read_text(encoding="utf-8")
    assert done.startswith("FINISHED upscaled 24 (items/cutouts 8, solid blocks 11, animations 1, scroll strips 3")
    assert "shift pairs 2" in done
    assert "connected sheets 1" in done
    assert "skipped 2 (other sizes), failed 0" in done
    log = Path(str(built_pack) + ".log").read_text(encoding="utf-8")
    assert "testmod-1.0.jar: 26 candidate textures" in log
    assert "connected-texture sheets: 1" in log


def test_second_run_is_served_from_the_cache(mod_dir: Path, built_pack: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    assert run_pack.main([str(mod_dir), str(first), "testmod", "--cache-dir", str(cache)]) == 0
    cached = sorted(cache.rglob("*.png"))
    assert cached
    assert run_pack.main([str(mod_dir), str(second), "testmod", "--cache-dir", str(cache)]) == 0
    assert sorted(cache.rglob("*.png")) == cached
    assert pack_fingerprints(first) == pack_fingerprints(second) == EXPECTED_PACK


def test_budget_stops_cleanly_without_writing_the_pack(
    mod_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "pack.zip"
    code = run_pack.main([str(mod_dir), str(out), "testmod", "--cache-dir", str(tmp_path / "c"), "--budget", "-1"])
    assert code == 3
    assert Path(str(out) + ".done").read_text(encoding="utf-8").startswith("INCOMPLETE")
    assert "INCOMPLETE" in capsys.readouterr().out
    assert not out.exists() or out.stat().st_size == 0


def test_cache_dir_falls_back_to_the_environment(
    mod_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGEN_CACHE", str(tmp_path / "env_cache"))
    assert run_pack.main([str(mod_dir), str(tmp_path / "p.zip"), "nomatch"]) == 0  # no jar matches: empty pack
    assert not (tmp_path / "env_cache").exists() or not list((tmp_path / "env_cache").rglob("*.png"))
    assert run_pack.main([str(mod_dir), str(tmp_path / "q.zip"), "testmod"]) == 0
    assert list((tmp_path / "env_cache").rglob("*.png"))


def test_budget_object() -> None:
    run_pack.Budget(None).check()
    run_pack.Budget(1e9).check()
    with pytest.raises(run_pack.OutOfTimeError):
        run_pack.Budget(-1).check()


def test_code_hash_is_a_short_stable_hex_string() -> None:
    h = run_pack.code_hash()
    assert len(h) == 10
    int(h, 16)
    assert h == run_pack.code_hash()


# ---- hole_check / ct_check ------------------------------------------------------------------------------------------


def test_hole_check_reports_no_holes_for_a_good_pack(mod_jar: Path, built_pack: Path) -> None:
    with zipfile.ZipFile(mod_jar) as jar, zipfile.ZipFile(built_pack) as pack:
        assert hole_check.find_new_holes(jar, pack) == []


def test_hole_check_finds_holes_when_layers_go_clear(mod_jar: Path, built_pack: Path, tmp_path: Path) -> None:
    clear = io.BytesIO()
    Image.fromarray(np.zeros((64, 64, 4), np.uint8)).save(clear, "PNG")
    doctored = tmp_path / "holes.zip"
    with zipfile.ZipFile(built_pack) as src, zipfile.ZipFile(doctored, "w") as out:
        for name in src.namelist():
            replace = name.endswith(("layer_over.png", "layer_base.png"))
            out.writestr(name, clear.getvalue() if replace else src.read(name))
    with zipfile.ZipFile(mod_jar) as jar, zipfile.ZipFile(doctored) as pack:
        found = hole_check.find_new_holes(jar, pack)
    assert found == [(4048, "block/layered.json", ["block/layer_base.png", "block/layer_over.png"])]


def test_hole_check_reference_parsing() -> None:
    assert hole_check.split_ref("mod:block/x") == ("mod", "block/x")
    assert hole_check.split_ref("block/x") == ("minecraft", "block/x")
    assert hole_check.texture_file("mod:block/x") == "assets/mod/textures/block/x.png"


def test_ct_check_accepts_the_built_pack(mod_dir: Path, built_pack: Path) -> None:
    with zipfile.ZipFile(built_pack) as pack:
        checked, bad, rows = ct_check.check_pack(pack, mod_dir, ["testmod"], wanted=["wall"])
    assert (checked, bad) == (1, [])
    assert [r.name for r in rows] == ["wall"]


def test_ct_check_seams() -> None:
    flat = np.full((48, 48, 4), 90, np.uint8)
    assert ct_check.seams(flat, 16) == 0
    striped = flat.copy()
    striped[:, 16:32, :3] = 190
    assert ct_check.seams(striped, 16) > 0


def test_ct_check_cli_writes_the_comparison_image(
    mod_dir: Path, built_pack: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    png = tmp_path / "cmp.png"
    args = [str(built_pack), str(mod_dir), "testmod", "--sheet", str(png), "wall"]
    assert ct_check.main(args) == 0
    assert capsys.readouterr().out.startswith("1 sheets checked; 0 flagged")
    assert png.stat().st_size > 0


# ---- make_variant / upscale_folder / selftest / check_links ----------------------------------------------------------


@pytest.mark.parametrize(("mode", "count"), [("identity16", 19), ("items64", 5), ("blocks64", 14)])
def test_make_variant(mod_jar: Path, tmp_path: Path, mode: str, count: int) -> None:
    out = tmp_path / f"{mode}.zip"
    assert make_variant.make_variant(mod_jar, out, mode) == count
    with zipfile.ZipFile(out) as z:
        assert len(z.namelist()) == count + 1  # + pack.mcmeta
        sizes = {Image.open(io.BytesIO(z.read(n))).size for n in z.namelist() if n.endswith(".png")}
    assert sizes == ({(16, 16)} if mode == "identity16" else {(64, 64)})


def test_upscale_folder(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    Image.fromarray(textures()["blob0"]).save(src / "a.png")
    Image.fromarray(textures()["item1"]).save(src / "sub" / "b.png")
    Image.fromarray(textures()["big32"]).save(src / "c.png")
    assert upscale_folder.upscale_folder(src, dst) == (2, 1)
    assert Image.open(dst / "sub" / "b.png").size == (64, 64)
    assert not (dst / "c.png").exists()
    assert upscale_folder.upscale_folder(src, tmp_path / "dst2", "base-v1.0") == (2, 1)


def test_upscale_folder_is_deterministic_and_matches_regen4x(tmp_path: Path) -> None:
    from regen4x import regen4x

    src = tmp_path / "src"
    src.mkdir()
    Image.fromarray(textures()["blob0"]).save(src / "a.png")
    upscale_folder.upscale_folder(src, tmp_path / "one")
    upscale_folder.upscale_folder(src, tmp_path / "two")
    first = (tmp_path / "one" / "a.png").read_bytes()
    assert first == (tmp_path / "two" / "a.png").read_bytes()
    im = Image.fromarray(textures()["blob0"])
    expected = regen4x(im, presets.ship_for(im), seed=presets.seed_for("a.png"))
    assert fingerprint(Image.open(tmp_path / "one" / "a.png").convert("RGBA")) == fingerprint(expected)


def test_selftest_hash_matches_the_original(mod_jar: Path) -> None:
    assert selftest.combined_hash(mod_jar) == (14, "c0eef90b1a83")


def test_check_links_folder_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name, a in textures().items():
        if a.shape[:2] == (16, 16):
            Image.fromarray(a).save(tmp_path / f"{name}.png")
    assert check_links.main([str(tmp_path)]) == 0
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line == "37 textures; textures with a local diagonal link not connected: 4"


def test_check_links_local_check_on_a_clean_texture() -> None:
    assert check_links.local_check(Image.fromarray(textures()["flat"]), presets.LINES_V1_0) == []


# ---- command line errors --------------------------------------------------------------------------------------------


def test_cli_usage_errors_exit_with_code_2(mod_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as no_args:
        run_pack.main([])
    assert no_args.value.code == 2
    with pytest.raises(SystemExit) as bad_preset:
        upscale_folder.main([str(tmp_path), str(tmp_path), "NOPE"])
    assert bad_preset.value.code == 2
    with pytest.raises(SystemExit) as no_jar:
        make_variant.main([str(mod_dir), str(tmp_path / "x.zip"), "nomatch", "blocks64"])
    assert no_jar.value.code == 2
