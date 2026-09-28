"""A valid run config as a dict, for tests to edit (model; ARCHITECTURE.md D4, D8)."""

from typing import Any


def run_data(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "run": {"name": "baseline"},
        "kind": "batch",
        "mode": "sole-planning",
        "context_mode": "full",
        "split": "validation",
        "queries": "all",
        "seeds": [0, 1, 2],
        "order": "seed-major",
        "stack": "configs/stack.yaml",
        "prompt": {
            "version": "sp-direct-v1",
            "path": "prompts/sole_planning_direct_v1.txt",
            "sha256": "0" * 64,
        },
        "generation": {
            "num_predict": 4096,
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "repeat_penalty": 1.0,
            "think": False,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "timeout_s": 600,
            "transport_retries": 2,
        },
    }
    data.update(changes)
    return data
