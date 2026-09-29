"""``runs/.model.lock``: one model call at a time, system-wide (ARCHITECTURE.md D4 §Concurrency).

Every process that calls the model holds this file lock for as long as it does: a CLI run from
before its warm-up to its ``run_end``, and each API job (D8). The lock is never waited for: a
second caller fails at once with ``ModelLockHeldError``, which the API maps to 409. The lock
file and its path are shared with the api session by contract (D9 §Shared files, item 5).
"""

from pathlib import Path

from filelock import FileLock, Timeout

from tripartite.config import MODEL_LOCK_PATH


class ModelLockHeldError(RuntimeError):
    """Another process holds ``runs/.model.lock``: it is calling the model now."""


def acquire_model_lock(path: Path = MODEL_LOCK_PATH) -> FileLock:
    """Take the model lock without waiting, or raise ``ModelLockHeldError``. The caller releases
    it with ``release()``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path, timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise ModelLockHeldError(
            f"{path} is held by another process that is calling the model"
        ) from None
    return lock
