"""``tripartite run start --resume <run_id>`` (ARCHITECTURE.md D7 §Resume, Q10).

A run that did not finish can be resumed: one that ``failed`` or was ``interrupted``, or one
still marked ``running`` because its process died (the model lock proves no process is running
it now). A ``succeeded`` run is final and is never touched; ``queued`` belongs to the API.

Resume re-uses the run's own stored config. Re-hashing it must give the run's ``config_hash``, and
today's stack pins, prompt, parser and calibrated post-check mode must equal the run's, because
the stack is not part of ``config_hash`` (``run.open_run`` checks them under the lock). Then:

1. ``repair_tail`` cuts a half-written last line off ``events.jsonl`` (its bytes go to
   ``events.corrupt-<ts>.txt``), and the count lands in the manifest as ``repaired_tail_bytes``;
   a bad line anywhere else is a hard ``RunLogError``;
2. a new ``run_start`` is appended with ``resumed_from`` set to the same run id, and the manifest
   says ``running`` with ``resumed: true``;
3. after a fresh warm-up, only the pairs without a ``query_result`` are run, into the same log.
"""

from typing import Final

from pydantic import ValidationError

from tripartite.config import RunConfig, config_hash
from tripartite.pipeline.run import (
    ResumeError,
    ResumeState,
    RunDeps,
    RunOutcome,
    RunSession,
    execute,
    open_run,
    read_manifest,
)
from tripartite.runlog.schema import validate_run_id

__all__ = ["RESUMABLE", "ResumeError", "open_resume", "resume_run"]

RESUMABLE: Final = frozenset({"failed", "interrupted", "running"})


def open_resume(run_id: str, deps: RunDeps) -> RunSession:
    """Check that ``run_id`` can be resumed and reopen it (everything before the warm-up)."""
    try:
        validate_run_id(run_id)
    except ValueError:
        raise ResumeError(f"{run_id!r} is not a run id") from None
    run_dir = deps.runs_dir / run_id
    try:
        manifest = read_manifest(run_dir)
    except FileNotFoundError:
        raise ResumeError(f"no run {run_id} in {deps.runs_dir}") from None
    if manifest.status not in RESUMABLE:
        raise ResumeError(
            f"run {run_id} is {manifest.status}; only a failed, interrupted or stale running "
            "run can be resumed"
        )
    stored = manifest.run_start.config
    if config_hash(stored) != manifest.run_start.config_hash:
        raise ResumeError(
            f"run {run_id}: its stored config hashes to {config_hash(stored)}, not its "
            f"config_hash {manifest.run_start.config_hash}"
        )
    try:
        config = RunConfig.model_validate(stored)
    except ValidationError as exc:
        raise ResumeError(f"run {run_id}: its stored config does not validate: {exc}") from None
    return open_run(config, deps, resume=ResumeState(run_dir, manifest))


def resume_run(run_id: str, deps: RunDeps | None = None) -> RunOutcome:
    """Resume ``run_id`` and run it to its end."""
    deps = deps or RunDeps()
    return execute(open_resume(run_id, deps))
