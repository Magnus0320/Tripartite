"""Response models of the API (ARCHITECTURE.md D8). They are the OpenAPI contract that
``tripartite api export-openapi`` writes to ``api-contract/openapi.json``.

A query is served as the planner may see it: ``query_id`` and ``query`` from ``PlannerInput``,
and nothing else (D3). ``reference_information`` is left out because the UI lists queries, and
no ``EvalRecord`` field is ever served; ``QueryItem`` forbids extra fields.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

from tripartite.data.planner_inputs import PlannerInput


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Health(_Response):
    """The response of GET /api/health."""

    status: Literal["ok"]
    model_reachable: bool
    model_digest_ok: bool
    evaluator_ready: bool


class QueryItem(_Response):
    """One validation query: the PlannerInput fields query_id and query only."""

    query_id: str
    query: str

    @classmethod
    def from_planner_input(cls, inp: PlannerInput) -> Self:
        return cls(query_id=inp.query_id, query=inp.query)


class QueryList(_Response):
    """The response of GET /api/queries: all 180 validation queries, in query_id order."""

    items: list[QueryItem]


class ErrorDetail(_Response):
    """An error response, for example for an unknown query_id."""

    detail: str
