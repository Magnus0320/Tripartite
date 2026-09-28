"""The official prompt, read from the vendored upstream file (model; ARCHITECTURE.md D6)."""

import ast

from tripartite.config import REPO_ROOT


def upstream_planner_instruction() -> str:
    """``PLANNER_INSTRUCTION`` from the vendored ``agents/prompts.py``, read with ``ast`` so that
    langchain is never imported (D6)."""
    path = REPO_ROOT / "vendor" / "travelplanner" / "agents" / "prompts.py"
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PLANNER_INSTRUCTION" for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError("PLANNER_INSTRUCTION not found")
