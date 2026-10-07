"""The in-process job runner and the start-up sweep (ARCHITECTURE.md D4 §Concurrency, D7, D8).

**One job at a time, no queue.** ``JobRunner.submit`` starts one single run from
``configs/single.yaml`` with ``queries`` and ``seeds`` replaced, through the pipeline's own
``open_run`` and ``execute``, so an API run is the run ``tripartite run start`` would make.
The blocking work is in one thread per job:

1. ``open_run``: the checks, ``runs/.model.lock``, the run directory and its ``run_start``. An
   error here means no run exists: it is handed back to ``submit`` (``ModelLockHeldError`` → 409,
   anything else → 503).
2. The manifest becomes ``queued`` and ``submit`` returns the run id. ``open_run`` creates the
   run id, so the request cannot be answered earlier.
3. The manifest becomes ``running`` and ``execute`` does the warm-up, the pair, the scores and
   ``run_end``, and releases the lock in every case.

``open_run`` and ``execute`` share the thread because the model lock is a thread-local
``FileLock``: only the thread that took it can release it. The thread is a daemon thread, so a
model call that takes minutes never blocks the server's exit; the run it leaves ``running`` is
what the sweep is for.

**The sweep** (``sweep_stale_runs``, at start-up): a single run still ``queued`` or ``running``
when no process holds the model lock was cut off, so it gets a ``run_end`` event and becomes
``interrupted``. If the lock is held, some process is running a job right now and nothing is
swept. Batch runs and folders without a manifest are never touched. The API never repairs a log
(D7): when a stale run's ``events.jsonl`` cannot be read or appended to, only its manifest
changes, and the error says so.
"""

import asyncio
import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from tripartite.config import RUNS_DIR, SINGLE_CONFIG_PATH, RunConfig, load_run_config
from tripartite.pipeline.lock import ModelLockHeldError, acquire_model_lock
from tripartite.pipeline.metrics import load_run_log
from tripartite.pipeline.run import (
    EVENTS_FILE,
    MANIFEST_FILE,
    RunDeps,
    close_run,
    execute,
    open_run,
    read_manifest,
    write_manifest,
)
from tripartite.runlog.reader import RunLogError
from tripartite.runlog.schema import ErrorInfo, RunEnd, RunManifest
from tripartite.runlog.writer import RunLogWriter, utc_now

LOCK_FILE: Final = ".model.lock"
SSE_PING_S: Final = 15.0
"""D8: a ``: ping`` comment every 15 s."""
SSE_POLL_S: Final = 0.1
"""How often an event stream reads the manifest for a stage change."""
INTERRUPTED: Final = ErrorInfo(
    type="Interrupted", message="the API server stopped while this run was in progress"
)
NO_RUN_END: Final = (
    "; events.jsonl could not be read or appended to, so no run_end was written "
    "(tripartite run start --resume repairs it)"
)


@dataclass(frozen=True)
class ApiSettings:
    """Where the API keeps runs and how it starts them. The defaults are D8's; tests replace
    ``app.state.settings``."""

    runs_dir: Path = RUNS_DIR
    single_config_path: Path = SINGLE_CONFIG_PATH
    make_deps: Callable[[], RunDeps] | None = None
    """Default: ``RunDeps`` on ``runs_dir``, with the client, tokenizer and bridge the
    environment selects."""
    sse_ping_s: float = SSE_PING_S
    sse_poll_s: float = SSE_POLL_S

    @property
    def lock_path(self) -> Path:
        return self.runs_dir / LOCK_FILE

    def run_deps(self) -> RunDeps:
        if self.make_deps is not None:
            return self.make_deps()
        return RunDeps(runs_dir=self.runs_dir, lock_path=self.lock_path)


class JobActiveError(RuntimeError):
    """This server is already running a job (D8: at most one, and no queue)."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is in progress; one job runs at a time")
        self.run_id = run_id


def single_config(path: Path, query_id: str, seed: int) -> RunConfig:
    """``configs/single.yaml`` with its one query and one seed replaced (D8)."""
    data = load_run_config(path).model_dump(mode="json")
    return RunConfig.model_validate({**data, "queries": [query_id], "seeds": [seed]})


class JobRunner:
    """Runs at most one single run at a time, in a thread of its own."""

    def __init__(self, settings: ApiSettings) -> None:
        self._settings = settings
        self._submitting = asyncio.Lock()
        self._active: str | None = None

    @property
    def active_run_id(self) -> str | None:
        return self._active

    async def submit(self, query_id: str, seed: int) -> str:
        """Start a run and return its id once it exists on disk as ``queued``. Raises
        ``JobActiveError`` if a job is running, and whatever ``open_run`` raised if the run could
        not start (``ModelLockHeldError`` when another process holds the model lock)."""
        async with self._submitting:
            if self._active is not None:
                raise JobActiveError(self._active)
            config = single_config(self._settings.single_config_path, query_id, seed)
            loop = asyncio.get_running_loop()
            opened: asyncio.Future[str] = loop.create_future()
            threading.Thread(
                target=self._work, args=(config, loop, opened), daemon=True, name="tripartite-job"
            ).start()
            return await asyncio.shield(opened)

    def _work(
        self, config: RunConfig, loop: asyncio.AbstractEventLoop, opened: "asyncio.Future[str]"
    ) -> None:
        try:
            session = open_run(config, self._settings.run_deps())
            try:
                session.update(status="queued", stage="queued")
            except BaseException:
                close_run(session)
                raise
        except BaseException as exc:
            _call(loop, self._on_refused, opened, exc)
            return
        _call(loop, self._on_opened, opened, session.run_id)
        try:
            try:
                session.update(status="running", stage="generating")
            except BaseException:
                close_run(session)
                raise
            execute(session)
        finally:
            _call(loop, self._on_finished)

    def _on_opened(self, opened: "asyncio.Future[str]", run_id: str) -> None:
        self._active = run_id
        if not opened.done():
            opened.set_result(run_id)

    def _on_refused(self, opened: "asyncio.Future[str]", exc: BaseException) -> None:
        if not opened.done():
            opened.set_exception(exc)

    def _on_finished(self) -> None:
        self._active = None


def _call(loop: asyncio.AbstractEventLoop, callback: Callable[..., None], *args: Any) -> None:
    """Run ``callback`` on the server's loop, from the job thread. A loop that has closed means
    the server is exiting, and there is nobody left to tell."""
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(callback, *args)


# --- the start-up sweep --------------------------------------------------------------------------


def _append_run_end(run_dir: Path, manifest: RunManifest) -> None:
    events = run_dir / EVENTS_FILE
    view = load_run_log(events)
    start = manifest.run_start
    results = list(view.query_results.values())
    counts = {
        "queries": len(start.query_ids),
        "seeds": len(start.seeds),
        "pairs_total": len(start.query_ids) * len(start.seeds),
        "pairs_done": len(results),
        "delivered": sum(result.status == "delivered" for result in results),
        "llm_calls": view.llm_calls,
        "errors": view.errors,
    }
    with RunLogWriter(events, run_dir.name) as writer:
        writer.write(
            RunEnd(status="interrupted", counts=counts, metrics_path=None, error=INTERRUPTED)
        )


def _interrupt(run_dir: Path, manifest: RunManifest) -> None:
    error = INTERRUPTED
    try:
        _append_run_end(run_dir, manifest)
    except (RunLogError, OSError):
        error = ErrorInfo(type=INTERRUPTED.type, message=INTERRUPTED.message + NO_RUN_END)
    now = utc_now()
    changes = {"status": "interrupted", "updated_at": now, "finished_at": now, "error": error}
    write_manifest(run_dir, RunManifest.model_validate({**manifest.model_dump(), **changes}))


def sweep_stale_runs(settings: ApiSettings) -> list[str]:
    """Mark every stale single run ``interrupted`` (D8) and return their ids. Does nothing when
    there is no ``runs_dir``, or when the model lock is held."""
    if not settings.runs_dir.is_dir():
        return []
    try:
        lock = acquire_model_lock(settings.lock_path)
    except ModelLockHeldError:
        return []
    swept = []
    try:
        for path in sorted(settings.runs_dir.glob(f"*/{MANIFEST_FILE}")):
            try:
                manifest = read_manifest(path.parent)
            except (OSError, ValidationError):
                continue
            if manifest.run_start.kind == "single" and manifest.status in ("queued", "running"):
                _interrupt(path.parent, manifest)
                swept.append(path.parent.name)
    finally:
        lock.release()
    return swept
