"""The shared synthetic data set (data-eval; ARCHITECTURE.md D3 §Planner inputs in other
sessions' tests, D9, FU-14). Never rows of the real data (§8).

The generator lives in ``tripartite.data.synthetic`` (FU-28), so that ``tripartite data synthetic``
can write the same set; this module re-exports every name of it unchanged.

CI has no dataset. A test that needs ``PlannerInput``s or ``EvalRecord``s writes this set and
points ``TRIPARTITE_DATA_DIR`` at it, in its own ``conftest.py``::

    from tests.fixtures.synthetic_data import write_synthetic_data_dir

    @pytest.fixture(autouse=True)
    def synthetic_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(write_synthetic_data_dir(tmp_path)))

and then calls the loaders as usual. Nothing in ``tripartite.data`` is ever monkeypatched. Other
sessions import this module and never copy or edit it.

``write_synthetic_data_dir(root)`` writes ``raw/validation.csv`` (the 11 F7 columns, 180 rows)
and a matching ``raw/validation_ref_info.jsonl`` under ``root``, and returns ``root``. There is
no ``MANIFEST.json``: the loaders do not check it. ``tripartite.data.synthetic`` describes the
canaries and the byte-exactness traps.
"""

from tripartite.data.synthetic import (
    CANARY,
    CANARY_NUMBER_COLUMNS,
    CANARY_STRING_COLUMNS,
    COLUMNS,
    LOCAL_CONSTRAINT_ODD,
    N,
    budget,
    canaries,
    local_constraint,
    people_number,
    query,
    ref_line,
    row,
    visiting_city_number,
    write_csv,
    write_jsonl,
    write_raw,
    write_synthetic_data_dir,
)

__all__ = [
    "CANARY",
    "CANARY_NUMBER_COLUMNS",
    "CANARY_STRING_COLUMNS",
    "COLUMNS",
    "LOCAL_CONSTRAINT_ODD",
    "N",
    "budget",
    "canaries",
    "local_constraint",
    "people_number",
    "query",
    "ref_line",
    "row",
    "visiting_city_number",
    "write_csv",
    "write_jsonl",
    "write_raw",
    "write_synthetic_data_dir",
]
