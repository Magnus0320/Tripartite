"""Valid context and calibration reports for a stack, written to test paths (model; D4, FU-25).

Tests write these under ``tmp_path`` and point the code at them; nothing here ever touches the
committed ``reports/`` files.
"""

from pathlib import Path

from tripartite.config import StackConfig
from tripartite.llm.calibration import CalibrationReport, Mode, Probe, write_json
from tripartite.llm.context import ContextReport, QueryCount, Summary, report_json

FAKE_REPO, FAKE_REVISION = "fake-bytes", "v1"
"""``fake-bytes@v1`` split the way both reports store a tokenizer id."""


def context_report(
    stack: StackConfig, *, tokenizer: str | None = None, revision: str | None = None
) -> ContextReport:
    """A one-query report that fits, counted with ``stack``'s tokenizer unless given."""
    summary = Summary(min=100, median=100.0, p95=100, max=100)
    return ContextReport(
        tokenizer=stack.tokenizer.repo if tokenizer is None else tokenizer,
        revision=stack.tokenizer.revision if revision is None else revision,
        num_ctx=stack.model.num_ctx,
        num_predict=4096,
        prompt_version="sp-direct-v1",
        prompt_sha256="0" * 64,
        per_query=[QueryCount(query_id="val-001", ref_chars=90, ref_tokens=90, prompt_tokens=100)],
        summary={name: summary for name in ("ref_chars", "ref_tokens", "prompt_tokens")},
        fits=True,
        headroom_tokens=stack.model.num_ctx - 4096 - 256 - 100,
    )


def write_context_report(path: Path, stack: StackConfig, **changes: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_json(context_report(stack, **changes)), encoding="utf-8")
    return path


def calibration_report(
    stack: StackConfig,
    *,
    mode: Mode = "total",
    tokenizer_repo: str | None = None,
    tokenizer_revision: str | None = None,
    ollama_version: str | None = None,
) -> CalibrationReport:
    """A report valid for ``stack`` unless a pin is overridden."""
    return CalibrationReport(
        calibrated_at="2026-09-28T05:00:00Z",
        ollama_version=stack.runtime.version if ollama_version is None else ollama_version,
        model_tag=stack.model.tag,
        model_digest=stack.model.digest,
        tokenizer_repo=stack.tokenizer.repo if tokenizer_repo is None else tokenizer_repo,
        tokenizer_revision=(
            stack.tokenizer.revision if tokenizer_revision is None else tokenizer_revision
        ),
        num_ctx=stack.model.num_ctx,
        mode=mode,
        probes=[
            Probe(
                kind="cold",
                query_id="val-001",
                prompt_tokens=10,
                lcp=None,
                prompt_eval_count=10,
                prompt_eval_cached_count=None,
                load_ms=1.0,
            )
        ],
    )


def write_calibration_report(path: Path, report: CalibrationReport) -> Path:
    write_json(report, path)
    return path
