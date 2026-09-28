"""``evaluator_ready()`` (ARCHITECTURE.md D8 §health, FU-18), on temporary trees only.

``tree`` builds everything the real evaluator needs in ``tmp_path``: a data root set as
``TRIPARTITE_DATA_DIR`` (the synthetic ``raw/`` files and a manifest recording them), a vendor
tree with ``VENDOR.lock`` and the 8 database files (synthetic contents, §8), and an evalenv
interpreter. ``readiness``'s two paths and ``manifest.VENDOR_DATABASE_DIR`` point into it. The
real vendor tree, evalenv and data are read only by the ``local`` test at the end.
"""

import contextlib
import os
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.data import synthetic
from tripartite.data import manifest
from tripartite.evaluation import readiness
from tripartite.evaluation.readiness import evaluator_ready

DATABASE = [f"database/{path}" for path in synthetic.DATABASE_FILES]
PIECES = ["vendor_lock", "python", "manifest", "validation_csv", *DATABASE]
SIZED = ["validation_csv", *DATABASE]


@dataclass(frozen=True)
class Tree:
    vendor_lock: Path
    python: Path
    manifest: Path
    database: Path
    validation_csv: Path

    def path(self, piece: str) -> Path:
        if piece.startswith("database/"):
            return self.database / piece.removeprefix("database/")
        path: Path = getattr(self, piece)
        return path


@pytest.fixture
def tree(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tree:
    """Everything the evaluator needs, in ``tmp_path``, with ``TRIPARTITE_EVAL_BRIDGE=real``."""
    raw = synthetic.write_synthetic_data_dir(data_dir) / "raw"
    vendor = tmp_path / "vendor" / "travelplanner"
    database = vendor / "database"
    for path, data in synthetic.DATABASE_FILES.items():
        (database / path).parent.mkdir(parents=True, exist_ok=True)
        (database / path).write_bytes(data)
    (vendor / "VENDOR.lock").write_text("{}\n")
    python = tmp_path / "evalenv" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)  # as in a uv venv
    # Real sizes, deliberately wrong hashes: evaluator_ready never compares a hash (D8).
    database_files = {
        path: manifest.FileEntry(bytes=len(data), sha256="0" * 64)
        for path, data in synthetic.DATABASE_FILES.items()
    }
    recorded = synthetic.matching_manifest(raw).model_copy(
        update={"database_files": database_files}
    )
    manifest.write_manifest(recorded, manifest.manifest_path())
    monkeypatch.setattr(readiness, "VENDOR_LOCK", vendor / "VENDOR.lock")
    monkeypatch.setattr(readiness, "EVALENV_PYTHON", python)
    monkeypatch.setattr(manifest, "VENDOR_DATABASE_DIR", database)
    monkeypatch.setenv("TRIPARTITE_EVAL_BRIDGE", "real")
    return Tree(
        vendor_lock=vendor / "VENDOR.lock",
        python=python,
        manifest=manifest.manifest_path(),
        database=database,
        validation_csv=raw / manifest.VALIDATION_CSV,
    )


# --- recording file opens and process starts (PEP 578 audit hooks) ---------------------------


class AuditRecorder:
    """Records every file open and process start while ``recording()`` is active. An audit hook
    sees opens from C code too, which replacing ``open`` would not."""

    WATCHED = frozenset({"open", "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"})

    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[Any, ...]]] | None = None

    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        if self.events is not None and event in self.WATCHED:
            self.events.append((event, args))

    @contextlib.contextmanager
    def recording(self) -> Iterator[list[tuple[str, tuple[Any, ...]]]]:
        self.events = events = []
        try:
            yield events
        finally:
            self.events = None


@pytest.fixture(scope="session")
def audit() -> AuditRecorder:
    """An audit hook cannot be removed, so one serves the session; it is idle outside tests."""
    recorder = AuditRecorder()
    sys.addaudithook(recorder)
    return recorder


def _opened(events: list[tuple[str, tuple[Any, ...]]]) -> set[str]:
    return {
        str(path) if isinstance(path, int) else os.path.realpath(os.fsdecode(path))
        for event, (path, *_) in events
        if event == "open"
    }


# --- ready ---------------------------------------------------------------------------------


def test_the_default_paths_are_d8s() -> None:
    assert readiness.VENDOR_LOCK == manifest.REPO_ROOT / "vendor" / "travelplanner" / "VENDOR.lock"
    assert readiness.EVALENV_PYTHON == manifest.REPO_ROOT / "evalenv" / ".venv" / "bin" / "python"


def test_a_complete_tree_is_ready(tree: Tree) -> None:
    assert set(synthetic.DATABASE_FILES) == set(manifest.EXPECTED_DATABASE_FILES)

    assert evaluator_ready() is True


def test_only_the_manifest_is_opened_and_no_process_is_started(
    tree: Tree, audit: AuditRecorder
) -> None:
    evaluator_ready()  # a first call may import lazily loaded modules; those opens are Python's

    with audit.recording() as events:
        ready = evaluator_ready()

    assert ready is True
    assert _opened(events) == {os.path.realpath(tree.manifest)}
    assert [event for event, _ in events if event != "open"] == []


def test_fake_mode_is_ready_without_touching_the_file_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audit: AuditRecorder
) -> None:
    monkeypatch.setenv("TRIPARTITE_EVAL_BRIDGE", "fake")
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setattr(readiness, "VENDOR_LOCK", tmp_path / "nowhere" / "VENDOR.lock")
    monkeypatch.setattr(readiness, "EVALENV_PYTHON", tmp_path / "nowhere" / "python")

    with audit.recording() as events:
        ready = evaluator_ready()

    assert ready is True
    assert events == []


# --- not ready -----------------------------------------------------------------------------


@pytest.mark.parametrize("piece", PIECES)
def test_a_missing_piece_is_not_ready(tree: Tree, piece: str) -> None:
    tree.path(piece).unlink()

    assert evaluator_ready() is False


@pytest.mark.parametrize("piece", SIZED)
@pytest.mark.parametrize("change", ["longer", "shorter"])
def test_a_file_of_the_wrong_size_is_not_ready(tree: Tree, piece: str, change: str) -> None:
    path = tree.path(piece)
    data = path.read_bytes()
    path.write_bytes(data + b"x" if change == "longer" else data[:-1])

    assert evaluator_ready() is False


def test_a_dangling_interpreter_symlink_is_not_ready(tree: Tree, tmp_path: Path) -> None:
    tree.python.unlink()
    tree.python.symlink_to(tmp_path / "removed" / "python3.12")

    assert evaluator_ready() is False


def test_a_directory_in_place_of_a_file_is_not_ready(tree: Tree) -> None:
    tree.validation_csv.unlink()
    tree.validation_csv.mkdir()

    assert evaluator_ready() is False


def _rewrite(tree: Tree, **update: Any) -> None:
    recorded = manifest.load_manifest(tree.manifest)
    manifest.write_manifest(recorded.model_copy(update=update), tree.manifest)


def _without_database_files(tree: Tree) -> None:
    _rewrite(tree, database_files=None)


def _one_database_file_unrecorded(tree: Tree) -> None:
    files = manifest.load_manifest(tree.manifest).database_files or {}
    _rewrite(tree, database_files={k: v for k, v in files.items() if not k.startswith("flights/")})


def _validation_csv_unrecorded(tree: Tree) -> None:
    dataset = manifest.load_manifest(tree.manifest).dataset
    files = {k: v for k, v in dataset.files.items() if k != manifest.VALIDATION_CSV}
    _rewrite(tree, dataset=dataset.model_copy(update={"files": files}))


def _not_json(tree: Tree) -> None:
    tree.manifest.write_text("{not json\n")


def _not_a_manifest(tree: Tree) -> None:
    tree.manifest.write_text('{"schema_version": 1}\n')


MANIFEST_PROBLEMS: dict[str, Callable[[Tree], None]] = {
    "no database_files": _without_database_files,
    "one database file unrecorded": _one_database_file_unrecorded,
    "validation.csv unrecorded": _validation_csv_unrecorded,
    "not JSON": _not_json,
    "not a manifest": _not_a_manifest,
}


@pytest.mark.parametrize("problem", MANIFEST_PROBLEMS)
def test_a_manifest_that_does_not_record_everything_is_not_ready(tree: Tree, problem: str) -> None:
    MANIFEST_PROBLEMS[problem](tree)

    assert evaluator_ready() is False


@pytest.mark.parametrize("value", ["relative/data", "/nowhere/at/all", ""])
def test_an_invalid_data_root_is_not_ready_and_does_not_raise(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", value)

    assert evaluator_ready() is False


@pytest.mark.parametrize("value", ["fast", "FAKE", ""])
def test_a_bridge_mode_bridge_from_env_refuses_is_not_ready(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TRIPARTITE_EVAL_BRIDGE", value)

    assert evaluator_ready() is False


# --- the real tree -------------------------------------------------------------------------


@pytest.mark.local
def test_the_real_tree_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Needs ``make setup`` (evalenv) and ``make data`` (the data and the unpacked database)."""
    monkeypatch.delenv("TRIPARTITE_EVAL_BRIDGE", raising=False)
    monkeypatch.delenv("TRIPARTITE_DATA_DIR", raising=False)

    assert evaluator_ready() is True
