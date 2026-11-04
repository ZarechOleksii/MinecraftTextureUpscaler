from pathlib import Path

import pytest

from regen4x.tools import run_pack
from tests.synthetic import build_mod_jar

JAR_NAME = "testmod-1.0.jar"


@pytest.fixture(scope="session")
def mod_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A mods folder holding one synthetic jar."""
    folder = tmp_path_factory.mktemp("mods")
    build_mod_jar(folder / JAR_NAME)
    return folder


@pytest.fixture(scope="session")
def mod_jar(mod_dir: Path) -> Path:
    return mod_dir / JAR_NAME


@pytest.fixture(scope="session")
def built_pack(mod_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The resource pack ``regen4x-run-pack`` builds from the synthetic jar."""
    out = tmp_path_factory.mktemp("pack") / "pack.zip"
    cache = tmp_path_factory.mktemp("cache")
    assert run_pack.main([str(mod_dir), str(out), "testmod", "--cache-dir", str(cache)]) == 0
    return out
