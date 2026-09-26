"""FU-13: ``TRIPARTITE_DATA_DIR`` replaces ``<repo>/data`` (ARCHITECTURE.md D3).

The variable is read at every call. It must be an absolute path to an existing directory;
anything else raises ``DataError`` naming it. The name is spelled out here as D3 documents it,
not taken from the code.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tripartite.data import manifest
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.records import load_eval_records

VAR = "TRIPARTITE_DATA_DIR"
PATH_FUNCTIONS: list[Callable[[], Path]] = [
    manifest.data_dir,
    manifest.raw_dir,
    manifest.manifest_path,
    manifest.database_zip_path,
]
PATH_IDS = ["data_dir", "raw_dir", "manifest_path", "database_zip_path"]


def _paths() -> list[Path]:
    return [resolve() for resolve in PATH_FUNCTIONS]


def _expected(root: Path) -> list[Path]:
    return [root, root / "raw", root / "MANIFEST.json", root / "downloads" / "sandbox_database.zip"]


def test_unset_means_the_repository_data_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAR, raising=False)

    assert _paths() == _expected(manifest.REPO_ROOT / "data")
    assert (manifest.REPO_ROOT / "pyproject.toml").is_file()


def test_set_replaces_the_root_of_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR, str(tmp_path))

    assert _paths() == _expected(tmp_path)


def test_the_variable_is_read_at_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.setenv(VAR, str(first))
    assert _paths() == _expected(first)
    monkeypatch.setenv(VAR, str(second))
    assert _paths() == _expected(second)
    monkeypatch.delenv(VAR)
    assert _paths() == _expected(manifest.REPO_ROOT / "data")


@pytest.mark.parametrize("resolve", PATH_FUNCTIONS, ids=PATH_IDS)
@pytest.mark.parametrize("value", ["data", "./data", "~/data", ""])
def test_a_relative_path_is_refused(
    resolve: Callable[[], Path], value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused even when it names a directory that exists relative to the working directory."""
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(VAR, value)

    with pytest.raises(manifest.DataError, match=rf"^{VAR} must be an absolute path, got "):
        resolve()


@pytest.mark.parametrize("resolve", PATH_FUNCTIONS, ids=PATH_IDS)
def test_a_missing_directory_is_refused(
    resolve: Callable[[], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR, str(tmp_path / "absent"))

    with pytest.raises(manifest.DataError, match=rf"^{VAR} must be an existing directory") as info:
        resolve()
    assert str(tmp_path / "absent") in str(info.value)


def test_a_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"")
    monkeypatch.setenv(VAR, str(path))

    with pytest.raises(manifest.DataError, match=rf"^{VAR} must be an existing directory"):
        manifest.data_dir()


@pytest.mark.parametrize(
    "loader", [load_planner_inputs, load_eval_records], ids=["planner_inputs", "eval_records"]
)
@pytest.mark.parametrize("value", ["data", "/nonexistent/tripartite-data"])
def test_the_loaders_refuse_an_invalid_variable(
    loader: Callable[[], Any], value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR, value)

    with pytest.raises(manifest.DataError, match=rf"^{VAR} must be "):
        loader()
