"""What ``open_run`` refuses before anything exists (ARCHITECTURE.md D4 §Fake mode and data, D9
§M5 operations; FU-27, FU-29).

- **FU-27**: fake mode is synthetic-data-only. ``TRIPARTITE_DATA_DIR`` must name a data root
  other than ``<repo>/data``; the guard raises before any loader runs, so the tests that point
  the variable at ``<repo>/data`` never read it.
- **FU-29**: a full run (batch, all 180 queries) refuses a dirty working tree unless
  ``allow_dirty`` is passed, and resumes only at the commit that started it. Subset runs are
  unaffected.
"""

import json
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from filelock import FileLock

from tests.fixtures.model.run_deps import fake_deps, fixed_env, scripted_deps, write_config
from tripartite.config import SMOKE_CONFIG_PATH, StackConfig, load_run_config
from tripartite.data.manifest import DATA_DIR, N_VALIDATION
from tripartite.data.planner_inputs import query_id_for
from tripartite.llm.errors import CalibrationMissingError, FakeModeRealDataError
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult
from tripartite.pipeline.resume import ResumeError, resume_run
from tripartite.pipeline.run import (
    DirtyTreeError,
    RunDeps,
    RunOutcome,
    close_run,
    open_run,
    start_run,
)
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import RunStartEvent

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def small(tmp_path: Path) -> Path:
    return write_config(tmp_path / "small.yaml", queries=["val-001", "val-002"], seeds=[0])


def full(tmp_path: Path) -> Path:
    return write_config(tmp_path / "full.yaml", queries="all", seeds=[0])


def deps_at(tmp_path: Path, *, dirty: bool = False, commit: str = COMMIT_A, **more: Any) -> RunDeps:
    return fake_deps(
        tmp_path, env_probe=partial(fixed_env, git_dirty=dirty, git_commit=commit), **more
    )


def assert_nothing_started(deps: RunDeps) -> None:
    """No run directory, no request, and the model lock is free."""
    runs = [p.name for p in deps.runs_dir.iterdir()] if deps.runs_dir.exists() else []
    assert [name for name in runs if name != ".model.lock"] == []
    assert isinstance(deps.client, FakeClient)
    assert deps.client.requests == []
    deps.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(deps.lock_path, timeout=0):
        pass


def run_starts(run_dir: Path) -> list[dict[str, Any]]:
    events = read_events(run_dir / "events.jsonl")
    return [e.model_dump(mode="json") for e in events if isinstance(e, RunStartEvent)]


def manifest_run_start(run_dir: Path) -> dict[str, Any]:
    data = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    start = data["run_start"]
    assert isinstance(start, dict)
    return start


# --- FU-27: fake mode is synthetic-data-only ---------------------------------------------------


def test_fake_mode_refuses_when_the_data_variable_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")
    deps = fake_deps(tmp_path)

    with pytest.raises(FakeModeRealDataError, match="TRIPARTITE_DATA_DIR"):
        start_run(small(tmp_path), deps)
    assert_nothing_started(deps)


def test_fake_mode_refuses_the_repository_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(DATA_DIR))
    deps = fake_deps(tmp_path)

    with pytest.raises(FakeModeRealDataError, match="TRIPARTITE_DATA_DIR"):
        start_run(small(tmp_path), deps)
    assert_nothing_started(deps)


def test_fake_mode_refuses_a_symlink_to_the_repository_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = tmp_path / "data-link"
    link.symlink_to(DATA_DIR, target_is_directory=True)
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(link))
    deps = fake_deps(tmp_path)

    with pytest.raises(FakeModeRealDataError, match="TRIPARTITE_DATA_DIR"):
        start_run(small(tmp_path), deps)
    assert_nothing_started(deps)


def test_fake_mode_runs_on_a_synthetic_data_root(tmp_path: Path) -> None:
    """The autouse fixture has set the variable to a temporary synthetic set."""
    outcome = start_run(small(tmp_path), fake_deps(tmp_path))

    assert outcome.status == "succeeded", outcome.error


def test_a_fake_resume_is_refused_on_the_real_data_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = interrupted(tmp_path, small(tmp_path), deps_at(tmp_path / "a"))
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")

    with pytest.raises(FakeModeRealDataError, match="TRIPARTITE_DATA_DIR"):
        resume_run(first.run_id, deps_at(tmp_path / "b", runs_dir=first.run_dir.parent))


def test_the_real_model_is_not_subject_to_the_guard(
    tmp_path: Path, stack: StackConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real mode with the variable unset is not refused by FU-27. With no calibration it stops
    at ``CalibrationMissingError``, before any loader could read the data."""
    monkeypatch.delenv("TRIPARTITE_LLM")
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")
    scripted = scripted_deps(tmp_path, stack)
    scripted.deps.calibration_path = tmp_path / "no-calibration.json"

    with pytest.raises(CalibrationMissingError, match="missing"):
        start_run(small(tmp_path), scripted.deps)
    assert scripted.server.requests == []
    assert not scripted.deps.runs_dir.exists()


# --- FU-29: a full run needs a clean tree -------------------------------------------------------


@pytest.mark.parametrize(
    "queries",
    ["all", [query_id_for(i) for i in range(1, N_VALIDATION + 1)]],
    ids=["all", "all-180-listed"],
)
def test_a_full_run_refuses_a_dirty_tree(tmp_path: Path, queries: str | list[str]) -> None:
    config = write_config(tmp_path / "full.yaml", queries=queries, seeds=[0])
    deps = deps_at(tmp_path, dirty=True)

    with pytest.raises(DirtyTreeError, match="--allow-dirty"):
        start_run(config, deps)
    assert_nothing_started(deps)


def test_allow_dirty_starts_the_run_and_is_recorded(tmp_path: Path) -> None:
    deps = deps_at(tmp_path, dirty=True)

    session = open_run(load_run_config(full(tmp_path)), deps, allow_dirty=True)
    close_run(session)

    (start,) = run_starts(session.run_dir)
    assert start["allow_dirty"] is True
    assert start["env"]["git_dirty"] is True
    assert manifest_run_start(session.run_dir)["allow_dirty"] is True


def test_a_clean_full_run_starts_and_records_no_flag(tmp_path: Path) -> None:
    session = open_run(load_run_config(full(tmp_path)), deps_at(tmp_path))
    close_run(session)

    (start,) = run_starts(session.run_dir)
    assert "allow_dirty" not in start
    assert "allow_dirty" not in manifest_run_start(session.run_dir)


def test_the_flag_is_recorded_whenever_it_is_passed(tmp_path: Path) -> None:
    """Even on a clean tree and a subset run; ``git_dirty`` beside it says what the tree was."""
    session = open_run(load_run_config(small(tmp_path)), deps_at(tmp_path), allow_dirty=True)
    close_run(session)

    (start,) = run_starts(session.run_dir)
    assert start["allow_dirty"] is True
    assert start["env"]["git_dirty"] is False


def test_a_subset_run_is_unaffected_by_a_dirty_tree(tmp_path: Path) -> None:
    outcome = start_run(SMOKE_CONFIG_PATH, deps_at(tmp_path, dirty=True))

    assert outcome.status == "succeeded", outcome.error
    (start,) = run_starts(outcome.run_dir)
    assert "allow_dirty" not in start


# --- FU-29 and resume ---------------------------------------------------------------------------


class Interrupting:
    """A fake client that is interrupted (Ctrl-C) on its second planner call."""

    def __init__(self) -> None:
        self.inner = FakeClient(FakeTokenizer())
        self.planner_calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if "Reply with OK." not in request.prompt:
            self.planner_calls += 1
            if self.planner_calls == 2:
                raise KeyboardInterrupt
        return self.inner.generate(request)


def interrupted(tmp_path: Path, config: Path, deps: RunDeps, **kwargs: Any) -> RunOutcome:
    deps.client = Interrupting()
    outcome = start_run(config, deps, **kwargs)
    assert outcome.status == "interrupted", outcome.error
    return outcome


def snapshot(run_dir: Path) -> tuple[bytes, bytes]:
    return (run_dir / "events.jsonl").read_bytes(), (run_dir / "manifest.json").read_bytes()


def test_a_full_run_resumes_at_the_same_commit(tmp_path: Path) -> None:
    first = interrupted(tmp_path, full(tmp_path), deps_at(tmp_path / "a"))

    outcome = resume_run(first.run_id, deps_at(tmp_path / "b", runs_dir=first.run_dir.parent))

    assert outcome.status == "succeeded", outcome.error
    assert [s["resumed_from"] for s in run_starts(first.run_dir)] == [None, first.run_id]


@pytest.mark.parametrize("allow_dirty", [False, True], ids=["plain", "allow-dirty"])
def test_a_full_run_does_not_resume_at_another_commit(tmp_path: Path, allow_dirty: bool) -> None:
    """``--allow-dirty`` does not override it: the fix is to check out the run's commit."""
    first = interrupted(tmp_path, full(tmp_path), deps_at(tmp_path / "a"))
    before = snapshot(first.run_dir)
    deps = deps_at(tmp_path / "b", commit=COMMIT_B, runs_dir=first.run_dir.parent)

    with pytest.raises(ResumeError) as caught:
        resume_run(first.run_id, deps, allow_dirty=allow_dirty)

    assert COMMIT_A in str(caught.value)
    assert COMMIT_B in str(caught.value)
    assert snapshot(first.run_dir) == before
    with FileLock(deps.lock_path, timeout=0):
        pass


def test_a_subset_run_resumes_across_commits(tmp_path: Path) -> None:
    first = interrupted(tmp_path, SMOKE_CONFIG_PATH, deps_at(tmp_path / "a"))

    outcome = resume_run(
        first.run_id,
        deps_at(tmp_path / "b", commit=COMMIT_B, dirty=True, runs_dir=first.run_dir.parent),
    )

    assert outcome.status == "succeeded", outcome.error
    commits = [s["env"]["git_commit"] for s in run_starts(first.run_dir)]
    assert commits == [COMMIT_A, COMMIT_B]


def test_a_full_run_does_not_resume_from_a_dirty_tree(tmp_path: Path) -> None:
    first = interrupted(tmp_path, full(tmp_path), deps_at(tmp_path / "a"))
    before = snapshot(first.run_dir)

    with pytest.raises(DirtyTreeError, match="--allow-dirty"):
        resume_run(first.run_id, deps_at(tmp_path / "b", dirty=True, runs_dir=first.run_dir.parent))
    assert snapshot(first.run_dir) == before


def test_allow_dirty_resumes_a_full_run_and_is_recorded(tmp_path: Path) -> None:
    first = interrupted(tmp_path, full(tmp_path), deps_at(tmp_path / "a"))

    outcome = resume_run(
        first.run_id,
        deps_at(tmp_path / "b", dirty=True, runs_dir=first.run_dir.parent),
        allow_dirty=True,
    )

    assert outcome.status == "succeeded", outcome.error
    starts = run_starts(first.run_dir)
    assert ["allow_dirty" in s for s in starts] == [False, True]
    assert manifest_run_start(first.run_dir)["allow_dirty"] is True


def test_allow_dirty_stays_on_a_run_once_a_session_used_it(tmp_path: Path) -> None:
    """Resume replaces the manifest's ``run_start``, so a later clean session keeps the flag."""
    first = interrupted(
        tmp_path, full(tmp_path), deps_at(tmp_path / "a", dirty=True), allow_dirty=True
    )

    outcome = resume_run(first.run_id, deps_at(tmp_path / "b", runs_dir=first.run_dir.parent))

    assert outcome.status == "succeeded", outcome.error
    assert [s.get("allow_dirty") for s in run_starts(first.run_dir)] == [True, True]
    assert manifest_run_start(first.run_dir)["allow_dirty"] is True
