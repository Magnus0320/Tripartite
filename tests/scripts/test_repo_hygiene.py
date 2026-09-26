"""scripts/ci/repo_hygiene.py (ARCHITECTURE.md §8), run against throwaway git repositories.

Each test builds a fresh repository in ``tmp_path`` and runs the real script in it. Every
key-shaped sample is assembled at runtime, so this file contains none and the hygiene check
passes on it (FU-10, AQ8).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "repo_hygiene.py"
GITIGNORE = ROOT / ".gitignore"
FORCE_ADDED = "tracked although .gitignore ignores it"
RUN_ID = "20260923T120000Z-batch-abababab-1a2b"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _write(repo: Path, path: str, content: bytes = b"x\n") -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(content)


def _check(repo: Path) -> dict[str, str]:
    """Run the hygiene check in ``repo`` and return its violations as ``{path: reasons}``."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True, check=False
    )
    reasons: dict[str, list[str]] = {}
    for line in result.stdout.splitlines()[1:]:
        path, reason = line.strip().split(": ", 1)
        reasons.setdefault(path, []).append(reason)
    assert result.returncode == (1 if reasons else 0), result.stdout + result.stderr
    return {path: "; ".join(found) for path, found in reasons.items()}


def _key_shaped() -> dict[str, str]:
    """One key-shaped sample per §8 prefix. Written as literals, they would fail the check."""
    return {
        "sk-": "sk-" + "a1B2" * 6,
        "hf_": "hf_" + "Ab3" * 11,
        "ghp_": "ghp_" + "x9" * 18,
        "AKIA": "AKIA" + "Q7" * 8,
    }


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty git repository with no .gitignore, isolated from any user or system config."""
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "--quiet")
    return path


@pytest.fixture
def project_repo(repo: Path) -> Path:
    """``repo`` with this project's .gitignore."""
    shutil.copyfile(GITIGNORE, repo / ".gitignore")
    return repo


# --- path rules, enforced by the script itself (no .gitignore) ------------------------------

PATH_CASES = [
    # §8.1 dataset files: only paths under the root data/ directory (v0.6, FQ1)
    ("data/raw/validation.csv", "§8.1"),
    ("data/x.csv", "§8.1"),
    ("data/MANIFEST.json", None),
    ("data", None),
    # §8.2 test-split artefacts: the file name only, data extensions only, in any case
    ("test.csv", "§8.2"),
    ("tests/fixtures/test_ref_info.jsonl", "§8.2"),
    ("web/public/old_test_ref_info_v2.json", "§8.2"),
    ("archive/test_ref_info.parquet", "§8.2"),
    ("archive/test_ref_info.jsonl.gz", "§8.2"),
    ("notes/test_ref_info.txt", "§8.2"),
    ("TEST.CSV", "§8.2"),
    ("fixtures/Test_Ref_Info.JSONL", "§8.2"),
    ("fixtures/My_TEST_ref_INFO.Csv", "§8.2"),
    ("tests/data/test_ref_info_alignment.py", None),
    ("fixtures/test_ref_info.md", None),
    ("fixtures/test_split/ref_info.jsonl", None),
    ("test_ref_info/summary.json", None),
    # §8.3 the sandbox database
    ("vendor/travelplanner/database/flights/clean_Flights_2022.csv", "§8.3"),
    ("vendor/travelplanner/database/README.md", None),
    # §8.4 run output, anchored at the repository root
    (f"runs/{RUN_ID}/events.jsonl", "§8.4"),
    ("mlruns/0/meta.yaml", "§8.4"),
    ("web/src/runs/RunList.tsx", None),
    ("src/tripartite/mlruns/__init__.py", None),
    # §8.5 secrets and local agent state
    (".env", "§8.5"),
    ("web/.env.local", "§8.5"),
    (".claude/settings.local.json", "§8.5"),
    (".claude/worktrees/fu-10/README.md", "§8.5"),
    (".claude/settings.json", None),
]


@pytest.mark.parametrize(("path", "rule"), PATH_CASES, ids=[path for path, _ in PATH_CASES])
def test_path_rules(repo: Path, path: str, rule: str | None) -> None:
    _write(repo, path)
    violations = _check(repo)
    if rule is None:
        assert violations == {}
    else:
        assert list(violations) == [path]
        assert rule in violations[path]


def test_tracked_and_untracked_files_are_both_checked(repo: Path) -> None:
    _write(repo, "tracked/test.csv")
    _git(repo, "add", "tracked/test.csv")
    _write(repo, "untracked/test.csv")
    assert set(_check(repo)) == {"tracked/test.csv", "untracked/test.csv"}


# --- together with this project's .gitignore ------------------------------------------------

FORCE_ADDED_CASES = [
    ("debug.log", None),
    ("data/raw/validation.csv", "§8.1"),
    ("vendor/travelplanner/database/flights/clean_Flights_2022.csv", "§8.3"),
    (f"runs/{RUN_ID}/events.jsonl", "§8.4"),
    ("mlruns/0/meta.yaml", "§8.4"),
    (".env", "§8.5"),
    (".claude/settings.local.json", "§8.5"),
    (".claude/worktrees/fu-10/README.md", "§8.5"),
]


@pytest.mark.parametrize(
    ("path", "rule"), FORCE_ADDED_CASES, ids=[path for path, _ in FORCE_ADDED_CASES]
)
def test_ignored_files_are_refused_once_force_added(
    project_repo: Path, path: str, rule: str | None
) -> None:
    _write(project_repo, path)
    assert _check(project_repo) == {}

    _git(project_repo, "add", "--force", path)
    violations = _check(project_repo)

    assert list(violations) == [path]
    assert FORCE_ADDED in violations[path]
    if rule is None:
        assert violations[path] == FORCE_ADDED
    else:
        assert rule in violations[path]


def test_runs_and_mlruns_are_ignored_only_at_the_root(project_repo: Path) -> None:
    nested = ["src/tripartite/mlruns/__init__.py", "web/src/runs/RunList.tsx"]
    for path in [*nested, f"runs/{RUN_ID}/events.jsonl", "mlruns/0/meta.yaml"]:
        _write(project_repo, path)

    assert _check(project_repo) == {}
    visible = _git(project_repo, "ls-files", "--others", "--exclude-standard").splitlines()
    assert sorted(visible) == [".gitignore", *nested]


def test_macos_archive_clutter_is_ignored(project_repo: Path) -> None:
    for path in [".DS_Store", "__MACOSX/database/._clean_Flights_2022.csv", "docs/._notes.md"]:
        _write(project_repo, path)

    assert _check(project_repo) == {}
    visible = _git(project_repo, "ls-files", "--others", "--exclude-standard").splitlines()
    assert visible == [".gitignore"]


# --- content rules ----------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["sk-", "hf_", "ghp_", "AKIA"])
def test_key_shaped_strings_are_refused(repo: Path, prefix: str) -> None:
    _write(repo, "src/settings.py", f'TOKEN = "{_key_shaped()[prefix]}"\n'.encode())
    assert _check(repo) == {"src/settings.py": f"key-shaped string ({prefix}...) (§8.5)"}


@pytest.mark.parametrize(
    "text", ["sk-" + "a" * 19, "task-" + "a" * 30], ids=["too-short", "inside-a-word"]
)
def test_strings_that_only_resemble_keys_are_allowed(repo: Path, text: str) -> None:
    _write(repo, "src/settings.py", f'TOKEN = "{text}"\n'.encode())
    assert _check(repo) == {}


def test_this_file_passes_the_check(repo: Path) -> None:
    shutil.copyfile(__file__, repo / "test_repo_hygiene.py")
    assert _check(repo) == {}


def test_files_over_2_mb_are_refused_except_lockfiles(repo: Path) -> None:
    too_big = b"\0" * 2_000_001
    for path in ["model.bin", "uv.lock", "evalenv/uv.lock", "web/package-lock.json"]:
        _write(repo, path, too_big)
    _write(repo, "limit.bin", b"\0" * 2_000_000)

    violations = _check(repo)

    assert list(violations) == ["model.bin"]
    assert "larger than 2 MB (2000001 bytes)" in violations["model.bin"]
