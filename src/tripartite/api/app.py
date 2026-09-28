"""The FastAPI app (ARCHITECTURE.md D8): ``uvicorn tripartite.api.app:app --host 127.0.0.1
--port 8000``, started by ``tripartite api serve`` (``make api``).

F1 serves ``GET /api/health`` and the query routes. Nothing here starts a run, takes
``runs/.model.lock`` or calls a model; runs and the job runner are F2. Importing this module
has no side effects, so ``tripartite api export-openapi`` needs no data.
"""

from importlib.metadata import version

from fastapi import FastAPI

from tripartite.api import routes_queries
from tripartite.api.schemas import Health

app = FastAPI(title="Tripartite API", version=version("tripartite"))
app.include_router(routes_queries.router)


@app.get("/api/health")
def get_health() -> Health:
    """Liveness, plus whether the model and the evaluator are ready."""
    # D8 fixes these fields but not what they check. model_reachable and model_digest_ok need
    # the model session's configs/stack.yaml and Ollama client (M3), and nothing defines
    # evaluator_ready yet. Until the F1 Architecture questions are answered, the server claims
    # none of them.
    return Health(status="ok", model_reachable=False, model_digest_ok=False, evaluator_ready=False)
