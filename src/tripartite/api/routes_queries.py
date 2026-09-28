"""``/api/queries`` (ARCHITECTURE.md D8, F1).

The queries come from ``tripartite.data.planner_inputs`` on every request, so the data root,
including ``TRIPARTITE_DATA_DIR``, is resolved at call time as D3 requires. Only ``query_id``
and ``query`` are served (``QueryItem``).
"""

from fastapi import APIRouter, HTTPException

from tripartite.api.schemas import ErrorDetail, QueryItem, QueryList
from tripartite.data.planner_inputs import get_planner_input, load_planner_inputs

router = APIRouter()


@router.get("/api/queries")
def list_queries() -> QueryList:
    """All 180 validation queries, in query_id order."""
    return QueryList(items=[QueryItem.from_planner_input(inp) for inp in load_planner_inputs()])


@router.get(
    "/api/queries/{query_id}",
    responses={404: {"model": ErrorDetail, "description": "Unknown query_id"}},
)
def get_query(query_id: str) -> QueryItem:
    """One validation query; 404 if the query_id is unknown."""
    try:
        inp = get_planner_input(query_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    return QueryItem.from_planner_input(inp)
