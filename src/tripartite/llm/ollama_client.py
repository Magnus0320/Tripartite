"""HTTP client for the dedicated Ollama server (ARCHITECTURE.md D4 §API, D6, D7).

Generation uses the native ``POST /api/generate`` with ``raw: true`` (we render the chat template
ourselves), ``stream: false``, ``keep_alive: -1``, ``think: false`` and every sampling option
explicitly, so Modelfile defaults never apply. ``stop`` is sent inside ``options``, which is
where Ollama reads it. The OpenAI-compatible endpoint is never used, because it drops
``num_ctx``.

``build_generate_body`` is the one serializer of a generation request. The real client sends
exactly its bytes and the fake client records exactly its bytes, so a test of the fake sees what
the server would have received.

Errors: a refused connection, a timeout or an HTTP 5xx raise ``TransportError``, the only
retryable kind (D6); any other failure raises ``ServerError``.

``DesktopApp`` is a separate, read-only view of the desktop app's server: it can only list
loaded models. Nothing in this project loads or pulls a model there (D4).
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from tripartite.config import Generation, StackConfig
from tripartite.llm.errors import ServerError, TransportError

LLM_MODE_ENV: Final = "TRIPARTITE_LLM"
DEFAULT_TIMEOUT_S: Final = 600.0
"""D6: a call that takes longer is a transport error."""
GENERATE_ENDPOINT: Final = "/api/generate"


def llm_mode() -> Literal["ollama", "fake"]:
    """``fake`` when ``TRIPARTITE_LLM=fake`` (CI and web development), else ``ollama``."""
    value = os.environ.get(LLM_MODE_ENV, "")
    if value in ("", "ollama"):
        return "ollama"
    if value == "fake":
        return "fake"
    raise ValueError(f"{LLM_MODE_ENV} must be 'fake', 'ollama' or unset, got {value!r}")


@dataclass(frozen=True, slots=True)
class GenerateOptions:
    """The ``options`` of a generation request, in the order they are sent."""

    num_ctx: int
    num_predict: int
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    repeat_penalty: float
    seed: int
    stop: tuple[str, ...]

    @classmethod
    def production(
        cls,
        stack: StackConfig,
        generation: Generation,
        *,
        seed: int,
        num_predict: int | None = None,
    ) -> Self:
        """The D4 options of a real call; ``num_predict`` is overridden only for probes."""
        return cls(
            num_ctx=stack.model.num_ctx,
            num_predict=generation.num_predict if num_predict is None else num_predict,
            temperature=generation.temperature,
            top_p=generation.top_p,
            top_k=generation.top_k,
            min_p=generation.min_p,
            repeat_penalty=generation.repeat_penalty,
            seed=seed,
            stop=tuple(generation.stop),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "seed": self.seed,
            "stop": list(self.stop),
        }


@dataclass(frozen=True, slots=True)
class GenerateRequest:
    model: str
    prompt: str
    """The fully rendered raw prompt, chat template included."""
    options: GenerateOptions
    think: bool = False


def build_generate_body(request: GenerateRequest) -> bytes:
    """The exact request body of ``POST /api/generate`` (D4 §API)."""
    body = {
        "model": request.model,
        "prompt": request.prompt,
        "raw": True,
        "stream": False,
        "keep_alive": -1,
        "think": request.think,
        "options": request.options.as_dict(),
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class GenerateResult:
    """One generation. Runtime-reported values are None when the runtime omitted them (D7)."""

    text: str
    done_reason: str | None
    prompt_eval_count: int | None
    prompt_eval_cached_count: int | None
    eval_count: int | None
    load_ms: float | None
    prefill_ms: float | None
    generation_ms: float | None
    total_ms: float | None
    wall_ms: float


class _Lenient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _GenerateResponse(_Lenient):
    response: str = ""
    done: bool
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    prompt_eval_cached_count: int | None = None
    eval_count: int | None = None
    load_duration: int | None = None
    prompt_eval_duration: int | None = None
    eval_duration: int | None = None
    total_duration: int | None = None


class RunningModel(_Lenient):
    """An entry of ``GET /api/ps``."""

    name: str
    model: str = ""
    digest: str
    size: int | None = None
    size_vram: int | None = None
    context_length: int | None = None
    expires_at: str | None = None


class LocalModel(_Lenient):
    """An entry of ``GET /api/tags``."""

    name: str
    model: str = ""
    digest: str
    size: int | None = None


class _PsResponse(_Lenient):
    models: list[RunningModel] = []


class _TagsResponse(_Lenient):
    models: list[LocalModel] = []


class _VersionResponse(_Lenient):
    version: str


class PullProgress(_Lenient):
    """One line of the streamed ``POST /api/pull`` response."""

    status: str = ""
    digest: str | None = None
    total: int | None = None
    completed: int | None = None


def _ms(ns: int | None) -> float | None:
    return None if ns is None else ns / 1e6


class LLMClient(Protocol):
    def generate(self, request: GenerateRequest) -> GenerateResult: ...


class _Http:
    def __init__(
        self, base_url: str, timeout_s: float, transport: httpx.BaseTransport | None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = httpx.Client(
            base_url=self.base_url, timeout=httpx.Timeout(timeout_s), transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _where(self, method: str, path: str) -> str:
        return f"{method} {self.base_url}{path}"

    def _check(self, response: httpx.Response, where: str) -> None:
        if response.status_code >= 500:
            raise TransportError(f"{where}: HTTP {response.status_code}: {_error_text(response)}")
        if response.status_code >= 400:
            raise ServerError(f"{where}: HTTP {response.status_code}: {_error_text(response)}")

    def request_json(self, method: str, path: str, *, content: bytes | None = None) -> Any:
        where = self._where(method, path)
        headers = {"Content-Type": "application/json"} if content is not None else None
        try:
            response = self._client.request(method, path, content=content, headers=headers)
        except httpx.TimeoutException:
            raise TransportError(f"{where}: timed out after {self.timeout_s:g} s") from None
        except httpx.TransportError as exc:
            raise TransportError(f"{where}: {type(exc).__name__}: {exc}") from None
        self._check(response, where)
        try:
            data = response.json()
        except ValueError:
            raise ServerError(f"{where}: response is not JSON") from None
        if isinstance(data, dict) and "error" in data:
            raise ServerError(f"{where}: {data['error']}")
        return data


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return str(data["error"])
    return response.text[:500]


def _parse[M: BaseModel](model: type[M], data: Any, where: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ServerError(f"{where}: unexpected response: {exc}") from None


def _body(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


class OllamaClient(_Http):
    """The dedicated server at ``runtime.url`` (D4 §Server)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout_s, transport)

    def generate(self, request: GenerateRequest) -> GenerateResult:
        start = time.perf_counter()
        data = self.request_json("POST", GENERATE_ENDPOINT, content=build_generate_body(request))
        wall_ms = (time.perf_counter() - start) * 1000
        r = _parse(_GenerateResponse, data, self._where("POST", GENERATE_ENDPOINT))
        if not r.done:
            raise ServerError(f"{self._where('POST', GENERATE_ENDPOINT)}: response not done")
        return GenerateResult(
            text=r.response,
            done_reason=r.done_reason,
            prompt_eval_count=r.prompt_eval_count,
            prompt_eval_cached_count=r.prompt_eval_cached_count,
            eval_count=r.eval_count,
            load_ms=_ms(r.load_duration),
            prefill_ms=_ms(r.prompt_eval_duration),
            generation_ms=_ms(r.eval_duration),
            total_ms=_ms(r.total_duration),
            wall_ms=wall_ms,
        )

    def load(self, model: str) -> None:
        """Load ``model`` with the server's default options and keep it loaded."""
        self.request_json(
            "POST", GENERATE_ENDPOINT, content=_body({"model": model, "keep_alive": -1})
        )

    def unload(self, model: str) -> None:
        """Ask the server to unload ``model`` now (``keep_alive: 0``; A-021)."""
        self.request_json(
            "POST", GENERATE_ENDPOINT, content=_body({"model": model, "keep_alive": 0})
        )

    def ps(self) -> list[RunningModel]:
        data = self.request_json("GET", "/api/ps")
        return _parse(_PsResponse, data, self._where("GET", "/api/ps")).models

    def tags(self) -> list[LocalModel]:
        data = self.request_json("GET", "/api/tags")
        return _parse(_TagsResponse, data, self._where("GET", "/api/tags")).models

    def version(self) -> str:
        data = self.request_json("GET", "/api/version")
        return _parse(_VersionResponse, data, self._where("GET", "/api/version")).version

    def pull(self, model: str, on_progress: Callable[[PullProgress], None]) -> None:
        """Pull ``model`` through this server, reporting each streamed progress line."""
        where = self._where("POST", "/api/pull")
        try:
            with self._client.stream(
                "POST",
                "/api/pull",
                content=_body({"model": model, "stream": True}),
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    self._check(response, where)
                status = ""
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        raise ServerError(f"{where}: not a JSON line: {line[:200]!r}") from None
                    if isinstance(data, dict) and "error" in data:
                        raise ServerError(f"{where}: {data['error']}")
                    progress = _parse(PullProgress, data, where)
                    status = progress.status
                    on_progress(progress)
        except httpx.TimeoutException:
            raise TransportError(f"{where}: timed out after {self.timeout_s:g} s") from None
        except httpx.TransportError as exc:
            raise TransportError(f"{where}: {type(exc).__name__}: {exc}") from None
        if status != "success":
            raise ServerError(f"{where}: stream ended with status {status!r}, not 'success'")


class DesktopApp(_Http):
    """The desktop app's server at ``runtime.desktop_app_url``: read-only, ``/api/ps`` only."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout_s, transport)

    def ps(self) -> list[RunningModel]:
        data = self.request_json("GET", "/api/ps")
        return _parse(_PsResponse, data, self._where("GET", "/api/ps")).models
