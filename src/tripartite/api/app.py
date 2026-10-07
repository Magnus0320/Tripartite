"""The FastAPI app (ARCHITECTURE.md D8): ``uvicorn tripartite.api.app:app --host 127.0.0.1
--port 8000``, started by ``tripartite api serve`` (``make api``).

F1 serves ``GET /api/health`` and the query routes. Nothing here starts a run, takes
``runs/.model.lock`` or sends a generate request; runs and the job runner are F2. Importing
this module has no side effects, so ``tripartite api export-openapi`` needs no data.

The three health flags are their owners' functions (D8, FU-19): ``model_reachable`` and
``model_digest_ok`` from ``tripartite.llm.doctor`` (one ``GET`` each, at most 1.0 s, never a
model load) and ``evaluator_ready`` from ``tripartite.evaluation.readiness`` (``os.stat`` only).
None of them raises, and all three are ``True`` in the fake modes.
"""

from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI

from tripartite.api import routes_queries
from tripartite.api.schemas import Health
from tripartite.config import STACK_PATH
from tripartite.evaluation.readiness import evaluator_ready
from tripartite.llm.doctor import model_digest_ok, model_reachable

app = FastAPI(title="Tripartite API", version=version("tripartite"))
app.include_router(routes_queries.router)


def stack_path() -> Path:
    """The ``stack.yaml`` whose server and pinned digest the health flags check: the committed
    ``configs/stack.yaml``. A dependency, so that tests can point the route at another file."""
    return STACK_PATH


@app.get("/api/health")
def get_health(stack: Annotated[Path, Depends(stack_path)]) -> Health:
    """Liveness, plus whether the model and the evaluator are ready."""
    # A sync def, so FastAPI runs it in its thread pool: the two model checks block for up to
    # 1.0 s each. They get the path, not a loaded config, so that the model session's loader
    # runs inside that bound and a missing or invalid stack.yaml is False, never a 500.
    return Health(
        status="ok",
        model_reachable=model_reachable(stack),
        model_digest_ok=model_digest_ok(stack),
        evaluator_ready=evaluator_ready(),
    )
