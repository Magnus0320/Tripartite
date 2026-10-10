"""The FastAPI app (ARCHITECTURE.md D8): ``uvicorn tripartite.api.app:app --host 127.0.0.1
--port 8000``, started by ``tripartite api serve`` (``make api``).

It serves ``GET /api/health``, the query routes and the run routes. Importing this module has
no side effects, so ``tripartite api export-openapi`` needs no data. When the server starts, the
lifespan marks every stale single run ``interrupted`` and creates the one job runner (D8;
``jobs.py``). ``app.state.settings`` says where runs live; tests replace it.

The three health flags are their owners' functions (D8, FU-19): ``model_reachable`` and
``model_digest_ok`` from ``tripartite.llm.doctor`` (one ``GET`` each, at most 1.0 s, never a
model load) and ``evaluator_ready`` from ``tripartite.evaluation.readiness`` (``os.stat`` only).
None of them raises, and all three are ``True`` in the fake modes. The two model checks run
side by side, so a server that hangs costs one timeout, not two.
"""

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI

from tripartite.api import routes_queries, routes_runs
from tripartite.api.jobs import ApiSettings, JobRunner, sweep_stale_runs
from tripartite.api.schemas import Health, StageEvent, StreamError
from tripartite.config import STACK_PATH
from tripartite.evaluation.readiness import evaluator_ready
from tripartite.llm.doctor import model_digest_ok, model_reachable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: ApiSettings = app.state.settings
    await asyncio.to_thread(sweep_stale_runs, settings)
    app.state.jobs = JobRunner(settings)
    yield


class _Api(FastAPI):
    """FastAPI, with the two models of the event stream in the contract. No route returns them
    as a JSON body, so FastAPI would leave them out of ``components/schemas`` (D8, FU-34)."""

    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            schemas = super().openapi().setdefault("components", {}).setdefault("schemas", {})
            for model in (StageEvent, StreamError):
                schemas[model.__name__] = model.model_json_schema(
                    ref_template="#/components/schemas/{model}"
                )
        return super().openapi()


app = _Api(title="Tripartite API", version=version("tripartite"), lifespan=lifespan)
app.state.settings = ApiSettings()
app.include_router(routes_queries.router)
app.include_router(routes_runs.router)


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
    with ThreadPoolExecutor(max_workers=2) as pool:
        reachable = pool.submit(model_reachable, stack)
        digest_ok = pool.submit(model_digest_ok, stack)
        return Health(
            status="ok",
            model_reachable=reachable.result(),
            model_digest_ok=digest_ok.result(),
            evaluator_ready=evaluator_ready(),
        )
