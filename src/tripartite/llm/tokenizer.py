"""The local tokenizer: HF ``Qwen/Qwen3-8B`` at the pinned revision (ARCHITECTURE.md D4, S4).

Local counts are the canonical input-token numbers (D7) and the basis of the context gate and
the post-check (D4). ``tripartite model pull`` downloads ``tokenizer.json`` and
``tokenizer_config.json`` (which holds the chat template) into ``tokenizer.local_dir`` and then
writes ``.pinned.json`` there: the repo, the revision and each file's size and sha256. Loading
checks the files against that marker and the marker against ``configs/stack.yaml``, so a folder
filled at another revision, or edited by hand, is refused rather than silently used.

A raw prompt is encoded with ``add_special_tokens=False``: the chat template already wrote every
special token into the text, and the tokenizer matches them there as single tokens, as the
runtime does with ``raw: true``.

``Tokenizer`` is what the model layer needs from a tokenizer. ``HFTokenizer`` is the pinned one;
fake mode has ``FakeTokenizer`` (``tripartite.llm.fake_client``), so CI, which has no network and
no tokenizer folder, never needs the real files (D4 §Fake-mode tokenizer). Functions take the
tokenizer as an argument; ``tokenizer_from_env()`` is only the default the pipeline, the CLI and
the API use.
"""

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Protocol

import tokenizers
from pydantic import BaseModel, ConfigDict, NonNegativeInt, ValidationError

from tripartite.config import StackConfig, load_stack
from tripartite.llm.errors import TokenizerError
from tripartite.llm.ollama_client import llm_mode

TOKENIZER_FILES: Final = ("tokenizer.json", "tokenizer_config.json")
MARKER: Final = ".pinned.json"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PinnedFile(_Frozen):
    bytes: NonNegativeInt
    sha256: str


class PinnedFiles(_Frozen):
    """``<local_dir>/.pinned.json``, written by ``tripartite model pull``."""

    repo: str
    revision: str
    files: dict[str, PinnedFile]


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_marker(directory: Path, repo: str, revision: str) -> PinnedFiles:
    """Record the size and sha256 of the tokenizer files just downloaded at ``revision``."""
    files = {
        name: PinnedFile(bytes=(directory / name).stat().st_size, sha256=_sha256(directory / name))
        for name in TOKENIZER_FILES
    }
    marker = PinnedFiles(repo=repo, revision=revision, files=files)
    tmp = directory / (MARKER + ".tmp")
    tmp.write_text(json.dumps(marker.model_dump(), indent=2, sort_keys=True) + "\n", "utf-8")
    os.replace(tmp, directory / MARKER)
    return marker


def check_tokenizer_dir(directory: Path, repo: str, revision: str) -> list[str]:
    """What is wrong with ``directory`` against the pin; empty if nothing."""
    try:
        marker = PinnedFiles.model_validate_json((directory / MARKER).read_bytes())
    except FileNotFoundError:
        return [f"{directory / MARKER} is missing; run `make pull-model`"]
    except ValidationError as exc:
        return [f"{directory / MARKER} is invalid: {exc}"]
    problems = []
    if (marker.repo, marker.revision) != (repo, revision):
        problems.append(
            f"files are {marker.repo}@{marker.revision}, but configs/stack.yaml pins "
            f"{repo}@{revision}; run `make pull-model`"
        )
    for name in TOKENIZER_FILES:
        path = directory / name
        entry = marker.files.get(name)
        if entry is None:
            problems.append(f"{MARKER} does not list {name}")
        elif not path.is_file():
            problems.append(f"{path} is missing; run `make pull-model`")
        elif path.stat().st_size != entry.bytes or _sha256(path) != entry.sha256:
            problems.append(f"{path} differs from the file downloaded at {marker.revision}")
    return problems


class Tokenizer(Protocol):
    """A tokenizer and its ``<repo>@<revision>`` id (D7 ``tokens.tokenizer``)."""

    @property
    def id(self) -> str: ...

    def encode_ids(self, text: str) -> list[int]: ...

    def count(self, text: str) -> int: ...

    def decode(self, ids: Sequence[int]) -> str: ...


class HFTokenizer:
    """The pinned HF tokenizer, loaded from ``tokenizer.json``."""

    def __init__(self, inner: tokenizers.Tokenizer, tokenizer_id: str) -> None:
        self._inner = inner
        self.id = tokenizer_id

    @classmethod
    def from_dir(cls, directory: Path, repo: str, revision: str) -> "HFTokenizer":
        problems = check_tokenizer_dir(directory, repo, revision)
        if problems:
            raise TokenizerError("; ".join(problems))
        inner = tokenizers.Tokenizer.from_file(str(directory / "tokenizer.json"))
        return cls(inner, f"{repo}@{revision}")

    def encode_ids(self, text: str) -> list[int]:
        return list(self._inner.encode(text, add_special_tokens=False).ids)

    def count(self, text: str) -> int:
        return len(self.encode_ids(text))

    def decode(self, ids: Sequence[int]) -> str:
        return self._inner.decode(list(ids), skip_special_tokens=False)


def load_tokenizer(stack: StackConfig, directory: Path | None = None) -> HFTokenizer:
    """The pinned tokenizer from ``tokenizer.local_dir`` (or ``directory``), checked first."""
    return HFTokenizer.from_dir(
        stack.tokenizer_dir if directory is None else directory,
        stack.tokenizer.repo,
        stack.tokenizer.revision,
    )


def tokenizer_from_env(stack: StackConfig | None = None) -> Tokenizer:
    """The default tokenizer: ``FakeTokenizer`` when ``TRIPARTITE_LLM=fake``, without reading
    ``configs/stack.yaml`` or ``tokenizer.local_dir`` and without the network; otherwise the pinned
    tokenizer of ``stack`` (default ``configs/stack.yaml``), checked by ``load_tokenizer``."""
    if llm_mode() == "fake":
        from tripartite.llm.fake_client import FakeTokenizer  # fake_client imports this module

        return FakeTokenizer()
    return load_tokenizer(load_stack() if stack is None else stack)


def lcp(a: Sequence[int], b: Sequence[int]) -> int:
    """The length of the common token-id prefix of ``a`` and ``b`` (D4)."""
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n
