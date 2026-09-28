"""scripts/vendor_check.py (ARCHITECTURE.md D5, D9 §Shared files, item 4), in throwaway repos.

Each test builds a small vendored tree in a fresh git repository in ``tmp_path``, writes a
matching ``VENDOR.lock``, and runs the real script there. Only git-tracked files are checked.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vendor_check.py"
COMMIT = "e52c87f4ac348a3410c46dc3553c519db5ec5e23"
UPSTREAM = {"commit": COMMIT, "repo": "https://github.com/OSU-NLP-Group/TravelPlanner"}
FILES = {
    "LICENSE": b"MIT License\n",
    "evaluation/eval.py": b"print('upstream')\n",
    "tools/__init__.py": b"",
    "database/README.md": b"# schema\n",
    "postprocess/example_evaluation.jsonl": b'{"idx": 1, "plan": null}\n',
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _entry(data: bytes) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "git_blob": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _write_lock(repo: Path, files: dict[str, dict[str, Any]], **overrides: Any) -> None:
    lock = {"schema_version": 1, "upstream": UPSTREAM, "files": files, **overrides}
    (repo / "vendor/travelplanner/VENDOR.lock").write_text(json.dumps(lock, indent=2))


def _run(repo: Path) -> tuple[int, list[str]]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout.splitlines()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository with a vendored tree, a matching lock, and everything tracked."""
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "repo"
    vendor = path / "vendor/travelplanner"
    for name, data in FILES.items():
        (vendor / name).parent.mkdir(parents=True, exist_ok=True)
        (vendor / name).write_bytes(data)
    (vendor / "VENDOR.md").write_text("# provenance\n")
    _git(path.parent, "init", "--quiet", str(path))
    _write_lock(path, {name: _entry(data) for name, data in FILES.items()})
    _git(path, "add", "vendor")
    return path


def test_a_matching_tree_passes(repo: Path) -> None:
    code, lines = _run(repo)

    assert code == 0, lines
    assert lines == [f"vendor check: OK (5 tracked files match VENDOR.lock at {COMMIT})"]


def test_untracked_ignored_database_files_are_outside_the_check(repo: Path) -> None:
    (repo / ".gitignore").write_text("vendor/travelplanner/database/*\n")
    database = repo / "vendor/travelplanner/database"
    (database / "flights").mkdir()
    (database / "flights/clean_Flights_2022.csv").write_text("unpacked, never tracked\n")
    (database / ".unpack-tmp").mkdir()
    (database / ".unpack-tmp/x").write_text("x")

    assert _run(repo)[0] == 0


def test_a_modified_file_fails_with_expected_and_actual(repo: Path) -> None:
    (repo / "vendor/travelplanner/evaluation/eval.py").write_bytes(b"print('edited')\n")

    code, lines = _run(repo)

    assert code == 1
    assert lines[0] == "vendor check: FAILED (ARCHITECTURE.md D5, D9)"
    problems = [line.strip() for line in lines[1:]]
    assert all(p.startswith("vendor/travelplanner/evaluation/eval.py: expected ") for p in problems)
    assert any("expected 18 bytes, found 16" in p for p in problems)
    assert any(p.split(": ", 1)[1].startswith("expected sha256 ") for p in problems)
    assert any(p.split(": ", 1)[1].startswith("expected git blob ") for p in problems)


def test_a_tracked_file_missing_from_the_lock_fails(repo: Path) -> None:
    (repo / "vendor/travelplanner/utils").mkdir()
    (repo / "vendor/travelplanner/utils/func.py").write_text("import gradio\n")
    _git(repo, "add", "vendor")

    code, lines = _run(repo)

    assert code == 1
    assert "  vendor/travelplanner/utils/func.py: tracked but not in VENDOR.lock" in lines


def test_a_lock_entry_that_is_not_tracked_fails(repo: Path) -> None:
    _git(repo, "rm", "--cached", "--quiet", "vendor/travelplanner/LICENSE")

    code, lines = _run(repo)

    assert code == 1
    assert "  vendor/travelplanner/LICENSE: in VENDOR.lock but not tracked by git" in lines


def test_a_deleted_file_fails(repo: Path) -> None:
    (repo / "vendor/travelplanner/LICENSE").unlink()

    code, lines = _run(repo)

    assert code == 1
    assert "  vendor/travelplanner/LICENSE: not a regular file" in lines


def test_a_symlink_fails(repo: Path) -> None:
    target = repo / "vendor/travelplanner/LICENSE"
    target.unlink()
    target.symlink_to("README.md")
    _git(repo, "add", "vendor")

    code, lines = _run(repo)

    assert code == 1
    assert "  vendor/travelplanner/LICENSE: not a regular file" in lines


@pytest.mark.parametrize(
    "path", ["database/test_ref_info.jsonl", "database/Validation_Ref_Info.JSONL", "db/x.CSV"]
)
def test_the_lock_never_lists_reference_information_or_csv(repo: Path, path: str) -> None:
    lock = json.loads((repo / "vendor/travelplanner/VENDOR.lock").read_text())
    _write_lock(repo, {**lock["files"], path: _entry(b"x")})

    code, lines = _run(repo)

    assert code == 1
    assert (
        f"  vendor/travelplanner/VENDOR.lock: {path}: a *ref_info* or *.csv path is never "
        "vendored (D5)" in lines
    )


def test_a_tracked_reference_file_anywhere_under_vendor_fails(repo: Path) -> None:
    (repo / "vendor/other").mkdir()
    (repo / "vendor/other/train_ref_info.jsonl").write_text("{}\n")
    _git(repo, "add", "vendor")

    code, lines = _run(repo)

    assert code == 1
    assert (
        "  vendor/other/train_ref_info.jsonl: a *ref_info* or *.csv file is committed under "
        "vendor/ (D5, §8)" in lines
    )


def test_a_path_outside_the_d5_list_fails(repo: Path) -> None:
    data = b"print('agent')\n"
    (repo / "vendor/travelplanner/agents").mkdir()
    (repo / "vendor/travelplanner/agents/tool_agents.py").write_bytes(data)
    lock = json.loads((repo / "vendor/travelplanner/VENDOR.lock").read_text())
    _write_lock(repo, {**lock["files"], "agents/tool_agents.py": _entry(data)})
    _git(repo, "add", "vendor")

    code, lines = _run(repo)

    assert code == 1
    assert (
        "  vendor/travelplanner/VENDOR.lock: agents/tool_agents.py: outside D5's vendored path "
        "list" in lines
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"upstream": {**UPSTREAM, "commit": "0" * 40}}, "upstream is"),
        ({"upstream": {**UPSTREAM, "repo": "https://example.com/fork"}}, "upstream is"),
        ({"schema_version": 2}, "schema_version is 2, expected 1"),
        ({"files": {}}, "files must be a non-empty object"),
        ({"files": {"LICENSE": {"bytes": 1}}}, "LICENSE: entry must be"),
        ({"files": {"../LICENSE": _entry(b"x")}}, "../LICENSE: not a normalized relative path"),
        ({"files": {"VENDOR.md": _entry(b"x")}}, "VENDOR.md: a local file"),
    ],
)
def test_an_invalid_lock_fails(repo: Path, override: dict[str, Any], message: str) -> None:
    lock = json.loads((repo / "vendor/travelplanner/VENDOR.lock").read_text())
    _write_lock(repo, **{"files": lock["files"], **override})

    code, lines = _run(repo)

    assert code == 1
    assert any(message in line for line in lines), lines


def test_a_missing_lock_fails(repo: Path) -> None:
    (repo / "vendor/travelplanner/VENDOR.lock").unlink()

    code, lines = _run(repo)

    assert code == 1
    assert lines[1].startswith("  vendor/travelplanner/VENDOR.lock: cannot read: ")
