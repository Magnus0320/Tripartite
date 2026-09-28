"""The golden ``queries.jsonl`` holds only what §8.1 signs off (ARCHITECTURE.md §8.1, FU-24).

It is the one named exception to "no dataset derivative is committed": each of its 180 lines
holds exactly ``query_id``, ``level``, ``days`` and ``constrained``, the sorted names of the
local-constraint keys that are not null. No query text, reference information, budget, date,
city or constraint value. Any other key needs its own sign-off, so this test pins the key set,
and the values, so that none of them can carry free text either. The file is read here as raw
JSON lines, not through ``golden.queries()``.
"""

import json

from tests.evaluation.golden import GOLDEN

KEYS = {"query_id", "level", "days", "constrained"}
CONSTRAINT_KEYS = {"house rule", "cuisine", "room type", "transportation"}


def test_every_line_has_exactly_the_signed_off_keys_and_values() -> None:
    lines = (GOLDEN / "queries.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(lines) == 180
    for i, line in enumerate(lines, start=1):
        obj = json.loads(line)
        assert set(obj) == KEYS, (i, sorted(obj))
        constrained = obj["constrained"]
        assert isinstance(constrained, list), i
        assert constrained == sorted(set(constrained)), i  # sorted, no repeats
        assert set(constrained) <= CONSTRAINT_KEYS, (i, constrained)
        assert obj["query_id"] == f"val-{i:03d}"
        assert obj["level"] in {"easy", "medium", "hard"}, i
        assert type(obj["days"]) is int, i
        assert obj["days"] in {3, 5, 7}, i
