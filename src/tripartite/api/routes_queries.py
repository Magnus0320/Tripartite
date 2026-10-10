"""``/api/queries`` (ARCHITECTURE.md D8, F1).

The queries come from ``tripartite.data.planner_inputs`` on every request, so the data root,
including ``TRIPARTITE_DATA_DIR``, is resolved at call time as D3 requires. Only ``query_id``
and ``query`` are served (``QueryItem``).

If the data is missing or invalid, both routes answer 503 with the loader's message as
``ErrorDetail.detail``, never FastAPI's default 500 (D8, FU-23), and without absolute paths
(``messages.py``, FU-35). The loader reports that in
more than one way (``DATA_ERRORS``): ``DataError`` for a bad data root, ``OSError`` for a file
that is missing or unreadable, and ``ValueError`` or ``csv.Error`` for a file that is not the
pinned one.
"""

import csv
from typing import Any, Final

from fastapi import APIRouter, HTTPException

from tripartite.api.messages import public_message
from tripartite.api.schemas import ErrorDetail, QueryItem, QueryList
from tripartite.data.manifest import DataError
from tripartite.data.planner_inputs import get_planner_input, load_planner_inputs

router = APIRouter()

DATA_ERRORS: Final = (DataError, OSError, ValueError, csv.Error)
"""What ``load_planner_inputs`` raises when the data is missing or invalid."""
DATA_UNAVAILABLE: Final[dict[int | str, dict[str, Any]]] = {
    503: {"model": ErrorDetail, "description": "The data is missing or invalid"}
}


@router.get("/api/queries", responses=DATA_UNAVAILABLE)
def list_queries() -> QueryList:
    """All 180 validation queries, in query_id order; 503 if the data is missing or invalid."""
    try:
        inputs = load_planner_inputs()
    except DATA_ERRORS as exc:
        raise HTTPException(status_code=503, detail=public_message(str(exc))) from None
    return QueryList(items=[QueryItem.from_planner_input(inp) for inp in inputs])


@router.get(
    "/api/queries/{query_id}",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown query_id"},
        **DATA_UNAVAILABLE,
    },
)
def get_query(query_id: str) -> QueryItem:
    """One validation query; 404 if the query_id is unknown, 503 if the data is missing or
    invalid."""
    try:
        inp = get_planner_input(query_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    except DATA_ERRORS as exc:
        raise HTTPException(status_code=503, detail=public_message(str(exc))) from None
    return QueryItem.from_planner_input(inp)
