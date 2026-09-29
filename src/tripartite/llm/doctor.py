"""``tripartite model doctor``: is the running stack the pinned one? (ARCHITECTURE.md D4, D1)

Checks, each reported as one line (``ok``, ``warn``, ``fail`` or ``info``):

- ``ollama --version`` (the CLI, asked about our server) equals ``runtime.version``;
- the server at ``runtime.url`` answers, and its ``/api/version`` equals ``runtime.version``;
- the server was started with the D4 environment: the last ``server config`` line of
  ``runs/ollama-server.log`` matches ``runtime.env`` (A-022 evidence);
- ``/api/tags`` lists ``model.tag`` with the pinned digest;
- the loaded model (``/api/ps``) has the pinned digest and ``context_length == model.num_ctx``.
  If nothing is loaded, doctor loads the model on the dedicated server with **no options**,
  under ``runs/.model.lock``, so ``/api/ps`` shows the server's own default context, which is
  what ``OLLAMA_CONTEXT_LENGTH`` set (A-022);
- the desktop app's server has no model loaded (``/api/ps`` only; a warning if it is not
  running). Nothing here ever sends it anything else;
- the tokenizer files are the ones pulled at the pinned revision;
- ``reports/context_report.json`` and ``reports/token_calibration.json`` are valid (a missing or
  stale one is a warning: both come after doctor, D4). A report counted with fake mode's
  tokenizer ``fake-bytes@v1`` is stale (FU-25);
- ``tripartite data verify`` passes.

Any ``fail`` makes doctor exit 1, so any runtime pin that differs from ``configs/stack.yaml``
fails it (D1). ``iogpu.wired_limit_mb`` and Metal's ``recommendedMaxWorkingSetSize`` from the
server log are reported as information (A-005).

``model_reachable`` and ``model_digest_ok`` are the two cheap model flags of ``/api/health`` (D4
§Health checks, D8; FU-17). Each sends one ``GET`` (``/api/version``, ``/api/tags``) and takes
at most 1.0 s in total. Neither sends a generate request, so neither can load the model, and
``/api/tags`` lists the model whether or not it is loaded. They never raise: any error, timeout
or missing ``configs/stack.yaml`` is ``False``. In fake mode both are ``True`` without any
network call.
"""

import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import httpx
from filelock import FileLock, Timeout

from tripartite.config import (
    MODEL_LOCK_PATH,
    SERVER_LOG_PATH,
    STACK_PATH,
    StackConfig,
    host_port,
    load_stack,
)
from tripartite.data import manifest
from tripartite.llm.calibration import CALIBRATION_REPORT_PATH, calibration_status
from tripartite.llm.context import CONTEXT_REPORT_PATH, context_report_status
from tripartite.llm.errors import LLMError, TransportError
from tripartite.llm.ollama_client import DesktopApp, OllamaClient, RunningModel, llm_mode
from tripartite.llm.tokenizer import check_tokenizer_dir

Level = Literal["ok", "warn", "fail", "info"]

CALIBRATION_LEVELS: Final[dict[str, Level]] = {
    "valid": "ok",
    "missing": "warn",
    "stale": "warn",
    "invalid": "fail",
}
"""Both reports come after doctor (D4), so a missing or stale one is only a warning."""
GO_MAX_DURATION: Final = "2562047h47m16.854775807s"
"""How Go prints ``math.MaxInt64`` nanoseconds: Ollama's keep-alive for ``-1`` (forever)."""
HEALTH_TIMEOUT_S: Final = 1.0
"""The total time a health check may take, loading ``configs/stack.yaml`` included (D4)."""


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    level: Level
    detail: str


def parse_cli_version(output: str) -> str | None:
    """The CLI's own version from ``ollama --version`` output. When the server's version differs
    the CLI prints it first and adds ``Warning: client version is X``."""
    match = re.search(r"client version is (\S+)", output) or re.search(
        r"ollama version is (\S+)", output
    )
    return match.group(1) if match else None


def ollama_cli_version(stack: StackConfig) -> str:
    """Run ``ollama --version`` against our server and return the CLI's version."""
    env = {**os.environ, "OLLAMA_HOST": stack.runtime.env["OLLAMA_HOST"]}
    proc = subprocess.run(
        ["ollama", "--version"], env=env, capture_output=True, text=True, timeout=30, check=False
    )
    output = proc.stdout + proc.stderr
    version = parse_cli_version(output)
    if version is None:
        raise RuntimeError(f"cannot read a version from `ollama --version`: {output.strip()!r}")
    return version


def iogpu_wired_limit_mb() -> int | None:
    """``sysctl iogpu.wired_limit_mb`` (0 = the macOS default), or None if unreadable."""
    try:
        proc = subprocess.run(
            ["sysctl", "-n", "iogpu.wired_limit_mb"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return int(proc.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# --- runs/ollama-server.log -----------------------------------------------------------------


def last_server_config(log_text: str) -> str | None:
    """The last ``msg="server config"`` line: the environment of the latest server start."""
    lines = [line for line in log_text.splitlines() if 'msg="server config"' in line]
    return lines[-1] if lines else None


def server_config_value(line: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}:([^\s\]]*)", line)
    return match.group(1) if match else None


def env_value_matches(key: str, expected: str, logged: str) -> bool:
    """Whether the logged form of ``key`` means the value exported from ``runtime.env``."""
    if key == "OLLAMA_HOST":
        return logged.removeprefix("http://").removeprefix("https://") == expected
    if key in ("OLLAMA_CONTEXT_LENGTH", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS"):
        return logged.isdigit() and int(logged) == int(expected)
    if key == "OLLAMA_KEEP_ALIVE" and expected == "-1":
        return logged in ("-1", GO_MAX_DURATION)
    if key == "OLLAMA_FLASH_ATTENTION" and expected == "1":
        return logged in ("1", "true")
    return logged == expected


def recommended_working_set_mb(log_text: str) -> float | None:
    """Metal's ``recommendedMaxWorkingSetSize`` from the ggml init lines (A-005)."""
    matches = re.findall(r"recommendedMaxWorkingSetSize\s*=\s*([\d.]+)\s*MB", log_text)
    return float(matches[-1]) if matches else None


def metal_total_gib(log_text: str) -> float | None:
    """The Metal device total from Ollama's ``inference compute`` line. Runtimes whose ggml init
    no longer logs ``recommendedMaxWorkingSetSize`` report the same budget here (A-005)."""
    matches = re.findall(
        r'msg="inference compute".*?library=Metal.*?\btotal="([\d.]+) GiB"', log_text
    )
    return float(matches[-1]) if matches else None


def log_context_length(log_text: str) -> int | None:
    """The last context size a runner was started with, for runtimes whose ``/api/ps`` lacks
    ``context_length`` (the A-022 fallback)."""
    matches = re.findall(r"(?:\bn_ctx\s*=\s*|--ctx-size\s+|\bKvSize:)(\d+)", log_text)
    return int(matches[-1]) if matches else None


# --- the checks -------------------------------------------------------------------------------


@dataclass
class DoctorDeps:
    client: OllamaClient
    desktop: DesktopApp
    log_path: Path = SERVER_LOG_PATH
    context_report_path: Path = CONTEXT_REPORT_PATH
    calibration_path: Path = CALIBRATION_REPORT_PATH
    tokenizer_dir: Path | None = None
    lock_path: Path | None = MODEL_LOCK_PATH
    """None when the caller already holds the model lock (``calibrate``)."""
    cli_version: Callable[[StackConfig], str] = ollama_cli_version
    data_checks: Callable[[], list[manifest.Check]] = manifest.verify
    wired_limit_mb: Callable[[], int | None] = iogpu_wired_limit_mb


def _read_log(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


def _env_check(stack: StackConfig, log_text: str | None, log_label: str) -> Check:
    label = f"server env ({log_label})"
    if log_text is None:
        return Check(label, "fail", "missing; start the server with `make serve-model`")
    line = last_server_config(log_text)
    if line is None:
        return Check(label, "fail", 'no msg="server config" line; start it with `make serve-model`')
    wrong = []
    for key, expected in stack.runtime.env.items():
        logged = server_config_value(line, key)
        if logged is None or not env_value_matches(key, expected, logged):
            wrong.append(f"{key}={logged!r} (expected {expected!r})")
    if wrong:
        return Check(label, "fail", "the running server's environment differs: " + ", ".join(wrong))
    return Check(label, "ok", f"{len(stack.runtime.env)} runtime.env values match")


def _describe(m: RunningModel) -> str:
    size = f", size {m.size / 1e9:.2f} GB" if m.size is not None else ""
    vram = f", size_vram {m.size_vram / 1e9:.2f} GB" if m.size_vram is not None else ""
    return f"{m.name} digest {m.digest[:12]}, context_length {m.context_length}{size}{vram}"


def _loaded_model_checks(stack: StackConfig, deps: DoctorDeps, log_text: str | None) -> Check:
    label = "loaded model (/api/ps)"
    client = deps.client
    running = client.ps()
    note = ""
    if not running:
        try:
            if deps.lock_path is None:
                client.load(stack.model.tag)
            else:
                deps.lock_path.parent.mkdir(parents=True, exist_ok=True)
                with FileLock(deps.lock_path, timeout=0):
                    client.load(stack.model.tag)
        except Timeout:
            return Check(
                label,
                "fail",
                f"nothing is loaded and {deps.lock_path} is held by another process, "
                "so doctor cannot load the model to check it",
            )
        note = "loaded by doctor with the server's default options; "
        running = client.ps()
    if len(running) != 1:
        names = [m.name for m in running] or "nothing"
        return Check(label, "fail", f"expected exactly {stack.model.tag} loaded, found {names}")
    model = running[0]
    problems = []
    if model.digest != stack.digest_hex:
        problems.append(f"digest {model.digest} != pinned {stack.digest_hex}")
    context = model.context_length
    source = "/api/ps"
    if context is None:
        context = log_context_length(log_text or "")
        source = "the server log"
    if context != stack.model.num_ctx:
        problems.append(
            f"context length {context} (from {source}) != num_ctx {stack.model.num_ctx}"
        )
    if problems:
        return Check(label, "fail", "; ".join(problems))
    return Check(label, "ok", note + _describe(model))


def _desktop_check(stack: StackConfig, desktop: DesktopApp) -> Check:
    label = f"desktop app ({host_port(stack.runtime.desktop_app_url)})"
    try:
        running = desktop.ps()
    except TransportError:
        return Check(label, "warn", "not running, so it has no model loaded")
    except LLMError as exc:
        return Check(label, "fail", f"cannot read /api/ps: {exc}")
    if running:
        return Check(
            label,
            "fail",
            f"has {[m.name for m in running]} loaded; unload it (the D4 memory budget "
            "assumes only the dedicated server holds a model)",
        )
    return Check(label, "ok", "no model loaded")


def run_doctor(stack: StackConfig, deps: DoctorDeps) -> list[Check]:
    checks = [
        Check(
            "configs/stack.yaml",
            "ok",
            f"valid; pins {stack.model.tag} "
            f"{stack.model.digest}, ollama {stack.runtime.version}, {stack.tokenizer_id}",
        )
    ]
    pin = stack.runtime.version

    try:
        cli = deps.cli_version(stack)
        checks.append(
            Check(
                "ollama --version",
                "ok" if cli == pin else "fail",
                f"client {cli}" + ("" if cli == pin else f" != pinned {pin}"),
            )
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        checks.append(Check("ollama --version", "fail", str(exc)))

    url = stack.runtime.url
    log_text = _read_log(deps.log_path)
    try:
        server = deps.client.version()
    except LLMError as exc:
        checks.append(
            Check(
                f"server ({url})",
                "fail",
                f"does not answer ({exc}); start it with `make serve-model`",
            )
        )
    else:
        checks.append(
            Check(
                f"server ({url})",
                "ok" if server == pin else "fail",
                f"/api/version {server}" + ("" if server == pin else f" != {pin}"),
            )
        )
        checks.append(_env_check(stack, log_text, "runs/ollama-server.log"))
        try:
            local = [m for m in deps.client.tags() if m.name == stack.model.tag]
            if not local:
                checks.append(
                    Check(
                        "model (/api/tags)",
                        "fail",
                        f"{stack.model.tag} is not pulled; run `make pull-model`",
                    )
                )
            elif local[0].digest != stack.digest_hex:
                checks.append(
                    Check(
                        "model (/api/tags)",
                        "fail",
                        f"{stack.model.tag} has digest {local[0].digest}, pinned "
                        f"{stack.digest_hex}; never update the pin to match",
                    )
                )
            else:
                checks.append(
                    Check("model (/api/tags)", "ok", f"{stack.model.tag} sha256:{local[0].digest}")
                )
                checks.append(_loaded_model_checks(stack, deps, log_text))
        except LLMError as exc:
            checks.append(Check("model", "fail", f"{type(exc).__name__}: {exc}"))

    checks.append(_desktop_check(stack, deps.desktop))

    tokenizer_dir = stack.tokenizer_dir if deps.tokenizer_dir is None else deps.tokenizer_dir
    problems = check_tokenizer_dir(tokenizer_dir, stack.tokenizer.repo, stack.tokenizer.revision)
    checks.append(
        Check(
            "tokenizer",
            "fail" if problems else "ok",
            "; ".join(problems) or f"{stack.tokenizer_id} in {stack.tokenizer.local_dir}",
        )
    )

    context = context_report_status(stack, deps.context_report_path)
    checks.append(
        Check(
            "context report",
            CALIBRATION_LEVELS[context.status],
            f"{context.status}: {context.detail}",
        )
    )
    status = calibration_status(stack, deps.calibration_path)
    checks.append(
        Check(
            "token calibration",
            CALIBRATION_LEVELS[status.status],
            f"{status.status}: {status.detail}",
        )
    )

    try:
        data = deps.data_checks()
    except manifest.DataError as exc:
        checks.append(Check("data verify", "fail", str(exc)))
    else:
        for c in data:
            checks.append(
                Check(
                    f"data verify: {c.label}",
                    "ok" if c.ok else "fail",
                    "; ".join(c.problems) or c.detail,
                )
            )

    wired = deps.wired_limit_mb()
    checks.append(
        Check(
            "iogpu.wired_limit_mb",
            "info",
            "unreadable" if wired is None else f"{wired} (0 = macOS default)",
        )
    )
    working_set = recommended_working_set_mb(log_text or "")
    metal_total = metal_total_gib(log_text or "")
    if working_set is not None:
        detail = f"{working_set:.2f} MB (A-005)"
    elif metal_total is not None:
        detail = f"not logged; Metal total {metal_total:g} GiB from 'inference compute' (A-005)"
    else:
        detail = "not in the server log"
    checks.append(Check("recommendedMaxWorkingSetSize", "info", detail))
    return checks


# --- /api/health (FU-17) ------------------------------------------------------------------------


def _health(
    check: Callable[[StackConfig, httpx.Client], bool],
    stack: StackConfig | Path,
    transport: httpx.BaseTransport | None,
) -> bool:
    """Run ``check`` against the dedicated server in a daemon thread, so that 1.0 s bounds the
    whole call (httpx's timeouts are per phase); ``False`` on any exception or on overrun."""
    try:
        if llm_mode() == "fake":
            return True
    except ValueError:
        return False
    result: list[bool] = []

    def run() -> None:
        try:
            config = load_stack(stack) if isinstance(stack, Path) else stack
            with httpx.Client(
                base_url=config.runtime.url, timeout=HEALTH_TIMEOUT_S, transport=transport
            ) as client:
                result.append(check(config, client))
        except Exception:  # never raise (D4): whatever went wrong, the flag is false
            result.append(False)

    thread = threading.Thread(target=run, name="model-health", daemon=True)
    thread.start()
    thread.join(HEALTH_TIMEOUT_S)
    return bool(result) and result[0]


def _get_json(client: httpx.Client, path: str) -> Any:
    """The JSON body of ``GET path`` if the status is exactly 200, else None."""
    response = client.get(path)
    return response.json() if response.status_code == 200 else None


def _answers_version(_stack: StackConfig, client: httpx.Client) -> bool:
    data = _get_json(client, "/api/version")
    return isinstance(data, dict) and "version" in data


def _lists_pinned_digest(stack: StackConfig, client: httpx.Client) -> bool:
    data = _get_json(client, "/api/tags")
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return False
    return any(
        isinstance(m, dict)
        and stack.model.tag in (m.get("name"), m.get("model"))
        and isinstance(m.get("digest"), str)
        and m["digest"].removeprefix("sha256:") == stack.digest_hex
        for m in models
    )


def model_reachable(
    stack: StackConfig | Path = STACK_PATH, *, transport: httpx.BaseTransport | None = None
) -> bool:
    """Whether the dedicated server answers ``GET /api/version`` with HTTP 200 and a ``version``
    field within 1.0 s. ``stack`` is a loaded config or the path of one (default
    ``configs/stack.yaml``); ``transport`` is for tests."""
    return _health(_answers_version, stack, transport)


def model_digest_ok(
    stack: StackConfig | Path = STACK_PATH, *, transport: httpx.BaseTransport | None = None
) -> bool:
    """Whether ``GET /api/tags`` lists an entry whose ``name`` (or ``model``) is ``model.tag``
    and whose digest, without any ``sha256:`` prefix, is ``model.digest``, within 1.0 s. It does
    not check the Ollama version; ``make doctor`` does."""
    return _health(_lists_pinned_digest, stack, transport)
