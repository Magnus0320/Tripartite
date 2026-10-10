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

## Requirements

- [uv](https://docs.astral.sh/uv/). uv installs the Python version pinned in `.python-version`
  and every Python dependency. Do not use conda or the system `pip`.
- Node.js 24 LTS for `web/`. The exact version is in [`web/.nvmrc`](web/.nvmrc).

The development loop below needs no model, no dataset and no network after setup.

## Development loop

### 1. Set up

```bash
make setup
```

This installs three things: the Python environment (`uv sync --locked`), the evaluator's own
environment in `evalenv/`, and the web dependencies (`npm ci` in `web/`).

### 2. Run the API in fake mode

Fake mode replaces the model and the evaluator with deterministic stand-ins. It runs only on
synthetic data, so first write the scoreable synthetic set to a directory outside the
repository:

```bash
export TRIPARTITE_DATA_DIR="$(uv run tripartite data synthetic --scoreable --out ~/.cache/tripartite/synthetic-scoreable)"
```

Then start the API in the same shell:

```bash
TRIPARTITE_LLM=fake TRIPARTITE_EVAL_BRIDGE=fake make api
```

The API listens on `127.0.0.1:8000`.

### 3. Run the web UI

In a second terminal:

```bash
make web
```

Open the address that Vite prints. The dev server proxies `/api` to the API from step 2.

### 4. Check your changes

```bash
make lint
```

```bash
make test
```

`make lint` runs ruff, mypy and the import contracts. `make test` runs every test that needs
no model (`pytest -m "not local"`).

## Real-model runs

Runs with the real model and the real dataset (`make data`, `make serve-model`, `make doctor`,
`make baseline`, `make eval`, `make reproduce-check`) are described in `ARCHITECTURE.md`: D4 for
the model server, D7 for run directories and resuming, and D9 for every Makefile target and
the order of operations. Follow that document; this README does not repeat it.

To browse finished batch runs in MLflow, sync one with `make mlflow-sync RUN=<run_id>` and then
run `make mlflow-ui`. MLflow is only an index; `runs/<run_id>/` is the record (D7).

## Run-log schema

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
