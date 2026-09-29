"""``RunDeps`` for pipeline tests, and the guard that keeps them out of the repository (model).

- ``fake_deps``: fake mode as CI runs it. ``FakeClient`` records every request body, the
  ``FakeBridge`` evaluates, and nothing touches the network or a model.
- ``scripted_deps``: the real-model code path (``TRIPARTITE_LLM`` unset) against ``FakeOllama``
  behind ``httpx.MockTransport``, with the synthetic HF tokenizer and chat template, a tmp
  calibration report and a tmp server log. Calibration, the post-check, the stack check and the
  truncation scan all run as they do against the real server.

Every path is under ``tmp_path``. ``RepositoryGuard`` fails a test that changed a committed report
or anything under the repository's ``runs/`` other than the two shared files a real-model test
may create or append to: ``runs/.model.lock`` and ``runs/ollama-server.log``.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import yaml

from tests.fixtures.model.fake_ollama import FakeOllama
from tests.fixtures.model.reports import calibration_report, write_calibration_report
from tests.fixtures.model.synthetic_tokenizer import write_synthetic_tokenizer_dir
from tripartite.config import (
    MODEL_LOCK_PATH,
    REPO_ROOT,
    RUNS_DIR,
    SERVER_LOG_PATH,
    SMOKE_CONFIG_PATH,
    StackConfig,
)
from tripartite.evaluation.bridge_client import FakeBridge
from tripartite.llm.calibration import CALIBRATION_REPORT_PATH, Mode
from tripartite.llm.chat_template import load_chat_template
from tripartite.llm.context import CONTEXT_REPORT_PATH
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.tokenizer import load_tokenizer
from tripartite.pipeline.run import RunDeps
from tripartite.runlog.schema import EnvInfo

SHA: Final = "ab" * 32
PLAN_TEXT: Final = (
    "Day 1:\n"
    "Current City: from Aville to Synthville\n"
    "Transportation: Flight Number: F0000001, from Aville to Synthville\n"
    "Breakfast: -\n"
    "Attraction: Synth Museum, Synthville;\n"
    "Lunch: Cafe One, Synthville\n"
    "Dinner: Diner Two, Synthville\n"
    "Accommodation: Cozy Room, Synthville"
)
"""A hand-written one-day plan in the official format (not model output)."""


def write_config(
    path: Path,
    *,
    queries: str | Sequence[str] | None = None,
    seeds: Sequence[int] | None = None,
    base: Path = SMOKE_CONFIG_PATH,
    **generation: Any,
) -> Path:
    """``base`` (the smoke config) with other queries, seeds or generation options."""
    data = yaml.safe_load(base.read_text(encoding="utf-8"))
    data["run"]["name"] = "test"
    if queries is not None:
        data["queries"] = queries if isinstance(queries, str) else list(queries)
    if seeds is not None:
        data["seeds"] = list(seeds)
    data["generation"].update(generation)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def fixed_env(_stack: StackConfig) -> EnvInfo:
    return EnvInfo(
        python="3.12.13",
        uv_lock_sha256=SHA,
        evalenv_lock_sha256=SHA,
        git_commit="0" * 40,
        git_dirty=False,
        macos="26.0",
        chip="Apple M4 Pro",
        ollama_env={"OLLAMA_NUM_PARALLEL": "1"},
        iogpu_wired_limit_mb=0,
        gpu_recommended_max_working_set_bytes=None,
    )


class TickingClock:
    """UTC, one second later on every call, so run ids and rescore folders never collide."""

    def __init__(self, start: datetime = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def fake_deps(tmp_path: Path, **changes: Any) -> RunDeps:
    runs = tmp_path / "runs"
    deps: dict[str, Any] = {
        "runs_dir": runs,
        "lock_path": runs / ".model.lock",
        "calibration_path": tmp_path / "no-calibration.json",
        "server_log_path": tmp_path / "no-server.log",
        "client": FakeClient(FakeTokenizer()),
        "tokenizer": FakeTokenizer(),
        "bridge": FakeBridge(),
        "env_probe": fixed_env,
        "clock": TickingClock(),
        "sleep": lambda _s: None,
    }
    deps.update(changes)
    return RunDeps(**deps)


@dataclass
class Scripted:
    """The pieces of a scripted real-model run, for tests to inspect or change."""

    deps: RunDeps
    server: FakeOllama
    log: Path


def scripted_deps(
    tmp_path: Path,
    stack: StackConfig,
    *,
    mode: Mode = "total",
    reply: str = PLAN_TEXT,
    **server_changes: Any,
) -> Scripted:
    tokenizer_dir = write_synthetic_tokenizer_dir(tmp_path / "tokenizer", stack.tokenizer.revision)
    tokenizer = load_tokenizer(stack, tokenizer_dir)
    server = FakeOllama.for_stack(
        stack, tokenizer, mode=mode, reply=reply, reply_done_reason="stop", **server_changes
    )
    calibration = write_calibration_report(
        tmp_path / "token_calibration.json", calibration_report(stack, mode=mode)
    )
    log = tmp_path / "ollama-server.log"
    log.write_text('time=... level=INFO msg="server config"\n', encoding="utf-8")
    runs = tmp_path / "runs"
    deps = RunDeps(
        runs_dir=runs,
        lock_path=runs / ".model.lock",
        calibration_path=calibration,
        server_log_path=log,
        client=server.client(),
        tokenizer=tokenizer,
        chat=load_chat_template(stack, tokenizer_dir),
        bridge=FakeBridge(),
        env_probe=fixed_env,
        clock=TickingClock(),
        sleep=lambda _s: None,
    )
    return Scripted(deps, server, log)


# --- the repository guard ------------------------------------------------------------------------

EXEMPT: Final = frozenset({MODEL_LOCK_PATH, SERVER_LOG_PATH})
"""The two shared files a real-model (``local``) test may create or append to."""
COMMITTED_REPORTS: Final = (CONTEXT_REPORT_PATH, CALIBRATION_REPORT_PATH)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runs_state() -> dict[str, tuple[int, int]]:
    """Every path under the repository's ``runs/`` but the exempt ones: (size, mtime)."""
    if not RUNS_DIR.exists():
        return {}
    state = {}
    for path in RUNS_DIR.rglob("*"):
        if path in EXEMPT:
            continue
        stat = path.lstat()
        state[path.relative_to(REPO_ROOT).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return state


class RepositoryGuard:
    """Snapshot the committed reports and ``runs/`` before a test; ``check`` after it."""

    def __init__(self) -> None:
        self.reports = {path: _digest(path) for path in COMMITTED_REPORTS}
        self.runs = _runs_state()

    def check(self) -> list[str]:
        problems = [
            f"{path.relative_to(REPO_ROOT)} changed"
            for path, digest in self.reports.items()
            if _digest(path) != digest
        ]
        after = _runs_state()
        problems += [
            f"{name} appeared or changed under runs/"
            for name, state in after.items()
            if self.runs.get(name) != state
        ]
        problems += [f"{name} vanished from runs/" for name in self.runs if name not in after]
        return problems


GuardFactory = Callable[[], RepositoryGuard]
