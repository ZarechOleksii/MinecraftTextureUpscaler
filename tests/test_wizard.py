import zipfile
from pathlib import Path

import pytest
from PIL import Image

from regen4x import presets
from regen4x.tools import wizard


def scripted(*answers: str) -> tuple[wizard.Prompter, list[str]]:
    """A prompter that answers from ``answers`` in order, and the lines it said."""
    remaining = iter(answers)
    said: list[str] = []

    def ask(prompt: str) -> str:
        said.append(prompt)
        return next(remaining)

    return wizard.Prompter(ask, said.append), said


def gather(*answers: str, extra: list[Path] | None = None) -> list[str]:
    prompter, _ = scripted(*answers)
    return wizard.gather(prompter, presets.BOOK, extra or [])


def png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (200, 60, 60, 255)).save(path)
    return path


def test_a_jar_asks_for_size_profile_and_output(mod_jar: Path, tmp_path: Path) -> None:
    out = tmp_path / "pack.zip"
    argv = gather(str(mod_jar), "3", "", "n", str(out))
    assert argv == [str(mod_jar), "-o", str(out), "--scale", "3", "--profile", "standard"]


def test_every_question_has_a_default(mod_jar: Path) -> None:
    argv = gather(str(mod_jar), "", "", "", "")
    assert argv[0] == str(mod_jar)
    assert argv[1:2] == ["-o"]
    assert argv[2] == str(mod_jar.with_name("testmod-1.0_64x.zip"))
    assert argv[3:] == ["--scale", "4", "--profile", "standard"]


def test_quotes_around_a_pasted_path_are_dropped(mod_jar: Path, tmp_path: Path) -> None:
    assert gather(f'"{mod_jar}"', "", "", "", str(tmp_path / "o.zip"))[0] == str(mod_jar)


def test_a_missing_input_and_a_bad_size_are_asked_again(mod_jar: Path, tmp_path: Path) -> None:
    prompter, said = scripted(
        str(tmp_path / "nope.jar"), str(mod_jar), "9", "1", "abc", "8", "", "", str(tmp_path / "o")
    )
    argv = wizard.gather(prompter, presets.BOOK, [])
    assert argv[3:] == ["--scale", "8", "--profile", "standard"]
    assert any("does not exist" in line for line in said)
    assert sum("Please enter a whole number" in line for line in said) == 3


def test_loose_pngs_ask_what_they_are(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    png(folder / "a.png")
    argv = gather(str(folder), "item", "mymod", "", "", "", str(tmp_path / "out"))
    expected = [str(folder), "-o", str(tmp_path / "out"), "--scale", "4", "--profile", "standard"]
    assert argv == [*expected, "--kind", "item", "--namespace", "mymod"]


def test_loose_pngs_of_unknown_origin_get_no_kind(tmp_path: Path) -> None:
    single = png(tmp_path / "a.png")
    argv = gather(str(single), "unsure", "", "", "", str(tmp_path / "out"))
    assert "--kind" not in argv


def test_an_extracted_mod_is_not_asked_what_it_is(tmp_path: Path) -> None:
    png(tmp_path / "mod" / "assets" / "m" / "textures" / "block" / "a.png")
    argv = gather(str(tmp_path / "mod"), "", "", "", str(tmp_path / "out"))
    assert "--kind" not in argv


def test_a_folder_of_jars_asks_which_jars_and_checks_the_prefix(mod_dir: Path, tmp_path: Path) -> None:
    prompter, said = scripted(str(mod_dir), "zzz", "testmod, other", "", "", "", str(tmp_path / "o.zip"))
    argv = wizard.gather(prompter, presets.BOOK, [])
    assert argv[argv.index("--only") :] == ["--only", "testmod", "--only", "other"]
    assert any("No jar starts with that" in line for line in said)


def test_a_folder_of_jars_takes_all_when_none_is_named(mod_dir: Path, tmp_path: Path) -> None:
    assert "--only" not in gather(str(mod_dir), "", "", "", "", str(tmp_path / "o.zip"))


def test_a_profile_is_picked_by_number_or_by_name(mod_jar: Path, tmp_path: Path) -> None:
    names = [*presets.BOOK.aliases, *presets.BOOK.profiles]
    assert len(names) > 1
    out = str(tmp_path / "o.zip")
    assert gather(str(mod_jar), "", "2", "", out)[-2:] == ["--profile", names[1]]
    assert gather(str(mod_jar), "", names[1].upper(), "", out)[-2:] == ["--profile", names[1]]


def test_block_and_item_presets_can_be_picked(mod_jar: Path, tmp_path: Path) -> None:
    names = list(presets.BOOK.presets)
    argv = gather(str(mod_jar), "", "", "y", names[2], "", str(tmp_path / "o.zip"))
    assert argv[-2:] == ["--blocks", names[2]]
    argv = gather(str(mod_jar), "", "", "y", "", "solid-v1.6", str(tmp_path / "o.zip"))
    assert argv[-2:] == ["--items", "solid-v1.6"]


def test_an_existing_zip_can_be_updated_replaced_or_swapped(mod_jar: Path, tmp_path: Path) -> None:
    existing = tmp_path / "pack.zip"
    with zipfile.ZipFile(existing, "w"):
        pass
    start = (str(mod_jar), "", "", "n")
    assert gather(*start, str(existing), "update")[3:5] == ["--update", "--scale"]
    assert gather(*start, str(existing), "2")[3:5] == ["--force", "--scale"]
    fresh = tmp_path / "fresh.zip"
    argv = gather(*start, str(existing), "other", str(fresh))
    assert argv[2] == str(fresh)
    assert "--update" not in argv
    assert "--force" not in argv


def test_a_file_cannot_be_an_output_folder_nor_a_folder_a_zip(mod_jar: Path, tmp_path: Path) -> None:
    afile = tmp_path / "file.txt"
    afile.write_text("x", encoding="utf-8")
    adir = tmp_path / "dir.zip"
    adir.mkdir()
    argv = gather(str(mod_jar), "", "", "n", str(afile), str(adir), str(tmp_path / "ok"))
    assert argv[2] == str(tmp_path / "ok")


def test_extra_preset_files_are_passed_on(mod_jar: Path, tmp_path: Path) -> None:
    mine = tmp_path / "mine.toml"
    assert gather(str(mod_jar), "", "", "n", str(tmp_path / "o.zip"), extra=[mine])[-2:] == ["--presets", str(mine)]


def test_the_printed_command_is_a_regen4x_upscale_call(tmp_path: Path) -> None:
    text = wizard.format_command(["in put.jar", "-o", str(tmp_path / "o.zip"), "--scale", "4"])
    assert text.startswith("regen4x-upscale ")
    assert "in put.jar" in text
    assert '"in put.jar"' in text or "'in put.jar'" in text


# ---- the command ------------------------------------------------------------------------------------------


def feed(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    remaining = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(remaining))


def test_the_command_it_prints_is_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # the cache goes to ./cache
    single = png(tmp_path / "in" / "a.png")
    out = tmp_path / "out"
    feed(monkeypatch, str(single), "block", "", "2", "", "n", str(out), "")
    assert wizard.main([]) == 0
    with Image.open(out / "assets" / "minecraft" / "textures" / "block" / "a.png") as im:
        assert im.size == (32, 32)


def test_dry_run_prints_the_command_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    single = png(tmp_path / "a.png")
    out = tmp_path / "out"
    feed(monkeypatch, str(single), "unsure", "", "", "n", str(out))
    assert wizard.main(["--dry-run"]) == 0
    assert "regen4x-upscale" in capsys.readouterr().out
    assert not out.exists()


def test_saying_no_does_not_run_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    single = png(tmp_path / "a.png")
    out = tmp_path / "out"
    feed(monkeypatch, str(single), "unsure", "", "", "n", str(out), "n")
    assert wizard.main([]) == 0
    assert not out.exists()


def test_end_of_input_and_ctrl_c_cancel(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def eof(prompt: str = "") -> str:
        raise EOFError

    def interrupt(prompt: str = "") -> str:
        raise KeyboardInterrupt

    for fn in (eof, interrupt):
        monkeypatch.setattr("builtins.input", fn)
        assert wizard.main([]) == 1
        assert "Cancelled" in capsys.readouterr().out


def test_a_bad_presets_file_is_a_usage_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[preset.X]\nextends = 'NOPE'\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        wizard.main(["--presets", str(bad)])
    assert exit_info.value.code == 2


def test_what_each_kind_of_input_is_asked(mod_jar: Path, mod_dir: Path, tmp_path: Path) -> None:
    assert wizard.classify(tmp_path / "missing") is None
    odd = tmp_path / "x.txt"
    odd.write_text("x", encoding="utf-8")
    assert wizard.classify(odd) is None
    assert wizard.classify(mod_jar) == wizard.Input(mod_jar, mods=False, loose=False)
    assert wizard.classify(mod_dir) == wizard.Input(mod_dir, mods=True, loose=False)
    assert wizard.classify(png(tmp_path / "a.png")) == wizard.Input(tmp_path / "a.png", mods=False, loose=True)


# ---- the questions themselves ----------------------------------------------------------------------------------------


def test_a_required_answer_is_asked_again_until_given() -> None:
    prompter, said = scripted("", "   ", "value")
    assert prompter.text("Question") == "value"
    assert sum("Please enter a value" in line for line in said) == 2


def test_yes_no_takes_the_default_and_asks_again_on_nonsense() -> None:
    prompter, said = scripted("", "maybe", "YES", "n")
    assert prompter.yes_no("Sure?", False) is False
    assert prompter.yes_no("Sure?", False) is True
    assert prompter.yes_no("Sure?", True) is False
    assert any("Please answer y or n" in line for line in said)


def test_a_choice_that_is_not_in_the_list_is_asked_again() -> None:
    prompter, said = scripted("0", "7", "nothing", "b")
    assert prompter.choose("Pick", [("a", "first"), ("b", "second")], "a") == "b"
    assert sum("Please enter a number from 1 to 2" in line for line in said) == 3


def test_an_input_that_is_neither_folder_nor_known_file_is_explained(tmp_path: Path) -> None:
    odd = tmp_path / "notes.txt"
    odd.write_text("x", encoding="utf-8")
    png_file = png(tmp_path / "a.png")
    prompter, said = scripted(str(odd), str(png_file))
    assert wizard.ask_input(prompter).path == png_file
    assert any("Don't know what to do" in line for line in said)


def test_the_wizard_runs_as_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy
    import sys
    import warnings

    monkeypatch.setattr(sys, "argv", ["wizard", "--help"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as stopped:
            runpy.run_module("regen4x.tools.wizard", run_name="__main__")
    assert stopped.value.code == 0
