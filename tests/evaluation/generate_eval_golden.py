"""Generate ``tests/fixtures/eval_golden/`` with the real bridge (ARCHITECTURE.md D5, local only).

    uv run python -m tests.evaluation.generate_eval_golden --out tests/fixtures/eval_golden

Needs ``make setup`` and ``make data``. It scores the upstream example submission
(``vendor/travelplanner/postprocess/example_evaluation.jsonl``, 180 plans, 161 delivered; F6)
against the real validation records, twice over: plan by plan with the bridge's ``per_plan``
op, and as a whole with its ``aggregate`` op, which runs ``eval.eval_score`` itself. The bridge
runs with ``HF_HUB_OFFLINE=1`` and ``HF_DATASETS_OFFLINE=1`` (``RealBridge`` always sets them),
so if ``load_dataset`` were not bypassed, ``aggregate`` would fail instead of reaching the
network. The output is canonical JSON with no timestamps, so two runs are byte-identical.

Files written:

- ``per_plan.jsonl``: 180 lines ``{"query_id", "delivered", "commonsense", "hard"}``.
- ``official.json``: ``{"scores": <the six official keys>, "detailed": ...}`` from ``eval_score``.
- ``queries.jsonl``: 180 lines ``{"query_id", "level", "days", "constrained"}``, where
  ``constrained`` lists the local-constraint keys that are not null. This is the least
  ``aggregate`` needs to rebuild the denominators in CI, which has no dataset; it holds no
  constraint values and no free text (user decision, 2026-09-26).
- ``provenance.json``: what the output was computed from.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from tripartite.data import manifest
from tripartite.data.manifest import sha256_file
from tripartite.evaluation.bridge_client import EvaluatorBridge, Plan, RealBridge, read_plans
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord, load_eval_records, write_bridge_records

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "vendor" / "travelplanner" / "postprocess" / "example_evaluation.jsonl"
VENDOR_LOCK = ROOT / "vendor" / "travelplanner" / "VENDOR.lock"
UPSTREAM_COMMIT = "e52c87f4ac348a3410c46dc3553c519db5ec5e23"
N_DELIVERED = 161  # F6
KNOWN_QUERY_DIFFERENCES = {162: ("allow parties", "allow smoking")}
"""Lines where upstream's example submission carries other query text than validation.csv:
line 162 says "allow parties" where the dataset says "allow smoking". ``eval.py`` never reads
the submission's ``query``; it scores each plan against the dataset row at the same position,
so this is upstream drift, not a misalignment. Every other line matches byte for byte."""


def per_plan_json(result: PerPlanResult) -> dict[str, Any]:
    def group(g: dict[str, tuple[bool | None, str | None]] | None) -> Any:
        return None if g is None else {k: list(v) for k, v in g.items()}

    return {
        "query_id": result.query_id,
        "delivered": result.delivered,
        "commonsense": group(result.commonsense),
        "hard": group(result.hard),
    }


def query_json(record: EvalRecord) -> dict[str, Any]:
    constrained = [k for k, v in record.local_constraint.items() if v is not None]
    return {
        "query_id": record.query_id,
        "level": record.level,
        "days": record.days,
        "constrained": sorted(constrained),
    }


def _dumps(obj: Any, indent: int | None = None) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=indent)


def _check_alignment(records: list[EvalRecord], plans_path: Path) -> list[Plan | None]:
    lines = plans_path.read_text(encoding="utf-8").strip().split("\n")
    submitted = [json.loads(line) for line in lines]
    if len(submitted) != len(records):
        raise SystemExit(f"{plans_path.name}: {len(submitted)} plans for {len(records)} queries")
    for i, (entry, record) in enumerate(zip(submitted, records, strict=True), start=1):
        query = entry["query"]
        if i in KNOWN_QUERY_DIFFERENCES:
            submitted_text, dataset_text = KNOWN_QUERY_DIFFERENCES[i]
            if query == record.query or query.replace(submitted_text, dataset_text) != record.query:
                raise SystemExit(f"{plans_path.name} line {i}: not the known difference")
        elif entry["idx"] != i or query != record.query:
            raise SystemExit(f"{plans_path.name} line {i} is not {record.query_id}")
    return read_plans(plans_path)


def generate(out: Path, bridge: EvaluatorBridge | None = None) -> dict[str, float]:
    """Write the golden files into ``out`` and return the official scores."""
    records = load_eval_records()
    plans = _check_alignment(records, PLANS)
    owned = bridge is None
    active: EvaluatorBridge = RealBridge() if bridge is None else bridge
    try:
        results = [active.per_plan(r, p) for r, p in zip(records, plans, strict=True)]
        with tempfile.TemporaryDirectory() as tmp:
            records_path = Path(tmp) / "records.jsonl"
            write_bridge_records(records, records_path)
            official = active.aggregate(PLANS, records_path)
    finally:
        if owned:
            active.close()
    delivered = sum(r.delivered for r in results)
    if delivered != N_DELIVERED:
        raise SystemExit(f"{delivered} plans delivered, expected {N_DELIVERED} (F6)")

    out.mkdir(parents=True, exist_ok=True)
    lines = "".join(_dumps(per_plan_json(r)) + "\n" for r in results)
    (out / "per_plan.jsonl").write_text(lines, encoding="utf-8")
    official_json = {"scores": official.scores, "detailed": official.detailed}
    (out / "official.json").write_text(_dumps(official_json, indent=2) + "\n", encoding="utf-8")
    queries = "".join(_dumps(query_json(r)) + "\n" for r in records)
    (out / "queries.jsonl").write_text(queries, encoding="utf-8")
    provenance = {
        "generated_by": "tests/evaluation/generate_eval_golden.py (RealBridge, evalenv/bridge.py)",
        "upstream_commit": UPSTREAM_COMMIT,
        "plans_file": "vendor/travelplanner/postprocess/example_evaluation.jsonl",
        "plans_sha256": sha256_file(PLANS),
        "vendor_lock_sha256": sha256_file(VENDOR_LOCK),
        "dataset_revision": manifest.HF_REVISION,
        "validation_csv_sha256": sha256_file(manifest.raw_dir() / manifest.VALIDATION_CSV),
        "database_zip_sha256": manifest.DATABASE_ZIP.sha256,
        "n_queries": len(records),
        "n_delivered": delivered,
    }
    (out / "provenance.json").write_text(_dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return dict(official.scores)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    scores = generate(args.out)
    for key, value in scores.items():
        print(f"{key}: {value!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
