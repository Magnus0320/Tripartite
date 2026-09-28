"""``tripartite model``: pull, serve, check and calibrate the pinned model (ARCHITECTURE.md D4).

- ``pull``: the tokenizer files at the pinned revision into ``tokenizer.local_dir``, then the model
  through the dedicated server (``make serve-model`` must be running), checked against the
  pinned digest. Nothing is pulled through the desktop app's server.
- ``serve-env [--format sh]``: validate ``configs/stack.yaml`` and print ``runtime.env`` for
  ``make serve-model``.
- ``doctor``: check the running stack against the pins (``tripartite.llm.doctor``).
- ``measure-context``: step 1 of ``make measure-context``; tokenizer only.
- ``calibrate``: step 2; needs the dedicated server.

Every command exits 1 on failure and says why.
"""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from filelock import FileLock, Timeout
from huggingface_hub import hf_hub_download

from tripartite.config import (
    BASELINE_CONFIG_PATH,
    MODEL_LOCK_PATH,
    ConfigError,
    StackConfig,
    load_run_config,
    load_stack,
    serve_env_lines,
)
from tripartite.data.manifest import DataError
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.llm.calibration import (
    CALIBRATION_REPORT_PATH,
    CALIBRATION_SEED,
    COLD_PROBE_IDS,
    CalibrationOutcome,
    ProbePrompt,
    preflight,
    run_calibration,
    write_json,
)
from tripartite.llm.context import (
    CONTEXT_REPORT_PATH,
    load_context_report,
    measure,
    prompt_budget,
    report_json,
)
from tripartite.llm.doctor import Check, DoctorDeps, run_doctor
from tripartite.llm.errors import LLMError
from tripartite.llm.ollama_client import (
    DesktopApp,
    GenerateOptions,
    OllamaClient,
    PullProgress,
    llm_mode,
)
from tripartite.llm.tokenizer import (
    TOKENIZER_FILES,
    check_tokenizer_dir,
    load_tokenizer,
    write_marker,
)
from tripartite.planner.prompt import PromptError, PromptRenderer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Pull, serve, check and calibrate the pinned model (ARCHITECTURE.md D4)."""


def _fail(command: str, problems: list[str]) -> NoReturn:
    for problem in problems:
        typer.echo(f"model {command}: {problem}", err=True)
    typer.echo(f"model {command}: FAILED", err=True)
    raise typer.Exit(1)


def _stack(command: str) -> StackConfig:
    try:
        return load_stack()
    except ConfigError as exc:
        _fail(command, [str(exc)])


class EnvFormat(StrEnum):
    env = "env"
    sh = "sh"


@app.command("serve-env")
def serve_env(
    fmt: Annotated[
        EnvFormat,
        typer.Option("--format", help="env: KEY=VALUE lines; sh: export KEY='VALUE' lines."),
    ] = EnvFormat.env,
) -> None:
    """Validate configs/stack.yaml and print runtime.env, one line per variable."""
    stack = _stack("serve-env")
    try:
        lines = serve_env_lines(stack, "sh" if fmt is EnvFormat.sh else "env")
    except ConfigError as exc:
        _fail("serve-env", [str(exc)])
    for line in lines:
        typer.echo(line)


# --- pull -------------------------------------------------------------------------------------


def pull_tokenizer(stack: StackConfig, directory: Path | None = None) -> bool:
    """Download the tokenizer files at the pinned revision; False if they were already there."""
    directory = stack.tokenizer_dir if directory is None else directory
    if not check_tokenizer_dir(directory, stack.tokenizer.repo, stack.tokenizer.revision):
        return False
    directory.mkdir(parents=True, exist_ok=True)
    for name in TOKENIZER_FILES:
        hf_hub_download(
            repo_id=stack.tokenizer.repo,
            filename=name,
            revision=stack.tokenizer.revision,
            local_dir=directory,
        )
    write_marker(directory, stack.tokenizer.repo, stack.tokenizer.revision)
    return True


class _Progress:
    """Print a pull's status changes and every 10% of each layer, not every line."""

    def __init__(self) -> None:
        self.status = ""
        self.decile = -1

    def __call__(self, p: PullProgress) -> None:
        if p.total and p.completed is not None:
            decile = int(10 * p.completed / p.total)
            if p.status != self.status or decile != self.decile:
                typer.echo(
                    f"model pull:   {p.status}: {p.completed / 1e9:.2f} / {p.total / 1e9:.2f} GB"
                )
            self.decile = decile
        elif p.status != self.status:
            typer.echo(f"model pull:   {p.status}")
        self.status = p.status


def pull_model(stack: StackConfig, client: OllamaClient) -> str:
    """Pull the pinned tag through the dedicated server unless it is already there with the
    pinned digest, then check the digest. Returns what happened."""
    tag = stack.model.tag
    present = [m for m in client.tags() if m.name == tag]
    if present and present[0].digest == stack.digest_hex:
        return f"{tag} already present with the pinned digest"
    client.pull(tag, _Progress())
    present = [m for m in client.tags() if m.name == tag]
    if not present:
        raise LLMError(f"{tag} is not listed by /api/tags after the pull")
    if present[0].digest != stack.digest_hex:
        raise LLMError(
            f"{tag} was pulled with digest sha256:{present[0].digest}, but configs/stack.yaml "
            f"pins {stack.model.digest}. That is an architecture question; never update the pin"
        )
    return f"pulled {tag}"


@app.command()
def pull() -> None:
    """Download the tokenizer at the pinned revision, then pull the model through the dedicated
    server (start it first with `make serve-model`) and check its digest."""
    stack = _stack("pull")
    try:
        fetched = pull_tokenizer(stack)
    except Exception as exc:  # the hub raises many types; all mean the download failed
        _fail("pull", [f"tokenizer: {type(exc).__name__}: {exc}"])
    action = "downloaded" if fetched else "already present"
    typer.echo(
        f"model pull: tokenizer {stack.tokenizer_id}: {action} in "
        f"{stack.tokenizer.local_dir} ({', '.join(TOKENIZER_FILES)})"
    )
    with OllamaClient(stack.runtime.url, timeout_s=600.0) as client:
        try:
            client.version()
        except LLMError as exc:
            _fail(
                "pull",
                [
                    f"{stack.runtime.url} does not answer ({exc}); start the dedicated "
                    "server with `make serve-model` in another terminal"
                ],
            )
        try:
            result = pull_model(stack, client)
        except LLMError as exc:
            _fail("pull", [str(exc)])
    typer.echo(f"model pull: {result}; digest {stack.model.digest}: OK")


# --- doctor -------------------------------------------------------------------------------------


def _print_checks(command: str, checks: list[Check]) -> None:
    for c in checks:
        if c.level == "info":
            typer.echo(f"model {command}: {c.label}: {c.detail}")
        elif c.level == "ok":
            typer.echo(f"model {command}: {c.label}: OK ({c.detail})")
        else:
            typer.echo(f"model {command}: {c.label}: {c.level.upper()}: {c.detail}")


@app.command()
def doctor() -> None:
    """Check the running stack against configs/stack.yaml (D4)."""
    stack = _stack("doctor")
    with (
        OllamaClient(stack.runtime.url, timeout_s=600.0) as client,
        DesktopApp(stack.runtime.desktop_app_url) as desktop,
    ):
        checks = run_doctor(stack, DoctorDeps(client=client, desktop=desktop))
    _print_checks("doctor", checks)
    failures = [c for c in checks if c.level == "fail"]
    warnings = [c for c in checks if c.level == "warn"]
    if failures:
        _fail("doctor", [f"{len(failures)} check(s) failed"])
    typer.echo(f"model doctor: OK ({len(warnings)} warning(s))")


# --- measure-context and calibrate ------------------------------------------------------------

ConfigOption = Annotated[Path, typer.Option("--config", help="The run config (prompt, options).")]


@app.command("measure-context")
def measure_context(
    config: ConfigOption = BASELINE_CONFIG_PATH,
    out: Annotated[Path, typer.Option(help="Where to write the report.")] = CONTEXT_REPORT_PATH,
) -> None:
    """Step 1 of `make measure-context`: count every prompt with the pinned tokenizer and fail
    unless max(prompt_tokens) + num_predict + 256 <= num_ctx. No server needed."""
    stack = _stack("measure-context")
    try:
        run = load_run_config(config)
        tokenizer = load_tokenizer(stack)
        renderer = PromptRenderer.from_config(run, stack)
        inputs = load_planner_inputs()
    except (ConfigError, LLMError, PromptError, DataError, OSError, ValueError) as exc:
        _fail("measure-context", [f"{type(exc).__name__}: {exc}"])
    report = measure(
        inputs,
        lambda inp: renderer.render(inp).text,
        tokenizer,
        stack=stack,
        num_predict=run.generation.num_predict,
        prompt_version=run.prompt.version,
        prompt_sha256=run.prompt.sha256,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_json(report), encoding="utf-8")
    budget = prompt_budget(report.num_ctx, report.num_predict)
    for name, s in report.summary.items():
        typer.echo(
            f"model measure-context: {name}: min {s.min}, median {s.median:g}, "
            f"p95 {s.p95}, max {s.max}"
        )
    typer.echo(
        f"model measure-context: {len(report.per_query)} queries; max prompt_tokens "
        f"{report.summary['prompt_tokens'].max} against {report.num_ctx} - {report.num_predict} "
        f"- 256 = {budget}: headroom {report.headroom_tokens} tokens; fits: "
        f"{str(report.fits).lower()}; wrote {out}"
    )
    if not report.fits:
        _fail(
            "measure-context",
            [
                "the longest prompt does not fit; stop and raise an architecture question "
                "(YaRN is not approved; D4, Open question 1)"
            ],
        )


def _print_probes(outcome: CalibrationOutcome) -> None:
    typer.echo(
        "model calibrate: kind  query_id  prompt_tokens  prompt_eval_count  cached  lcp    load_ms"
    )
    for p in outcome.probes:
        load = "-" if p.load_ms is None else f"{p.load_ms:.1f}"
        typer.echo(
            f"model calibrate: {p.kind:<5} {p.query_id:<9} {p.prompt_tokens:>13}  "
            f"{p.prompt_eval_count!s:>17}  {p.prompt_eval_cached_count!s:>6}  "
            f"{p.lcp!s:>5}  {load:>9}"
        )


@app.command()
def calibrate(
    config: ConfigOption = BASELINE_CONFIG_PATH,
    context_report: Annotated[
        Path, typer.Option(help="The report written by measure-context.")
    ] = CONTEXT_REPORT_PATH,
    out: Annotated[Path, typer.Option(help="Where to write the report.")] = CALIBRATION_REPORT_PATH,
) -> None:
    """Step 2 of `make measure-context`: cold and warm probes against the dedicated server
    classify how it reports prompt tokens (D4 §Token calibration)."""
    command = "calibrate"
    if llm_mode() == "fake":
        _fail(command, ["TRIPARTITE_LLM=fake is set; calibration needs the real server"])
    stack = _stack(command)
    try:
        run = load_run_config(config)
        measured = load_context_report(context_report)
        tokenizer = load_tokenizer(stack)
        renderer = PromptRenderer.from_config(run, stack)
        inputs = {inp.query_id: inp for inp in load_planner_inputs()}
    except (ConfigError, LLMError, PromptError, DataError, OSError, ValueError) as exc:
        _fail(command, [f"{type(exc).__name__}: {exc}"])
    if measured is None:
        _fail(command, [f"{context_report} is missing; run `tripartite model measure-context`"])
    stale = [
        f"{name} {have!r} != {want!r}"
        for name, have, want in (
            ("num_ctx", measured.num_ctx, stack.model.num_ctx),
            ("revision", measured.revision, stack.tokenizer.revision),
            ("prompt_sha256", measured.prompt_sha256, run.prompt.sha256),
            ("num_predict", measured.num_predict, run.generation.num_predict),
        )
        if have != want
    ]
    if not measured.fits or stale:
        _fail(
            command,
            [
                f"{context_report} does not fit"
                if not measured.fits
                else f"{context_report} is stale ({'; '.join(stale)}); re-run measure-context"
            ],
        )

    prompts = []
    for qid in COLD_PROBE_IDS:
        text = renderer.render(inputs[qid]).text
        prompts.append(ProbePrompt(qid, text, tuple(tokenizer.encode_ids(text))))
        preflight(len(prompts[-1].ids), 1, stack.model.num_ctx)
    options = GenerateOptions.production(
        stack, run.generation, seed=CALIBRATION_SEED, num_predict=1
    )

    MODEL_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            FileLock(MODEL_LOCK_PATH, timeout=0),
            OllamaClient(stack.runtime.url) as client,
            DesktopApp(stack.runtime.desktop_app_url) as desktop,
        ):
            checks = run_doctor(stack, DoctorDeps(client=client, desktop=desktop, lock_path=None))
            failures = [c for c in checks if c.level == "fail"]
            if failures:
                _print_checks(command, failures)
                _fail(command, ["`make doctor` must pass first (D4 §Token calibration, 1)"])
            version = client.version()
            outcome = run_calibration(client, stack, prompts, options)
    except Timeout:
        _fail(command, [f"{MODEL_LOCK_PATH} is held by another process that is calling the model"])
    _print_probes(outcome)
    if not outcome.ok:
        _fail(command, outcome.mismatches + outcome.problems)
    report = outcome.report(stack, version, datetime.now(UTC))
    write_json(report, out)
    typer.echo(
        f"model calibrate: tokenizer agreement on {len(COLD_PROBE_IDS)} cold probes: OK; "
        f"mode {report.mode}; wrote {out}"
    )
