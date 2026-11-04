import json
import shutil
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

PACK_FORMAT = 34  # 1.21.1
CREDIT = "Upscaled with regen4x: https://github.com/ZarechOleksii/MinecraftTextureUpscaler"


def is_texture(key: str, folders: Sequence[str]) -> bool:
    """``assets/<ns>/textures/<one of folders>/**.png``"""
    return key.startswith("assets/") and key.endswith(".png") and any(f"/textures/{f}/" in key for f in folders)


class Source(ABC):
    """Textures to upscale."""

    label: str

    @abstractmethod
    def names(self) -> set[str]:
        """Every key (also the ones that are no textures: .mcmeta files, models ...)."""

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def texture_keys(self, folders: Sequence[str]) -> list[str]:
        """The PNGs to consider, sorted. Loose files are all taken; jars and packs only the given texture folders."""

    def out_name(self, key: str) -> str:
        """The name of the entry written for ``key``."""
        return key

    def close(self) -> None:  # noqa: B027 (optional hook)
        pass


class ZipSource(Source):
    """A mod jar or a resource pack zip."""

    def __init__(self, path: Path) -> None:
        self.label = path.name
        self._zip = zipfile.ZipFile(path)
        self._names = set(self._zip.namelist())

    def names(self) -> set[str]:
        return self._names

    def read(self, key: str) -> bytes:
        return self._zip.read(key)

    def texture_keys(self, folders: Sequence[str]) -> list[str]:
        return sorted(n for n in self._names if is_texture(n, folders))

    def close(self) -> None:
        self._zip.close()


class DirSource(Source):
    """A folder (or one PNG).

    A folder with an ``assets`` folder inside is an extracted mod or pack and behaves like :class:`ZipSource`.
    Anything else is loose files: they get the key ``assets/<relative path>``, where the relative path is the one seen
    from the folder, or ``<namespace>/textures/<kind>/<relative path>`` if ``kind`` is given. With ``kind`` the
    output entries are named like the key (a proper ``assets/...`` pack path, and the same texture seed as in the real
    jar); without it they keep the plain relative path.
    """

    def __init__(self, path: Path, *, kind: str | None = None, namespace: str = "minecraft") -> None:
        single = path.is_file()
        root = path.parent if single else path
        self.label = path.name
        self.packlike = not single and (root / "assets").is_dir()
        files = [path, path.with_name(path.name + ".mcmeta")] if single else sorted(root.rglob("*"))
        self._paths: dict[str, Path] = {}
        self._out: dict[str, str] = {}
        for f in files:
            if not f.is_file():
                continue
            rel = f.relative_to(root).as_posix()
            if self.packlike:
                key = out = rel
            else:
                key = "assets/" + (f"{namespace}/textures/{kind}/{rel}" if kind else rel)
                out = key if kind else rel
            self._paths[key] = f
            self._out[key] = out

    def names(self) -> set[str]:
        return set(self._paths)

    def read(self, key: str) -> bytes:
        return self._paths[key].read_bytes()

    def texture_keys(self, folders: Sequence[str]) -> list[str]:
        if self.packlike:
            return sorted(k for k in self._paths if is_texture(k, folders))
        return sorted(k for k in self._paths if k.endswith(".png"))

    def out_name(self, key: str) -> str:
        return self._out[key]


class Sink(ABC):
    """Where the upscaled textures go."""

    @abstractmethod
    def write(self, name: str, data: bytes) -> None: ...

    @abstractmethod
    def commit(self) -> None:
        """Everything was written: make the result visible."""

    def abort(self) -> None:  # noqa: B027 (optional hook)
        """Something went wrong: leave the target as it was."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.abort()


class FolderSink(Sink):
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, name: str, data: bytes) -> None:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def commit(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class ZipSink(Sink):
    """A resource pack zip. Built next to the target and copied over it at the end.

    The zip is copied over the target (not renamed onto it) because a connected folder (network share, cloud sync) may
    not allow deleting or replacing files.
    """

    def __init__(self, path: Path, *, update: bool = False, description: str = "regen4x") -> None:
        self.path = path
        self.update = update and path.exists()
        self.description = description
        self.tmp = path.with_name(path.name + ".partial")
        self._written: set[str] = set()
        self._zip: zipfile.ZipFile | None = None

    def _out(self) -> zipfile.ZipFile:
        if self._zip is None:
            self._zip = zipfile.ZipFile(self.tmp, "w", zipfile.ZIP_DEFLATED)
            if not (self.update and self._old_has("pack.mcmeta")):
                description = f"{self.description}\n{CREDIT}"
                mcmeta = {"pack": {"pack_format": PACK_FORMAT, "description": description}}
                self.write("pack.mcmeta", json.dumps(mcmeta, indent=2).encode())
        return self._zip

    def _old_has(self, name: str) -> bool:
        with zipfile.ZipFile(self.path) as old:
            return name in old.namelist()

    def __enter__(self) -> Self:
        self._out()
        return self

    def write(self, name: str, data: bytes) -> None:
        self._out().writestr(name, data)
        self._written.add(name)

    def commit(self) -> None:
        out = self._out()
        if self.update:
            with zipfile.ZipFile(self.path) as old:
                for info in old.infolist():
                    if info.filename not in self._written:
                        out.writestr(info, old.read(info))
        out.close()
        shutil.copyfile(self.tmp, self.path)
        self.tmp.write_bytes(b"")

    def abort(self) -> None:
        if self._zip is not None:
            self._zip.close()
