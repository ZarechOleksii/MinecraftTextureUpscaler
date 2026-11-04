import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from regen4x import presets
from regen4x.tools import make_docs
from tests.golden_cases import textures

REPO = Path(__file__).parents[1]


def sample_folder(root: Path, extra: str = "") -> Path:
    folder = root / "samples"
    folder.mkdir()
    Image.fromarray(textures()["blob0"]).save(folder / "stone.png")
    Image.fromarray(textures()["item1"]).save(folder / "gem.png")
    (folder / "samples.toml").write_text(
        'title = "Test samples"\nnote = "Made for the tests."\n'
        '[[sample]]\nfile = "stone.png"\nkind = "block"\ngeometry = "soft blobs"\ncredit = "me, CC0"\n'
        '[[sample]]\nfile = "gem.png"\nkind = "item"\ngeometry = "a diamond"\ncredit = "me, CC0"\n' + extra,
        encoding="utf-8",
    )
    return folder


@pytest.fixture(scope="module")
def docs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("docs")
    out = root / "out"
    make_docs.build_docs(make_docs.load_samples(sample_folder(root)), out, presets.BOOK, 4)
    return out


# ---- the manifest ----------------------------------------------------------------------------------------------------


def test_samples_are_read_from_the_manifest(tmp_path: Path) -> None:
    samples = make_docs.load_samples(sample_folder(tmp_path))
    assert (samples.title, samples.note) == ("Test samples", "Made for the tests.")
    assert [(s.name, s.kind, s.geometry, s.credit) for s in samples.samples] == [
        ("stone", "block", "soft blobs", "me, CC0"),
        ("gem", "item", "a diamond", "me, CC0"),
    ]
    assert [s.name for s in samples.of_kind("item")] == ["gem"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('[[sample]]\nfile = "stone.png"\nkind = "block"\n', "used twice"),
        ('[[sample]]\nfile = "nope.png"\nkind = "block"\n', "nope.png"),
        ('[[sample]]\nfile = "stone.png"\nkind = "entity"\n', "needs a 'file' and a 'kind'"),
        ('[[sample]]\nkind = "block"\n', "needs a 'file' and a 'kind'"),
        ('[[sample]]\nfile = "stone.png"\nkind = "block"\ncolour = 1\n', "unknown key(s) 'colour'"),
        ("wrong = 1\n", "unknown key(s) 'wrong'"),
    ],
)
def test_manifest_mistakes_are_refused(tmp_path: Path, extra: str, message: str) -> None:
    folder = sample_folder(tmp_path)
    if "wrong" in extra:
        text = (folder / "samples.toml").read_text(encoding="utf-8")
        (folder / "samples.toml").write_text(extra + text, encoding="utf-8")
    else:
        text = (folder / "samples.toml").read_text(encoding="utf-8")
        (folder / "samples.toml").write_text(text + extra, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(message)):
        make_docs.load_samples(folder)


def test_samples_must_be_16_pixels_and_there_must_be_some(tmp_path: Path) -> None:
    folder = sample_folder(tmp_path)
    Image.fromarray(textures()["big32"]).save(folder / "big.png")
    text = (folder / "samples.toml").read_text(encoding="utf-8")
    (folder / "samples.toml").write_text(text + '[[sample]]\nfile = "big.png"\nkind = "block"\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"big\.png is 32x32"):
        make_docs.load_samples(folder)
    (folder / "samples.toml").write_text('title = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape("no [[sample]] entries")):
        make_docs.load_samples(folder)
    with pytest.raises(ValueError, match=re.escape("samples.toml")):
        make_docs.load_samples(tmp_path / "missing")


# ---- the pages -------------------------------------------------------------------------------------------------------


def test_every_built_in_preset_has_a_description() -> None:
    """The documentation pages are built from them."""
    assert [n for n in presets.PRESETS if not presets.BOOK.notes.get(n, "").strip()] == []


def test_there_is_a_page_and_images_for_every_preset(docs: Path) -> None:
    for name in presets.PRESETS:
        assert (docs / f"{name}.md").is_file()
        for kind in ("blocks", "items"):
            with Image.open(docs / "img" / name / f"{kind}.png") as im:
                assert im.width == make_docs.LABEL_W + 3 * (make_docs.CELL + make_docs.GAP)
                assert im.height == make_docs.HEAD + (make_docs.CELL + make_docs.GAP) + make_docs.GAP
    assert (docs / "README.md").is_file()
    assert sorted(p.name for p in (docs / "img").glob("sheet_*.png")) == [
        f"sheet_{kind}_{n}.png" for kind in ("blocks", "items") for n in (1, 2, 3)
    ]


def test_a_page_says_what_the_preset_changes_against_its_parent(docs: Path) -> None:
    page = (docs / "solid-v1.2.md").read_text(encoding="utf-8")
    assert "# solid-v1.2" in page
    assert "Based on: [solid-v1.1](solid-v1.1.md)" in page
    assert "Built on this: [solid-v1.3](solid-v1.3.md)" in page
    assert "| `line_min_len` | `0` | `5` |" in page
    assert "| `line_strong` | `1.0` | `0.18` |" in page
    assert "| `stair_grow`" not in page.split("## All settings")[0]  # that is the parent's change, not this one's
    assert "line_min_len = 5   [solid-v1.2]" in page
    assert "stair_grow = False   [solid-v1.1]" in page
    assert "Not used by any built-in profile" in page


def test_a_preset_without_a_parent_is_compared_with_the_defaults_and_names_its_profiles(docs: Path) -> None:
    current = (docs / "base-v1.0.md").read_text(encoding="utf-8")
    assert "Compared with defaults:" in current
    assert "| `thr` | `0.13` | `0.07` |" in current
    shipped = (docs / "solid-v1.6.md").read_text(encoding="utf-8")
    assert "- profile `standard-r1`: otherwise" in shipped


def test_the_index_lists_presets_profiles_sheets_and_credits(docs: Path) -> None:
    index = (docs / "README.md").read_text(encoding="utf-8")
    assert index.startswith(make_docs.MARKER)
    assert "# Presets: Test samples" in index
    assert "Made for the tests." in index
    assert all(f"[{n}]({n}.md)" in index for n in presets.PRESETS)
    assert "- `standard`: another name for `standard-r1`" in index
    assert "- `standard-r1`: " in index
    assert "| stone | block | soft blobs | me, CC0 |" in index
    assert "img/sheet_blocks_1.png" in index


def test_every_link_and_image_in_the_docs_exists(docs: Path) -> None:
    pages = sorted(docs.glob("*.md"))
    assert len(pages) == len(presets.PRESETS) + 1
    for page in pages:
        for target in re.findall(r"\]\(([^)#]+)\)", page.read_text(encoding="utf-8")):
            assert (docs / target).is_file(), f"{page.name} links to {target}"


def test_the_output_is_deterministic(tmp_path: Path, docs: Path) -> None:
    again = tmp_path / "again"
    make_docs.build_docs(make_docs.load_samples(sample_folder(tmp_path)), again, presets.BOOK, 4)
    for path in sorted(docs.rglob("*")):
        if path.is_file():
            assert path.read_bytes() == (again / path.relative_to(docs)).read_bytes(), path.name


def test_a_rerun_removes_what_it_wrote_before_but_not_other_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "OLD_PRESET.md").write_text(make_docs.MARKER + "\nold", encoding="utf-8")
    (out / "notes.md").write_text("mine", encoding="utf-8")
    (out / "img").mkdir()
    (out / "img" / "stale.png").write_bytes(b"x")
    make_docs.build_docs(make_docs.load_samples(sample_folder(tmp_path)), out, presets.BOOK, 4)
    assert not (out / "OLD_PRESET.md").exists()
    assert not (out / "img" / "stale.png").exists()
    assert (out / "notes.md").read_text(encoding="utf-8") == "mine"


def test_only_the_kinds_that_have_samples_get_images(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    Image.fromarray(textures()["blob0"]).save(folder / "stone.png")
    (folder / "samples.toml").write_text('[[sample]]\nfile = "stone.png"\nkind = "block"\n', encoding="utf-8")
    out = tmp_path / "out"
    make_docs.build_docs(make_docs.load_samples(folder), out, presets.BOOK, 4)
    assert (out / "img" / "base-v1.0" / "blocks.png").is_file()
    assert not (out / "img" / "base-v1.0" / "items.png").exists()
    assert "### Items" not in (out / "base-v1.0.md").read_text(encoding="utf-8")


def test_other_scales_get_their_own_images_and_a_section_on_the_page(tmp_path: Path) -> None:
    out = tmp_path / "out"
    make_docs.build_docs(make_docs.load_samples(sample_folder(tmp_path)), out, presets.BOOK, 4, also=[2, 8, 4])
    for kind in ("blocks", "items"):
        for scale in (2, 8):
            assert (out / "img" / "base-v1.0" / f"{kind}_x{scale}.png").is_file()
        assert not (out / "img" / "base-v1.0" / f"{kind}_x4.png").exists()
    page = (out / "base-v1.0.md").read_text(encoding="utf-8")
    assert page.index("x2: 16px to 32px") < page.index("x4: 16px to 64px (default)") < page.index("x8: 16px to 128px")
    assert "img/base-v1.0/blocks_x8.png" in page


def test_the_sheet_shows_the_preset_output_next_to_the_original(docs: Path) -> None:
    sheet = np.asarray(Image.open(docs / "img" / "base-v1.0" / "blocks.png").convert("RGBA"))
    x0 = make_docs.LABEL_W
    y0 = make_docs.HEAD
    cell = make_docs.CELL
    original = np.asarray(
        Image.fromarray(textures()["blob0"]).resize((cell, cell), Image.Resampling.NEAREST).convert("RGBA")
    )
    assert np.array_equal(sheet[y0 : y0 + cell, x0 : x0 + cell], original)
    parent = sheet[y0 : y0 + cell, x0 + cell + make_docs.GAP : x0 + 2 * cell + make_docs.GAP]
    assert not np.array_equal(parent, original)


# ---- the command -----------------------------------------------------------------------------------------------------


def test_the_standard_set_is_built_when_present_and_skipped_when_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert make_docs.main([]) == 0
    assert "skipped" in capsys.readouterr().out
    assert not (tmp_path / "docs").exists()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "samples").mkdir()
    sample_folder(elsewhere).rename(tmp_path / "samples" / "free")
    assert make_docs.main([]) == 0
    assert "docs" in capsys.readouterr().out
    assert (tmp_path / "docs" / "presets" / "README.md").is_file()


def test_extra_presets_are_documented_too(tmp_path: Path) -> None:
    mine = tmp_path / "mine.toml"
    mine.write_text('[preset.MINE]\nextends = "solid-v1.6"\ndescription = "My own."\nsmooth = 2.6\n', encoding="utf-8")
    out = tmp_path / "out"
    assert make_docs.main(["--samples", str(sample_folder(tmp_path)), "--out", str(out), "--presets", str(mine)]) == 0
    assert "| `smooth` | `2.2` | `2.6` |" in (out / "MINE.md").read_text(encoding="utf-8")
    assert "Built on this: [MINE](MINE.md)" in (out / "solid-v1.6.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "args",
    [
        ["--samples", "{s}"],
        ["--out", "{o}"],
        ["--samples", "{s}", "--out", "{o}", "--scale", "1"],
        ["--samples", "{s}", "--out", "{o}", "--also", "9"],
        ["--samples", "{o}", "--out", "{o}"],
    ],
)
def test_usage_errors_exit_with_code_2(args: list[str], tmp_path: Path) -> None:
    fill = {"s": str(sample_folder(tmp_path)), "o": str(tmp_path / "out")}
    with pytest.raises(SystemExit) as exit_info:
        make_docs.main([a.format_map(fill) for a in args])
    assert exit_info.value.code == 2


# ---- the committed docs ----------------------------------------------------------------------------------------------


def test_the_committed_docs_are_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pages hold no pixels, so they can be rebuilt without rendering: any difference means someone changed
    presets.toml or the samples and forgot ``regen4x-docs``."""
    monkeypatch.setattr(make_docs, "save", lambda im, path: None)
    monkeypatch.setattr(make_docs.Renderer, "render", lambda self, sample, preset: sample.image)
    committed = REPO / "docs" / "presets"
    assert committed.is_dir(), "run regen4x-docs"
    out = tmp_path / "out"
    make_docs.build_docs(make_docs.load_samples(REPO / "samples" / "free"), out, presets.BOOK, 4, also=[2, 8])
    expected = {p.name for p in out.glob("*.md")}
    assert {p.name for p in committed.glob("*.md")} == expected
    for name in sorted(expected):
        assert (committed / name).read_text(encoding="utf-8") == (out / name).read_text(encoding="utf-8"), (
            f"{name} is out of date: run regen4x-docs"
        )
