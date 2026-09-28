"""Runtime pins and run configs (ARCHITECTURE.md D4, D7, §6).

``configs/stack.yaml`` holds every runtime pin: the Ollama version, the dedicated server's URL
and environment, the model tag and digest, and the tokenizer revision. ``make serve-model`` reads
it through ``tripartite model serve-env`` and ``tripartite model doctor`` checks the running server
against it. ``load_stack`` validates the file strictly: unknown keys are refused (so a stale
``runtime.log_path`` fails loudly, D4 AQ4), and ``runtime.env`` must hold exactly the D4 server
environment. If the file and the D4 table ever disagree, the table wins and the file is wrong.

``configs/baseline.yaml`` and ``configs/single.yaml`` are run configs (``RunConfig``). They are
identical except for ``run.name``, ``kind``, ``queries`` and ``seeds`` (D8): the API replaces the
single config's one query and one seed per job. ``config_hash`` is the D7 hash of a resolved
config: sha256 of canonical JSON, excluding ``run.name``.

Relative paths in both files are relative to the repository root, never to the working directory.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Final, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
STACK_PATH: Final = REPO_ROOT / "configs" / "stack.yaml"
BASELINE_CONFIG_PATH: Final = REPO_ROOT / "configs" / "baseline.yaml"
SINGLE_CONFIG_PATH: Final = REPO_ROOT / "configs" / "single.yaml"
MODEL_LOCK_PATH: Final = REPO_ROOT / "runs" / ".model.lock"
"""Held by every process that calls the model (D4 §Concurrency); shared with api by contract."""
SERVER_LOG_PATH: Final = REPO_ROOT / "runs" / "ollama-server.log"
"""The dedicated server's log: a fixed constant, never a stack.yaml key (D4 AQ4)."""

D4_MODEL_TAG: Final = "qwen3:8b-q4_K_M"
D4_MODEL_QUANT: Final = "q4_K_M"
D4_DIGEST_PREFIX: Final = "sha256:500a1f067a9f"
"""F10: the published digest prefix of ``qwen3:8b-q4_K_M``; the full digest is the pin."""
D4_TOKENIZER_REPO: Final = "Qwen/Qwen3-8B"
MAX_NUM_CTX: Final = 32768
"""Qwen3-8B's native context. Anything larger needs YaRN, which is not approved (D4)."""

D4_SERVER_ENV: Final[Mapping[str, str]] = {
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_KEEP_ALIVE": "-1",
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "f16",
}
"""The fixed part of the D4 server environment. ``OLLAMA_HOST`` and ``OLLAMA_CONTEXT_LENGTH``
are derived from ``runtime.url`` and ``model.num_ctx``."""
SERVER_ENV_KEYS: Final = frozenset({"OLLAMA_HOST", "OLLAMA_CONTEXT_LENGTH", *D4_SERVER_ENV})

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
QueryId = Annotated[str, StringConstraints(pattern=r"^val-\d{3}$")]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class ConfigError(RuntimeError):
    """A config file is missing or does not validate."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"must be a relative POSIX path inside the repository, got {value!r}")
    return value


def _loopback_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.port is None:
        raise ValueError(f"must be http://127.0.0.1:<port>, got {value!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"must have no path, query or fragment, got {value!r}")
    return value.rstrip("/")


RelativePath = Annotated[str, AfterValidator(_relative_path)]
LoopbackUrl = Annotated[str, AfterValidator(_loopback_url)]


def host_port(url: str) -> str:
    """``127.0.0.1:11435`` for ``http://127.0.0.1:11435``."""
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}"


# --- configs/stack.yaml -------------------------------------------------------------------


class Runtime(_Strict):
    name: Literal["ollama"]
    version: Version
    """Exact; doctor compares ``ollama --version`` and the server's ``/api/version``."""
    url: LoopbackUrl
    """The dedicated server this project uses."""
    env: dict[str, str]
    """Exported verbatim before ``ollama serve``, in file order."""
    desktop_app_url: LoopbackUrl
    """The desktop app's server, which must have no model loaded."""


class ModelPin(_Strict):
    tag: Literal["qwen3:8b-q4_K_M"]
    digest: Digest
    quant: Literal["q4_K_M"]
    num_ctx: int = Field(ge=1, le=MAX_NUM_CTX)

    @field_validator("digest")
    @classmethod
    def _published_prefix(cls, value: str) -> str:
        if not value.startswith(D4_DIGEST_PREFIX):
            raise ValueError(f"must start with {D4_DIGEST_PREFIX} (F10, D4), got {value!r}")
        return value


class TokenizerPin(_Strict):
    repo: Literal["Qwen/Qwen3-8B"]
    revision: GitSha
    local_dir: RelativePath


class StackConfig(_Strict):
    """``configs/stack.yaml`` (D4 §configs/stack.yaml)."""

    schema_version: Literal[1]
    runtime: Runtime
    model: ModelPin
    tokenizer: TokenizerPin

    @model_validator(mode="after")
    def _server_env_is_d4(self) -> "StackConfig":
        env = self.runtime.env
        if set(env) != SERVER_ENV_KEYS:
            missing = sorted(SERVER_ENV_KEYS - set(env))
            extra = sorted(set(env) - SERVER_ENV_KEYS)
            raise ValueError(f"runtime.env: missing keys {missing}, unknown keys {extra} (D4)")
        expected = {
            **D4_SERVER_ENV,
            "OLLAMA_HOST": host_port(self.runtime.url),
            "OLLAMA_CONTEXT_LENGTH": str(self.model.num_ctx),
        }
        wrong = {k: v for k, v in env.items() if v != expected[k]}
        if wrong:
            detail = ", ".join(f"{k}={v!r} (expected {expected[k]!r})" for k, v in wrong.items())
            raise ValueError(f"runtime.env differs from the D4 server environment: {detail}")
        if host_port(self.runtime.url) == host_port(self.runtime.desktop_app_url):
            raise ValueError("runtime.url and runtime.desktop_app_url must differ")
        return self

    @property
    def tokenizer_dir(self) -> Path:
        return REPO_ROOT / self.tokenizer.local_dir

    @property
    def tokenizer_id(self) -> str:
        """``<repo>@<revision>``, as logged on every call (D7)."""
        return f"{self.tokenizer.repo}@{self.tokenizer.revision}"

    @property
    def digest_hex(self) -> str:
        """The digest without its ``sha256:`` prefix, as ``/api/tags`` and ``/api/ps`` report it."""
        return self.model.digest.removeprefix("sha256:")


def _read_yaml(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{_display(path)}: missing") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{_display(path)}: not valid YAML: {exc}") from None


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_stack(path: Path = STACK_PATH) -> StackConfig:
    data = _read_yaml(path)
    try:
        return StackConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{_display(path)}: invalid: {exc}") from None


def serve_env_lines(stack: StackConfig, fmt: Literal["env", "sh"] = "env") -> list[str]:
    """One line per ``runtime.env`` entry, in file order: ``KEY=VALUE``, or with ``fmt="sh"``
    ``export KEY='VALUE'`` for ``eval`` in ``make serve-model``."""
    lines = []
    for key, value in stack.runtime.env.items():
        if not _ENV_KEY.match(key) or any(c in value for c in "\n\r\0"):
            raise ConfigError(f"runtime.env: {key!r} cannot be exported safely")
        if fmt == "sh":
            quoted = "'" + value.replace("'", "'\\''") + "'"
            lines.append(f"export {key}={quoted}")
        else:
            lines.append(f"{key}={value}")
    return lines


# --- configs/baseline.yaml and configs/single.yaml -----------------------------------------


class RunName(_Strict):
    name: NonEmptyStr
    """Excluded from ``config_hash`` (D7)."""


class PromptRef(_Strict):
    version: NonEmptyStr
    path: RelativePath
    sha256: Sha256Hex


class Generation(_Strict):
    """Every option sent on every request, so Modelfile defaults never apply (D4)."""

    num_predict: PositiveInt
    temperature: float = Field(ge=0)
    top_p: float = Field(gt=0, le=1)
    top_k: NonNegativeInt
    min_p: float = Field(ge=0, le=1)
    repeat_penalty: float = Field(gt=0)
    think: Literal[False]
    """Thinking is off in Phase 1 (D4)."""
    stop: list[NonEmptyStr] = Field(min_length=1)
    timeout_s: float = Field(gt=0)
    transport_retries: NonNegativeInt
    """Retries after a transport error, with the same seed (D6)."""


class RunConfig(_Strict):
    """A run config (D1, D4, D8)."""

    schema_version: Literal[1]
    run: RunName
    kind: Literal["batch", "single"]
    mode: Literal["sole-planning"]
    context_mode: Literal["full"]
    split: Literal["validation"]
    queries: Literal["all"] | list[QueryId]
    seeds: list[NonNegativeInt] = Field(min_length=1)
    order: Literal["seed-major"]
    stack: RelativePath
    prompt: PromptRef
    generation: Generation

    @model_validator(mode="after")
    def _consistent(self) -> "RunConfig":
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError(f"seeds must be unique, got {self.seeds}")
        if isinstance(self.queries, list):
            if not self.queries:
                raise ValueError("queries must be 'all' or a non-empty list")
            if len(set(self.queries)) != len(self.queries):
                raise ValueError("queries must be unique")
        if self.kind == "single" and (
            not isinstance(self.queries, list) or len(self.queries) != 1 or len(self.seeds) != 1
        ):
            raise ValueError("a single run has exactly one query and one seed (D8)")
        return self

    @property
    def prompt_path(self) -> Path:
        return REPO_ROOT / self.prompt.path

    @property
    def stack_path(self) -> Path:
        return REPO_ROOT / self.stack


def load_run_config(path: Path = BASELINE_CONFIG_PATH) -> RunConfig:
    data = _read_yaml(path)
    try:
        return RunConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{_display(path)}: invalid: {exc}") from None


def config_hash(resolved: Mapping[str, Any]) -> str:
    """sha256 of canonical JSON (sorted keys, no whitespace, UTF-8), excluding ``run.name`` (D7)."""
    data = json.loads(json.dumps(resolved, allow_nan=False))
    run = data.get("run")
    if isinstance(run, dict):
        run.pop("name", None)
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
