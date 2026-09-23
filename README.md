# Tripartite

Tripartite is a research codebase for LLM travel planning on the
[TravelPlanner](https://github.com/OSU-NLP-Group/TravelPlanner) benchmark.

Version 0.1 covers Phases 0 and 1:

- a reproducible sole-planning baseline on the validation split;
- one local 8B model (Qwen3-8B served by Ollama);
- a deterministic rule-based plan parser;
- the unmodified official evaluator;
- a small FastAPI and React UI.

[`ARCHITECTURE.md`](ARCHITECTURE.md) is the build contract. Every design decision, pin and
path owner is recorded there. Assumptions live in [`assumptions.md`](assumptions.md).

## Status

Milestone **M0 (foundation)** is in place:

- the package skeleton;
- the root files (this README, the Makefile, `pyproject.toml` and the CI workflow);
- the run-log schema, with its writer and reader.

The later milestones are listed in D9's build order in `ARCHITECTURE.md`, and each one fills
in its own paths. Commands that belong to a later milestone either say "not available yet"
or print `skipped: <path> not present yet`.

## Requirements

- [uv](https://docs.astral.sh/uv/). uv installs the Python version pinned in `.python-version`
  and every Python dependency. Do not use conda or the system `pip`.
- Later milestones also need Ollama (M3) and Node.js for `web/` (W1).

## Quickstart

```bash
make setup   # uv sync; the evalenv and web steps are skipped until those projects exist
make lint    # ruff check, ruff format --check, mypy src, lint-imports
make test    # pytest -m "not local"
```

Every Makefile target is listed in `ARCHITECTURE.md` D9. The CLI entry point is
`uv run tripartite --help`.

The JSON Schema of the run-log events is committed at `src/tripartite/runlog/schema.json`.
After changing `src/tripartite/runlog/schema.py`, regenerate it:

```bash
uv run python -m tripartite.runlog.schema > src/tripartite/runlog/schema.json
```

## What is never committed

This repository is public. The following are never committed (`ARCHITECTURE.md` §8):

- dataset files: everything under `data/` except `data/MANIFEST.json`;
- any test-split artefact;
- the sandbox database;
- run output in `runs/` and `mlruns/`;
- secrets.

`.gitignore` covers all of these, and `scripts/ci/repo_hygiene.py` enforces them on every CI
run. Run it before committing:

```bash
uv run python scripts/ci/repo_hygiene.py
```

## Licence

MIT, see [`LICENSE`](LICENSE). Third-party attributions, including TravelPlanner (MIT code,
CC BY 4.0 data) and Qwen3 (Apache-2.0), are in [`NOTICE`](NOTICE).
