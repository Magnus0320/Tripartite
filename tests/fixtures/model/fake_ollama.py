"""A scripted Ollama server behind ``httpx.MockTransport`` (model; ARCHITECTURE.md D4).

It implements the endpoints the model layer uses (``/api/version``, ``/api/tags``, ``/api/ps``,
``/api/generate`` for generation, load and unload, and a streamed ``/api/pull``) and simulates
the prompt cache, so the calibration can be driven through every mode:

- ``total``: ``prompt_eval_count`` counts the whole prompt;
- ``split``: it counts the uncached part and ``prompt_eval_cached_count`` the rest;
- ``uncached_only``: it counts the uncached part only.

The cache holds the previous prompt (A-020), or every earlier prompt with ``keeps_older=True``.
A fully cached prompt still evaluates its last token, as llama.cpp does. ``token_offset`` skews
every count (a tokenizer mismatch), ``load_ns`` sets the ``load_duration`` of a fresh load, and
``unload_works=False`` makes ``keep_alive: 0`` do nothing. ``reply`` and ``reply_done_reason`` set
what every generation returns (by default one token, cut by ``num_predict: 1``). Every request is
recorded.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from tripartite.config import StackConfig
from tripartite.llm.ollama_client import DesktopApp, OllamaClient
from tripartite.llm.tokenizer import Tokenizer, lcp

URL = "http://127.0.0.1:11435"
DESKTOP_URL = "http://127.0.0.1:11434"


@dataclass
class FakeOllama:
    tokenizer: Tokenizer
    tag: str
    digest_hex: str
    version: str = "0.33.2"
    mode: Literal["total", "split", "uncached_only"] = "uncached_only"
    server_ctx: int = 32768
    """What ``OLLAMA_CONTEXT_LENGTH`` gave the server: the context of a load without options."""
    pulled: bool = True
    pulled_digest: str | None = None
    report_context_length: bool = True
    token_offset: int = 0
    keeps_older: bool = False
    unload_works: bool = True
    load_ns: int = 1_500_000_000
    loaded_ctx: int | None = None
    """The context of the loaded model, or None when nothing is loaded."""
    history: list[list[int]] = field(default_factory=list)
    generated: int = 0
    """How many prompts were generated from so far."""
    requests: list[tuple[str, str, bytes]] = field(default_factory=list)
    reply: str = "O"
    reply_done_reason: str = "length"

    @classmethod
    def for_stack(cls, stack: StackConfig, tokenizer: Tokenizer, **kwargs: Any) -> "FakeOllama":
        return cls(tokenizer=tokenizer, tag=stack.model.tag, digest_hex=stack.digest_hex, **kwargs)

    def client(self) -> OllamaClient:
        return OllamaClient(URL, transport=httpx.MockTransport(self.handler))

    def _model(self) -> dict[str, Any]:
        return {
            "name": self.tag,
            "model": self.tag,
            "digest": self.pulled_digest or self.digest_hex,
        }

    def _load(self, ctx: int) -> None:
        self.loaded_ctx = ctx
        self.history = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        self.requests.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": self.version})
        if path == "/api/tags":
            models = [{**self._model(), "size": 5_225_374_496}] if self.pulled else []
            return httpx.Response(200, json={"models": models})
        if path == "/api/ps":
            if self.loaded_ctx is None:
                return httpx.Response(200, json={"models": []})
            entry = {**self._model(), "size": 11_000_000_000, "size_vram": 11_000_000_000}
            if self.report_context_length:
                entry["context_length"] = self.loaded_ctx
            return httpx.Response(200, json={"models": [entry]})
        if path == "/api/pull":
            return self._pull()
        if path == "/api/generate":
            return self._generate(json.loads(body))
        return httpx.Response(404, json={"error": f"no route {path}"})

    def _pull(self) -> httpx.Response:
        self.pulled = True
        lines = [
            {"status": "pulling manifest"},
            {"status": "pulling a3de86cd1c13", "total": 1000, "completed": 0},
            {"status": "pulling a3de86cd1c13", "total": 1000, "completed": 1000},
            {"status": "verifying sha256 digest"},
            {"status": "success"},
        ]
        return httpx.Response(200, content=b"\n".join(json.dumps(x).encode() for x in lines))

    def _generate(self, body: dict[str, Any]) -> httpx.Response:
        if body.get("model") != self.tag:
            return httpx.Response(404, json={"error": f"model {body.get('model')!r} not found"})
        if "prompt" not in body:
            if body.get("keep_alive") == 0:
                if self.unload_works:
                    self.loaded_ctx = None
                return httpx.Response(200, json={"done": True, "done_reason": "unload"})
            if self.loaded_ctx is None:
                self._load(self.server_ctx)
            return httpx.Response(200, json={"done": True, "done_reason": "load"})

        ctx = body.get("options", {}).get("num_ctx", self.server_ctx)
        load_ns = 40_000
        if self.loaded_ctx != ctx:
            self._load(ctx)
            load_ns = self.load_ns
        self.generated += 1
        ids = self.tokenizer.encode_ids(body["prompt"])
        earlier = self.history if self.keeps_older else self.history[-1:]
        cached = max((lcp(h, ids) for h in earlier), default=0)
        cached = min(cached, len(ids) - 1)
        self.history = [*self.history, ids] if self.keeps_older else [ids]
        response: dict[str, Any] = {
            "model": self.tag,
            "response": self.reply,
            "done": True,
            "done_reason": self.reply_done_reason,
            "eval_count": len(self.tokenizer.encode_ids(self.reply)),
            "load_duration": load_ns,
            "prompt_eval_duration": 1_000_000 * (len(ids) - cached),
            "eval_duration": 20_000_000,
            "total_duration": load_ns + 21_000_000,
        }
        if self.mode == "total":
            response["prompt_eval_count"] = len(ids) + self.token_offset
        else:
            response["prompt_eval_count"] = len(ids) - cached + self.token_offset
            if self.mode == "split":
                response["prompt_eval_cached_count"] = cached
        return httpx.Response(200, json=response)


@dataclass
class FakeDesktopApp:
    """The desktop app's server: running or not, with or without a model loaded."""

    running: bool = True
    loaded: list[str] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if not self.running:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/ps":
            models = [{"name": n, "model": n, "digest": "0" * 64} for n in self.loaded]
            return httpx.Response(200, json={"models": models})
        return httpx.Response(404, json={"error": "not scripted"})

    def client(self) -> DesktopApp:
        return DesktopApp(DESKTOP_URL, transport=httpx.MockTransport(self.handler))


def server_config_line(env: dict[str, str]) -> str:
    """A ``server config`` log line in Ollama's format, for the given logged values."""
    values = {
        "OLLAMA_CONTEXT_LENGTH": "32768",
        "OLLAMA_FLASH_ATTENTION": "true",
        "OLLAMA_HOST": "http://127.0.0.1:11435",
        "OLLAMA_KEEP_ALIVE": "2562047h47m16.854775807s",
        "OLLAMA_KV_CACHE_TYPE": "f16",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_ORIGINS": "[http://localhost https://localhost]",
        **env,
    }
    inner = " ".join(f"{k}:{v}" for k, v in sorted(values.items()))
    return (
        'time=2026-09-28T10:00:00.000+05:30 level=INFO source=routes.go:1 msg="server config" '
        f'env="map[{inner}]"'
    )
