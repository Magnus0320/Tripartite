"""A synthetic tokenizer folder for CI (model; ARCHITECTURE.md D4, D9). No network, no real files.

``write_synthetic_tokenizer_dir(root, revision)`` writes what ``tripartite model pull`` leaves in
``tokenizer.local_dir``:

- ``tokenizer.json``: a byte-level model built in code, one token per UTF-8 byte, with the Qwen
  chat tokens (``<|im_start|>``, ``<|im_end|>``, ``<|endoftext|>``, ``<think>``, ``</think>``)
  as single tokens, like the real tokenizer;
- ``tokenizer_config.json``, whose ``chat_template`` renders a single user turn the way Qwen3's
  template does (``expected_user_prompt``);
- the ``.pinned.json`` marker for ``revision``.
"""

import json
from pathlib import Path
from typing import Final

import tokenizers
from tokenizers import AddedToken, decoders, models, pre_tokenizers

from tripartite.llm.tokenizer import write_marker

REPO: Final = "Qwen/Qwen3-8B"
SPECIAL_TOKENS: Final = ("<|endoftext|>", "<|im_start|>", "<|im_end|>")
ADDED_TOKENS: Final = ("<think>", "</think>")
CHAT_TEMPLATE: Final = (
    "{%- for message in messages %}\n"
    "    {{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>' + '\\n' }}\n"
    "{%- endfor %}\n"
    "{%- if add_generation_prompt %}\n"
    "    {{- '<|im_start|>assistant\\n' }}\n"
    "    {%- if enable_thinking is defined and enable_thinking is false %}\n"
    "        {{- '<think>\\n\\n</think>\\n\\n' }}\n"
    "    {%- endif %}\n"
    "{%- endif %}"
)


def expected_user_prompt(text: str) -> str:
    """What Qwen3's template renders for one user turn with thinking off."""
    return f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def build_tokenizer() -> tokenizers.Tokenizer:
    alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
    vocab = {char: i for i, char in enumerate(alphabet)}
    tk = tokenizers.Tokenizer(models.BPE(vocab=vocab, merges=[]))
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    tk.decoder = decoders.ByteLevel()
    tk.add_special_tokens([AddedToken(t, special=True, normalized=False) for t in SPECIAL_TOKENS])
    tk.add_tokens([AddedToken(t, special=False, normalized=False) for t in ADDED_TOKENS])
    return tk


def write_synthetic_tokenizer_dir(root: Path, revision: str, repo: str = REPO) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    build_tokenizer().save(str(root / "tokenizer.json"))
    config = {"chat_template": CHAT_TEMPLATE, "eos_token": "<|im_end|>"}
    (root / "tokenizer_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    write_marker(root, repo, revision)
    return root
