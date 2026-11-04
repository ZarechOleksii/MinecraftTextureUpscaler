import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOOD = "---\nokf: 1\npath: {path}\npurpose: Something.\n---\n\n# T\n\n{body}\n"


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("okf_check", ROOT / ".github" / "scripts" / "okf_check.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


okf = load_checker()


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tree(tmp_path: Path) -> list[str]:
    write(tmp_path, "OKF.md", GOOD.format(path=".", body="- [a.py](a.py): x.\n- [sub/](sub/OKF.md): y."))
    write(tmp_path, "a.py", "")
    write(tmp_path, "sub/OKF.md", GOOD.format(path="sub", body="- [b.py](b.py): x. Related: [a](../a.py)."))
    write(tmp_path, "sub/b.py", "")
    write(tmp_path, "sub/pic.png", "")
    return ["OKF.md", "a.py", "sub/OKF.md", "sub/b.py", "sub/pic.png"]


def test_the_repository_documentation_is_complete() -> None:
    assert okf.check(ROOT, okf.tracked_files(ROOT)) == []


def test_a_complete_tree_passes(tmp_path: Path) -> None:
    assert okf.check(tmp_path, tree(tmp_path)) == []


def test_a_missing_okf_file_is_reported(tmp_path: Path) -> None:
    files = tree(tmp_path)
    (tmp_path / "sub" / "OKF.md").unlink()
    assert any("sub/OKF.md: missing" in e for e in okf.check(tmp_path, files))


def test_an_undocumented_file_is_reported(tmp_path: Path) -> None:
    files = [*tree(tmp_path), "sub/c.py"]
    write(tmp_path, "sub/c.py", "")
    assert okf.check(tmp_path, files) == ["sub/OKF.md: no entry for c.py"]


def test_a_dead_link_is_reported(tmp_path: Path) -> None:
    files = tree(tmp_path)
    (tmp_path / "sub" / "b.py").unlink()
    assert any("points at nothing" in e for e in okf.check(tmp_path, files))


def test_bad_front_matter_is_reported(tmp_path: Path) -> None:
    files = tree(tmp_path)
    write(tmp_path, "sub/OKF.md", GOOD.format(path="other", body="- [b.py](b.py): x."))
    assert any("expected 'sub'" in e for e in okf.check(tmp_path, files))
    write(tmp_path, "sub/OKF.md", "no front matter\n[b.py](b.py)\n")
    assert any("front matter must define" in e for e in okf.check(tmp_path, files))


def test_a_directory_that_is_not_linked_from_its_parent_is_reported(tmp_path: Path) -> None:
    files = tree(tmp_path)
    write(tmp_path, "OKF.md", GOOD.format(path=".", body="- [a.py](a.py): x."))
    assert okf.check(tmp_path, files) == ["OKF.md: no link to sub/OKF.md"]


def test_generated_directories_and_code_fences_are_ignored(tmp_path: Path) -> None:
    files = [*tree(tmp_path), "docs/presets/x.md"]
    write(
        tmp_path, "OKF.md", GOOD.format(path=".", body="- [a.py](a.py): x.\n- [sub/](sub/OKF.md): y.\n```\n[z](z)\n```")
    )
    assert okf.check(tmp_path, files) == []


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["sub/b.py"], 1),
        (["sub/b.py", "sub/OKF.md"], 0),
        (["sub/pic.png"], 0),
    ],
)
def test_changed_files_without_their_okf_warn(tmp_path: Path, changed: list[str], expected: int) -> None:
    warnings = okf.stale_warnings(tree(tmp_path), changed)
    assert len(warnings) == expected
    assert all(w.startswith("::warning file=sub/b.py::") for w in warnings)
