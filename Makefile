# Tripartite Makefile: every target in ARCHITECTURE.md D9, written once at M0.
#
# Inputs that a later milestone creates are guarded by the existence of their path
# (D9 §Shared files, item 2). A guarded step inside a larger target prints
# "skipped: <path> not present yet" and the target carries on. A guarded target
# invoked by name prints the same line and its recipe exits 1, so make itself exits 2
# and a skip is never mistaken for success. Every guard becomes mandatory as soon as
# its path exists.

CONFIG ?= configs/baseline.yaml
RUN ?=
RUN2 ?=

TRIPARTITE := uv run tripartite

# $(call guarded_step,<path>,<command>): run <command> if <path> exists, else print the skip line.
define guarded_step
	@if test -e $(1); then echo '$(2)'; $(2); else echo 'skipped: $(1) not present yet'; fi
endef

# $(call require,<path>): stop a guarded target with the skip line and exit 1 if <path> is absent.
define require
	@test -e $(1) || { echo 'skipped: $(1) not present yet' >&2; exit 1; }
endef

.PHONY: setup serve-model pull-model doctor data measure-context baseline baseline-smoke \
	resume eval reproduce-check test test-local lint api openapi web e2e-local \
	mlflow-sync mlflow-ui

setup:
	uv sync
	$(call guarded_step,evalenv/pyproject.toml,uv sync --project evalenv)
	$(call guarded_step,web/package.json,npm ci --prefix web)

# D4 server (D4 §make serve-model): the model session's `tripartite model serve-env` validates
# configs/stack.yaml and prints runtime.env as shell exports; the Makefile never parses YAML.
# runs/ is created first because a fresh clone has none. If serve-env fails, the recipe exits
# before anything starts, so an unpinned server never comes up. The log path is a fixed constant.
serve-model:
	$(call require,configs/stack.yaml)
	mkdir -p runs; env_sh="$$(uv run tripartite model serve-env --format sh)" || exit 1; set -a; eval "$$env_sh"; set +a; exec ollama serve >> runs/ollama-server.log 2>&1

pull-model:
	$(TRIPARTITE) model pull

doctor:
	$(TRIPARTITE) data verify
	$(TRIPARTITE) model doctor

data:
	$(TRIPARTITE) data fetch
	$(TRIPARTITE) data verify

# Two steps, in this order; the calibration needs `make serve-model` running (D4).
measure-context:
	$(TRIPARTITE) model measure-context
	$(TRIPARTITE) model calibrate

baseline:
	$(TRIPARTITE) run start --config $(CONFIG)

baseline-smoke:
	$(MAKE) baseline CONFIG=configs/smoke.yaml

resume:
	$(TRIPARTITE) run start --resume $(RUN)

eval:
	$(TRIPARTITE) eval rescore --run $(RUN)

reproduce-check:
	$(TRIPARTITE) run reproduce-check --run $(RUN) --run2 $(RUN2)

test:
	uv run pytest -m "not local"

# pytest exits 5 when it collects no tests; until local tests exist that is not a failure (D9 C).
test-local:
	@echo 'uv run pytest -m local'; uv run pytest -m local || { rc=$$?; test $$rc -eq 5 || exit $$rc; echo 'no local tests collected'; }

lint:
	uv run ruff check
	uv run ruff format --check
	uv run mypy src
	uv run lint-imports

api:
	$(call require,src/tripartite/api/cli.py)
	$(TRIPARTITE) api serve

openapi:
	$(call require,src/tripartite/api/cli.py)
	mkdir -p api-contract
	$(TRIPARTITE) api export-openapi > api-contract/openapi.json

web:
	$(call require,web/package.json)
	npm run dev --prefix web

e2e-local:
	$(call require,web/package.json)
	npm run e2e --prefix web

mlflow-sync:
	$(TRIPARTITE) log mlflow-sync --run $(RUN)

mlflow-ui:
	uv run mlflow ui --backend-store-uri ./mlruns
