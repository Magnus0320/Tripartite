ARCHITECTURE.md · v0.3 · 2026-09-23

# Changelog

- v0.3 (2026-09-23): the repository is public, its root is this project's folder, and its remote is `github.com/Magnus0320/Tripartite`; commit 8205414 holds v0.2. New §8 (repository and publication hygiene) states what is never committed and names the check that enforces it; D9's `.gitignore` and vendor lines were tightened to match, and `scripts/` was added to the tree with owners. Open question 5 is fully closed. Fix: `num_ctx` is now **fixed at 32768** rather than computed, so nothing can disagree with the running server or invalidate the calibration; `make measure-context` has an explicit two-step order, and the measurement is a pass/fail gate, not an input (D4, D1). Fix: shared files across milestones. M0 creates the empty package skeleton, every CI step and Makefile target written at M0 is guarded by the existence of its input and becomes mandatory as soon as that input exists, `scripts/vendor_check.py` is owned by the data-eval session, and "CI green at M0" is defined exactly (D9 §Shared files). The same rule, plus a list of read-only shared paths (MANIFEST, openapi.json, the calibration report, smoke-ids, the model lock, conftest), resolves the other cross-session paths found in a sweep of D9.
- v0.2 (2026-09-22): user decisions recorded. D4 and D5 approved. D6 approved on condition that A-009 holds, and M4 is now gated on A-009 (D9 build order). A note there lets M3 use the official prompt only for token counting and calibration probes. Open question 4 (extra temperature-0 pass) declined. Licence MIT (open question 5; public/private still open). Open questions 6 and 7 unchanged in substance: R3 stays at ±2.0 pp, and A-016 remains the trigger to revisit it. NEEDS APPROVAL markers removed and Open questions updated. Fix: the tokenizer-agreement check and the truncation post-check assumed uncached calls, but every planner prompt shares the official instruction and example before `{text}`, so later calls hit the prompt cache. Both checks are redesigned in D4 around a Phase 0 calibration (`tripartite model calibrate`, run by `make measure-context`), cold probes made uncached by unloading the model, a unique-nonce warm-up, and a per-call bound that uses the token prefix shared with the previous prompt. Before calibration, real-model runs refuse to start. The measure-context row of the Makefile table, D1 Phase 0 exit item 2 and milestone M3 were updated to match. A-018–A-021 added; A-018 supersedes A-002 and A-019 supersedes A-003. Brief issues 1 and 10 no longer say "pending approval".
- v0.1 (2026-09-22): initial. Covers Phases 0 and 1 in full. Later phases appear only as named seams.

# 0. How to use this document

- This file is the build contract for the Claude Code sessions. Only the architecture session edits it. If you are a Code session and something here is ambiguous, wrong or missing: do not guess. Implement nothing for that point, write it under "Architecture questions" in your PR description, and carry on with the rest of your work.
- "MUST" is a requirement. "SHOULD" is a default that you may break only with a reason written in the PR. Anything not listed here is out of scope for v0.1.
- Assumptions are referenced as A-xxx and live in `assumptions.md`, which is append-only.
- Decisions are D1–D9, one for each item a–i in the architecture request. Decisions marked **NEEDS APPROVAL** are provisional. Build them as written, because they are the default, but Phase 1 exit numbers are not final until the user approves. As of v0.2 none remain. D6 is approved on condition that A-009 holds.

# 1. Scope of v0.1

In scope: Phase 0 (repo, CI, YAML configs, model serving, data loading; exit: `make baseline` runs end to end) and Phase 1 (validation split only, sole-planning mode with reference information as JSON, one local 8B model, local plan parsing, the official evaluator, 3 seeds, and a FastAPI + React skeleton with exactly five features).

Out of scope for v0.1. Do not build these, stub them or scaffold them:
- The DuckDB/SQLite port of the sandbox database (deferred until a phase needs it)
- Retrieval (BM25, embeddings, reranker) and retrieval tools
- Agents other than the single planner, and debate, moderator, stance classifier
- The code checker, the constraint parser (F1), the CP-SAT solver, trade-off score, optimality gap, citation checks
- UI: Leaflet map, Recharts budget charts, debate view, sliders, multi-turn refinement, replay mode
- Two-stage mode, injection tests, distillation, statistical tests (McNemar/bootstrap belong to Phase 4)
- Any use of the test split

# 2. Verified facts this design relies on

These were checked on 2026-09-22 against primary sources. Pins are in §6.

| # | Fact | Source |
|---|------|--------|
| F1 | The official evaluator reads the sandbox database itself. `evaluation/commonsense_constraint.py` and `hard_constraint.py` create `Flights()`, `Accommodations()`, `Restaurants()`, `GoogleDistanceMatrix()` and `Attractions()` when imported. Each one calls `pd.read_csv("../database/<...>.csv")` with a path relative to cwd, and both modules call `os.chdir()` to their own directory on import. | Repo at commit `e52c87f4ac348a3410c46dc3553c519db5ec5e23`, the source files |
| F2 | `evaluation/eval.py::eval_score` loads query data with `load_dataset('osunlp/TravelPlanner', 'validation', download_mode="force_redownload")`, so it goes to the network on every call. It indexes submitted plans by position (180 lines, in dataset order) and treats a plan as delivered when `tested_plan['plan']` is truthy. It already computes micro and macro rates: commonsense micro out of 1440 = 180×8, hard micro out of 420. | Same commit, `eval.py` |
| F3 | `utils/func.py` imports `gradio` at module top. The evaluator imports `utils.func`, so gradio must be importable even though the evaluator never calls it. | Same commit |
| F4 | The last evaluator change is `72d34bc` (2025-11-07). It fixes `is_valid_information_in_current_city`, where a single city string was iterated character by character. Numbers published before that date were produced by the older evaluator. | `git log -- evaluation/` |
| F5 | The official sole-planning "direct" run (`tools/planner/apis.py::Planner.run`) returns the string `'Max Token Length Exceeded.'` without calling the model when the prompt exceeds 12,000 tiktoken (gpt-3.5) tokens. It calls the model with temperature 0 and a single user message whose text is `PLANNER_INSTRUCTION.format(text=reference_information, query=query)`. | Same commit, `tools/planner/apis.py`, `agents/prompts.py` |
| F6 | The official GPT-4 parse step (`postprocess/openai_request.py`) turns text into a list of day dicts with keys `days, current_city, transportation, breakfast, attraction, lunch, dinner, accommodation`. It also deletes `$` and asks GPT-4 to rewrite vague entries as `-`. `postprocess/example_evaluation.jsonl` is a 180-line validation submission, 161 of them delivered, in the evaluator's input format. | Same commit |
| F7 | HF dataset `osunlp/TravelPlanner` at revision `8736504ecfc31b7f8b7e40122873c337e83fff7c` (last modified 2024-07-14) holds these files: `train.csv`, `validation.csv`, `test.csv`, `*_ref_info.jsonl`, `example_submission.jsonl`. Validation has 180 rows with columns `org, dest, days, visiting_city_number, date, people_number, local_constraint, budget, query, level, reference_information`. It has **no** `annotated_plan` column, which exists only in train. | HF API + datasets-server `/info` |
| F8 | In `database/validation_ref_info.jsonl` (repo), each line is one JSON object and runs 11,707 to 51,628 characters. The median is 26,810 and the 95th percentile 45,002. | Measured on the file |
| F9 | Qwen3-8B has 36 layers, 32 query heads and 8 KV heads, head_dim 128 and hidden size 4096. Native context is 32,768 (131,072 with YaRN) and `max_position_embeddings` is 40960. It has a hybrid thinking mode controlled by `enable_thinking` in the chat template. Recommended non-thinking sampling is T=0.7, top_p=0.8, top_k=20, min_p=0. Thinking mode must not use greedy decoding. | HF `Qwen/Qwen3-8B` config.json + model card |
| F10 | Ollama tags: `qwen3:8b` = `qwen3:8b-q4_K_M` is 5.2 GB (digest prefix `500a1f067a9f`), `qwen3:8b-q8_0` is 8.9 GB and `qwen3:8b-fp16` is 16 GB. The library lists a 40K context window. | ollama.com/library/qwen3/tags |
| F11 | Ollama's default context is small: 4096 in the FAQ, or a VRAM-tiered default on the context-length page (4k below 24 GiB of VRAM). Over-length prompts have been truncated with only a server-log warning (`"truncating input prompt" limit=… prompt=…`). The per-request `options.num_ctx`, `seed`, `temperature`, `top_k`, `top_p`, `min_p` and `num_predict` exist. Responses report `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count` and `eval_duration` (in ns). | docs.ollama.com FAQ, context-length and API pages; ollama/ollama issue #8099 |

Corrections to the facts supplied with the request:
- Validation **does** contain `budget`, and the evaluator reads it (`hard_constraint.py`, `valid_cost`). The field list supplied with the request omits it. Validation has no `annotated_plan` column. The loader therefore uses an **allowlist**, so every field not named in it, including ones nobody listed, is evaluator-only (D3).
- Ollama lists q8_0 at 8.9 GB, not 8.7 GB.
- GPU memory: the llama.cpp heuristic for machines with 32 GB or less reserves one third for the CPU, so the GPU gets about 16 GB of 24 GB, not 17 GB. Unverified on the target Mac (A-005).

# 3. System overview (Phases 0–1)

```
 HF dataset @rev ──► data/raw/validation.csv ─┐
                     data/raw/validation_ref_info.jsonl ─┐
                                              │          │
            (evaluator side only)             │          │ (planner side only)
   tripartite.evaluation.records ◄────────────┘          ▼
   EvalRecord (all fields)              tripartite.data.planner_inputs
            │                            PlannerInput{query_id, query, reference_information}
            │                                            │
            │                              tripartite.planner (official prompt v1)
            │                                            │ rendered prompt (pure fn of PlannerInput)
            │                              tripartite.llm (Ollama /api/generate raw, pinned)
            │                                            │ raw text + usage
            │                              tripartite.parse (rule parser, no LLM)
            │                                            │ plan dicts | null
            ▼                                            ▼
   evalenv/bridge.py (separate venv, subprocess) ◄── plans + EvalRecords
   runs official eval code UNMODIFIED from vendor/travelplanner
            │
            ▼
   per-plan constraint results + official metrics
            │
   runs/<run_id>/  (events.jsonl, manifest.json, plans_seed*.jsonl, metrics.json …)
            │                    │
   FastAPI (reads runs/, starts single-query jobs, SSE)      MLflow (derived index)
            │
   React UI (5 features)
```

# 4. Decisions

## D1 (a). Exit criteria, reproducibility and CI

### Phase 0 exit (all must hold)
1. `make setup && make data && make doctor` succeed on the M4 Pro.
2. `make measure-context` runs its two steps in order (D4 §Context measurement). Step 1 writes `reports/context_report.json` for all 180 validation queries and **fails** unless `max(prompt_tokens) + num_predict + 256 ≤ 32768`. Step 2 writes a valid `reports/token_calibration.json` (D4 §Token calibration), with tokenizer agreement passed on every cold probe and a classified cache mode.
3. `make baseline-smoke` exits 0. It runs `make baseline CONFIG=configs/smoke.yaml`: **9 queries × 3 seeds (0, 1, 2) = 27 calls**. The 9 queries are one per (level × days) cell (easy/medium/hard × 3/5/7). Each is the lowest-index query in its cell. The data-eval session provides `tripartite eval smoke-ids`, which computes them from the EvalRecords and prints them. The model session commits its output as explicit `query_ids` in `configs/smoke.yaml`. Selecting on `level`/`days` is an evaluator-side act done once, offline; the planner never sees those fields.
4. The smoke run directory contains every artifact listed in D7 §Run directory, including `metrics.json` computed by the subset aggregator (D5) and flagged `"subset": true`.
5. `make eval RUN=<smoke run>` re-scores it and produces byte-identical `metrics.json` and `per_plan_eval_seed*.jsonl` (R1 below).
6. CI is green on `main`.

### Phase 1 exit (all must hold)
1. `make baseline` (configs/baseline.yaml: all 180 queries × seeds 0, 1, 2 = 540 calls) completes with no hard errors, possibly after `make resume`.
2. Per seed: the official `eval_score` output (six official keys, verbatim) is in `metrics_seed{n}.json`. `metrics.json` holds per-seed values, mean and sample SD (ddof=1) for final pass rate, commonsense macro/micro, hard macro/micro and delivery rate. It also has input, output and thinking tokens, and load/prefill/generation/total/wall latency per query (mean, median, p95).
3. Reproducibility per the definition below: R1, R2 and R3 pass for a second full run, checked by `make reproduce-check RUN=<first> RUN2=<second>`.
4. `results/phase1/<run_id>/` (manifest.json, metrics.json, reproduce_check.json) is committed for both runs.
5. UI: `make e2e-local` passes. It drives the real stack in the browser for 3 query_ids drawn with a fixed RNG seed (42) from the 180: pick query, run, see day cards, see pass/fail per constraint, see tokens and latency, see the run in history. The CI API test also shows that every one of the 180 query_ids can be started and completes with the fake LLM.

### Definition of "reproducible"
- **R1, re-scoring (required, exact).** Re-running evaluation on stored parsed plans gives byte-identical `metrics_seed*.json` and `per_plan_eval_seed*.jsonl`.
- **R2, re-parsing (required, exact).** Re-running the parser on stored raw outputs gives byte-identical parsed plans.
- **R3, regeneration (required, tolerance).** A fresh run with an identical `config_hash` on the same pinned stack gives, for each of the six official metrics, a 3-seed mean within **±2.0 percentage points** of the first run. `reproduce_check.json` also reports, as a diagnostic with no threshold, the fraction of the 540 (query, seed) pairs whose raw output is byte-identical.
- Alternatives considered: (i) identical plans for every (query, seed). Rejected as an exit gate: Ollama gives no determinism guarantee on Metal across prompt-cache states or runtime restarts (A-001), so the gate would depend on something outside our control. It is kept as a diagnostic. (ii) Metrics-only with no R1/R2. Rejected because it cannot tell evaluator or parser nondeterminism from model noise. ±2 pp is about 3.6 queries out of 180 at the macro level. Micro rates have larger denominators.
- Pins required for R1–R3 are in §6. `make doctor` MUST fail if any runtime pin differs from `configs/stack.yaml`.

### CI (GitHub Actions, ubuntu-latest; no model, no database, no HF network)

The whole workflow is written once, by the foundation session at M0, and every step that depends on a path a later milestone creates is **guarded by that path's existence** (D9 §Shared files across milestones). A guarded step skips while its input is absent and is mandatory from the moment the input appears.

- **python job (always runs):** uv (pinned) and Python from `.python-version`. Runs `ruff check`, `ruff format --check`, `mypy src`, `lint-imports` (import-linter contracts, D3), the repository hygiene check (§8) and `pytest -m "not local"` with `TRIPARTITE_LLM=fake` and `TRIPARTITE_EVAL_BRIDGE=fake`. Guarded steps inside this job:
  - vendor integrity check, `python scripts/vendor_check.py` — guard: `vendor/travelplanner/VENDOR.lock` exists (M2). Every file under `vendor/travelplanner/` matches the lock (sha256), the lock lists no path matching `*ref_info*` or `*.csv`, and no such file is committed under `vendor/`;
  - test-split guard tests (D3) — part of pytest, guard: `tests/data/test_loader_refusals.py` exists (M1);
  - aggregator equivalence test against committed golden output from the real evaluator (D5) — part of pytest, guard: `tests/fixtures/eval_golden/` exists (M2);
  - OpenAPI drift check — guard: `api-contract/openapi.json` exists (F1). `tripartite api export-openapi` must equal the committed file.
- **web job:** guard: `web/package.json` exists (W1). Node from `web/.nvmrc`. Runs `npm ci`, `npm run typecheck`, `npm run lint`, `npm run test` (vitest), `npm run build`, and checks that `web/src/api/types.gen.ts` matches what is generated from `api-contract/openapi.json`.
- **Local gate (not in CI):** tests marked `@pytest.mark.local` need Ollama and/or the database and run with `make test-local`. Any PR touching `src/tripartite/{llm,planner,parse,pipeline,evaluation}`, `evalenv/`, `vendor/` or `configs/` MUST paste the output of `make test-local` and the smoke-run `metrics.json` into the PR description. `.github/pull_request_template.md` has that checkbox.

## D2 (b). Plan parsing (local, no LLM)

**Decision:** the planner writes free text in the official format using the official prompt (D6). A deterministic rule-based parser (`tripartite.parse`, id `rule-text`, version `v1`) turns it into the evaluator's JSON. No LLM parser and no constrained decoding in Phase 1.

Alternatives considered:
- (i) Structured output from the planner (Ollama `format` JSON schema). Rejected: it changes the official task and prompt, and constrained decoding changes model behaviour, which hurts comparability. It is also closer to "converting to structured formats for optimization".
- (ii) A local parser LLM (e.g. Qwen3-8B with the official GPT-4 parse prompt). Rejected for Phase 1: it adds a second nondeterministic model step, costs about 1–2k tokens per plan, and parse errors become model errors that are hard to attribute. It stays the documented fallback if A-012 fails; switching needs an architecture change.
- (iii) Rule parser. Chosen: deterministic (R2 is exact), zero LLM compute, auditable. The official prompt already fixes a rigid line format.

**Parser specification (v1).** Input is the visible output text only (no query, no evaluator fields). Output is `list[dict] | None` plus a list of warnings.
1. Normalize: CRLF→LF. Remove any `<think>…</think>` block; its content goes to `thinking_text` in the LLM event, and the warning `think_block_in_output` is added. Remove Markdown code fences, `**`, and leading `#`, `-`, `*` or `•` bullet markers at line start.
2. Day header: a line matching `(?i)^\s*day\s*(\d+)\s*:?\s*$`. Text before the first header is ignored.
3. Field line inside a day: `(?i)^\s*(current city|transportation|breakfast|attractions?|lunch|dinner|accommodations?)\s*:\s*(.*)$`. These map to `current_city, transportation, breakfast, attraction, lunch, dinner, accommodation`. A non-empty line that is neither a header nor a field line is appended, space-joined, to the previous field of the same day. If a label repeats within a day, the first occurrence wins (warning `duplicate_field`).
4. Value normalization (the deterministic subset of the official parse instructions in F6): strip whitespace, delete every `$`, and turn an empty value into `-`. A missing field becomes `-` (warning `missing_field:<name>`). Nothing else is rewritten. In particular, vague entries such as "eat at home" are **not** rewritten, although GPT-4 was asked to rewrite them (comparability note below).
5. Each day becomes `{"days": <int from header>, "current_city", "transportation", "breakfast", "attraction", "lunch", "dinner", "accommodation"}`, with days in order of appearance. Non-sequential numbering is kept and warned (`day_sequence`).
6. **Parse failure** (plan = `null`): the text is empty after normalization (`empty_output`), there is no day header (`no_day_blocks`), or no field line was recognized in any day (`no_fields`). The parser never reads the query and never pads or truncates days to match the query length. The evaluator judges completeness.
7. Golden tests: (a) round trip: render each delivered plan in `vendor/.../postprocess/example_evaluation.jsonl` into the official text format and parse it back to an equal dict; (b) hand-written fixtures for every rule and warning; (c) the smoke-run raw outputs committed as fixtures after Phase 0.

**Delivery rate.** The official definition is used unchanged: a (query, seed) is delivered if and only if its submitted `plan` is non-null and non-empty. Parse failures, empty outputs and LLM errors after retries all count as **not delivered**. `metrics.json` also breaks down the reasons for non-delivery (`llm_error`, `empty_output`, `length_no_plan`, `no_day_blocks`, `no_fields`). `done_reason == "length"` is not by itself a failure: the text is still parsed.

**Compute budget.** The parser uses no LLM tokens. Its CPU time is logged (`parse_ms`) and counted in wall-clock per query. It is common post-processing applied the same way to every system, so it is **excluded** from matched-compute budgets. Rule for later phases: if any system ever uses an LLM parser, that parser's tokens and time count toward that system's budget.

**Comparability with published numbers (to be written into every results table).** Our numbers are not directly comparable to the README/paper sole-planning results because of all of these: (1) local rule parser instead of GPT-4 parsing (we do not rewrite vague entries, and we do no manual fixes, while the official pipeline asks for manual fixes on parse failure); (2) no 12k-token cutoff (F5), so every query reaches the model; (3) the evaluator at `e52c87f4` includes the 2025-11 fix (F4); (4) sampling T=0.7 with 3 seeds instead of T=0; (5) a different model (Qwen3-8B non-thinking, Q4_K_M). Published 8B numbers (Llama3.1-8B final 0.0, commonsense macro 0.0, commonsense micro 60.1, hard macro 2.8; Qwen2-7B final 0.0) are shown for context only, with this note.

## D3 (c). Data boundary, enforced in code

**Rule:** the planner path sees exactly `query` and `reference_information`. Every other field, including any added later, is evaluator-only.

**Types** (in `src/tripartite/data/planner_inputs.py`):
```python
@dataclass(frozen=True, slots=True)
class PlannerInput:
    query_id: str            # "val-001" … "val-180", 1-based dataset order
    query: str               # validation.csv column "query", verbatim
    reference_information: str  # validation_ref_info.jsonl line i, exact bytes minus trailing "\n"

class TestSplitForbiddenError(RuntimeError): ...

def load_planner_inputs(split: str = "validation") -> list[PlannerInput]: ...
def get_planner_input(query_id: str) -> PlannerInput: ...
```
- `load_planner_inputs` reads `validation.csv` with `csv.DictReader` and builds each `PlannerInput` from the allowlist `{"query"}` only. The CSV `reference_information` column is ignored, because the JSON file is the brief's "reference info as JSON". It raises if the CSV and JSONL row counts differ or are not 180.
- `EvalRecord` (all columns, with `local_constraint` parsed by `ast.literal_eval`, never `eval`) lives in `src/tripartite/evaluation/records.py`, not in `tripartite.data`.
- **Import contracts** (import-linter, in `pyproject.toml`; CI fails on violation): `tripartite.planner`, `tripartite.llm` and `tripartite.parse` MUST NOT import `tripartite.evaluation` or `tripartite.api`. `tripartite.data` MUST NOT import `tripartite.evaluation`. The runtime (`tripartite.pipeline`) may import both sides, but passes only `PlannerInput` to `tripartite.planner`.
- `tripartite.planner.render_prompt(inp: PlannerInput) -> RenderedPrompt` raises `TypeError` unless `type(inp) is PlannerInput`.

**Test split refusal.**
- `load_planner_inputs("test")` and `load_eval_records("test")` raise `TestSplitForbiddenError` before any I/O. Any split other than `"validation"` raises `ValueError` (train is not needed in Phase 1 and carries annotated plans).
- The downloader fetches by explicit filename from the allowlist `{"validation.csv", "validation_ref_info.jsonl"}` via `huggingface_hub.hf_hub_download(repo_id="osunlp/TravelPlanner", repo_type="dataset", revision=<pinned>, filename=…)`. It MUST NOT use `snapshot_download` or `datasets.load_dataset`.
- The vendored evaluator excludes `database/test_ref_info.jsonl` and `train_ref_info.jsonl` (D5).
- The evaluator bridge refuses any `set_type` other than `validation`.

**Tests that prove the boundary** (`tests/leak/`, model session; `tests/data/`, data-eval session):
1. `test_planner_input_fields`: the dataclass fields are exactly `{"query_id", "query", "reference_information"}`.
2. `test_prompt_purity` (CI, over committed fixtures; plus `local` over all 180): for every input, the rendered prompt bytes equal `chat_template(PLANNER_TEMPLATE.format(text=ref, query=query))` built independently in the test. The prompt is therefore a pure function of the two allowed fields.
3. `test_canary_no_leak` (CI): build synthetic `EvalRecord`s whose evaluator-only fields hold unique canaries (`budget=987654321`, `level="CANARY_LVL_7f3a"`, `org="CANARY_ORG_…"`, a `local_constraint` with canary strings, etc.). Their `query` and `reference_information` do not contain the canaries. Run the full pipeline (`pipeline.run_one`) with the fake LLM client, which records every request body byte for byte. Assert that no canary appears in any recorded request.
4. `test_test_split_forbidden`: both loaders and the bridge client raise before any file or network access (checked by patching `open` and `hf_hub_download` to fail if called).
5. `test_no_test_files_on_disk` (local): no file named `test.csv` or `test_ref_info.jsonl` (or matching `*test*ref_info*`) exists anywhere under `data/` or `vendor/`.
6. The import-linter contracts above.

## D4 (d). Model and serving — Approved 2026-09-22

| Setting | Decision |
|---|---|
| Model | Qwen3-8B |
| Runtime | Ollama (version pinned at Phase 0 in `configs/stack.yaml`; `make doctor` enforces it) |
| Tag / quant | `qwen3:8b-q4_K_M`. The full digest is recorded at Phase 0 from `/api/tags`; the prefix must be `500a1f067a9f`. |
| Thinking | **Off.** Prompt rendered with the Qwen3 template and `enable_thinking=False` (an empty `<think>\n\n</think>\n\n` block). No `/no_think` text is added to the prompt. |
| Sampling | temperature 0.7, top_p 0.8, top_k 20, min_p 0.0, repeat_penalty 1.0 (Qwen non-thinking recommendation). Every option is sent explicitly on every request, so Modelfile defaults never apply. |
| Seeds | `options.seed` ∈ {0, 1, 2}; seed = replicate index |
| Call order | **Seed-major** (all 180 queries for seed 0, then seed 1, then seed 2), in query_id order. That way consecutive calls never share a reference-info prefix in the prompt cache, and prefill timing stays comparable. |
| num_predict | 4096 |
| num_ctx | **Fixed at 32768** (Qwen3-8B's native context) for Phase 1: in `configs/stack.yaml`, in `OLLAMA_CONTEXT_LENGTH` on the server, and in `options.num_ctx` on every request. It is a pin, not a computed value, so the server, the config and the calibration can never disagree. The measurement in `make measure-context` is a **gate**, not an input: it fails if `max(prompt_tokens) + num_predict + 256 > 32768`, and then the run stops and an architecture question is raised (YaRN is not approved). The memory budget below is sized for 32768, so a smaller value would save nothing that matters. Changing `num_ctx` later is a config change that requires restarting the server and re-running `tripartite model calibrate`; `make doctor` marks an old calibration stale until then. |
| Server | A dedicated `ollama serve` started by `make serve-model` on `127.0.0.1:11435` with `OLLAMA_CONTEXT_LENGTH=<num_ctx>`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=f16`, and the log written to `runs/ollama-server.log`. The desktop-app server on 11434 must have no model loaded; `make doctor` checks `/api/ps` and fails otherwise. |
| API | Native `POST /api/generate` with `raw: true`, `stream: false`, `keep_alive: -1`, `options{…}` and `stop: ["<|im_end|>", "<|endoftext|>"]`. The prompt is rendered by us from the pinned HF chat template (jinja2), so our local token count covers exactly the bytes the runtime sees. The OpenAI-compatible endpoint is not used, because it drops `num_ctx`. |
| Concurrency | 1 request at a time, system-wide. A file lock `runs/.model.lock` (filelock) is held by any process that calls the model (CLI batch or API job). |
| Warm-up | Each run, and each API single-run job, starts with one warm-up call (`num_predict: 1`), logged with `role: "warmup"` and excluded from metrics, so measured calls exclude model load. The warm-up prompt is the chat template around the fixed text `Reply with OK. nonce=<uuid4 hex>`, with a fresh nonce each time. The only token prefix it shares with any planner prompt is the chat-template header. That makes the cache state after the warm-up known by construction (see the post-check). |

**Memory budget (24 GB unified, dev tools and Claude apps running).** Weights take 5.2 GB. f16 KV cache is 2 × 36 layers × 8 heads × 128 × 2 B = 147,456 B/token, which is 4.8 GB at 32,768 tokens; the compute graph adds about 1 GB. Total resident is about 11 GB (A-011). That is under the ~16 GB default GPU working-set limit (A-005) and leaves about 13 GB for macOS, IDE, browser and the Claude apps.

**Context measurement (Phase 0, `make measure-context`).** The target runs exactly two commands, in this order, and stops at the first failure:

1. `tripartite model measure-context` — tokenizer only, no server needed. Tokenizer: HF `Qwen/Qwen3-8B` `tokenizer.json` at the pinned revision, loaded with `tokenizers`. For each of the 180 queries, record `ref_tokens` (reference_information alone) and `prompt_tokens` (the full rendered raw prompt). Write `reports/context_report.json`: `{tokenizer, revision, num_ctx: 32768, num_predict, per_query: [{query_id, ref_chars, ref_tokens, prompt_tokens}], summary: {min, median, p95, max} for each, fits: bool, headroom_tokens}`. Exit non-zero when `fits` is false, that is when `max(prompt_tokens) + num_predict + 256 > num_ctx`. From the character counts in F8, the maximum should be around 15–20k tokens (A-006), leaving ample headroom.
2. `tripartite model calibrate` — needs `make serve-model` running with the same pinned `num_ctx`. It refuses to run if `reports/context_report.json` is missing, if its `fits` is false, or if its `num_ctx` differs from the running server's (read from `/api/show` / the server env check in `make doctor`).

Because `num_ctx` is a pin and never recomputed, no server restart happens between the two steps.

**Truncation is a hard error.**
- (1) Pre-flight: if `prompt_tokens + num_predict > num_ctx`, raise `ContextOverflowError` before calling. The run aborts; the query is never silently recorded as non-delivered.
- (2) Post-check, per call, driven by the calibrated cache mode (§Token calibration below). Replaced in v0.2; the old rule assumed uncached calls.
- (3) After every run, `runs/ollama-server.log` is scanned for `truncating input prompt`. Any match fails the run.

**Why calls are not uncached (confirmed from source).** In the vendored `agents/prompts.py` at `e52c87f4`, `PLANNER_INSTRUCTION` is 1,971 characters long, and `{text}` first appears at character 1,937. The instruction and the Ithaca→Charlotte example come first, followed by `Given information: {text}\nQuery: {query}\nTravel Plan:`. So every rendered planner prompt starts with the same chat header plus about 1.9k characters of identical text. Ollama's prompt cache can therefore reuse that prefix from the previous call. The first measured call after a warm-up, and the first call per query in seed 0, are not uncached. A check that assumes `prompt_eval_count == prompt_tokens` would fail on every such call whenever the runtime leaves cached tokens out of `prompt_eval_count`.

**Token calibration (Phase 0; `tripartite model calibrate`, run as the second step of `make measure-context`; owner: model session, milestone M3).**
1. Preconditions: the dedicated server on `127.0.0.1:11435` is running with the pinned D4 env, and `make doctor` passes.
2. **Cold probes (uncached by construction).** Use the real planner prompts for `val-001` … `val-009` (exact production bytes). These are fixed IDs, so calibration does not depend on `configs/smoke.yaml`. For each one:
   - (a) Unload the model with `POST /api/generate {"model": <tag>, "keep_alive": 0}`, then poll `GET /api/ps` until the model is absent (timeout 60 s; on timeout the calibration fails).
   - (b) Send the prompt with the production options and `num_predict: 1`.
   - (c) Require `load_duration > 0`, as evidence of a fresh load with an empty KV cache (A-021).
   - (d) Record `prompt_eval_count`, and `prompt_eval_cached_count` if present.
   - **Tokenizer agreement (replaces the A-002 check; A-018):** `prompt_eval_count == prompt_tokens` (local count) with tolerance 0 on all 9 cold probes. Any mismatch fails the calibration with `TokenizerMismatchError`.
3. **Warm probes (cache semantics; A-019).** Right after the 9th cold probe, with no unload:
   - (i) Re-send the identical prompt: the whole prompt could be cached.
   - (ii) Send the `val-001` prompt, which shares only the instruction prefix with the prompt before it.
   - Compute `lcp` for each: the length of the common token-id prefix between this prompt and the previous one sent, both tokenized locally.
   - Classify the runtime into exactly one mode:
     - `total`: `prompt_eval_count == prompt_tokens` on both warm probes.
     - `split`: the response has `prompt_eval_cached_count`, and `prompt_eval_count + prompt_eval_cached_count == prompt_tokens` on both warm probes.
     - `uncached_only`: there is no usable cached-count field, and on both warm probes `prompt_tokens - lcp <= prompt_eval_count < prompt_tokens`.
   - If the mode is `uncached_only`, send (iii): the `val-009` prompt again, straight after (ii). It must satisfy `prompt_eval_count >= prompt_tokens - lcp` against (ii). This is the A-020 check; if it fails, the calibration fails.
   - Anything else fails the calibration and raises an architecture question. Do not improvise a rule.
4. Write `reports/token_calibration.json`: `{calibrated_at, ollama_version, model_tag, model_digest, tokenizer_repo, tokenizer_revision, num_ctx, mode, probes: [{kind: "cold"|"warm", query_id, prompt_tokens, lcp, prompt_eval_count, prompt_eval_cached_count, load_ms}]}`. The model session commits it. It is **valid** only while `ollama_version`, `model_digest`, `tokenizer_revision` and `num_ctx` equal the current `configs/stack.yaml` / config values. `make doctor` reports it as missing, valid or stale.
5. `make test-local` includes `test_tokenizer_agreement`, which re-runs only the cold probes (step 2) and asserts equality. It never inspects calls from a run.

**Post-check (2), per real-model call:**
- `lcp` = the common token-id prefix length between this call's prompt and the previous prompt **this process** sent since its warm-up. The warm-up counts as the previous prompt for the first measured call. Every call happens under `runs/.model.lock`, so no other process can change the cache between calls.
- Mode `total`: require `prompt_eval_count == prompt_tokens`.
- Mode `split`: require `prompt_eval_count + prompt_eval_cached_count == prompt_tokens`.
- Mode `uncached_only`: require `prompt_tokens - lcp <= prompt_eval_count <= prompt_tokens`. This bound relies on the cache holding at most the previous prompt (A-020).
- If the reported count is above `prompt_tokens`, raise `TokenizerMismatchError`. If it is below the lower bound, raise `TruncationError`. Both are hard errors: an `error` event is written and the run aborts.
- The result is logged on the `llm_call` event as an extra field `post_check: {mode, lcp, expected_min, expected_max, observed, ok}`. Readers ignore unknown fields (D7).

**Before calibration has run (explicit behaviour).** The post-check never runs without a valid calibration, and it never degrades to a warning:
- `tripartite run start` (CLI, including `make baseline`, `make baseline-smoke` and `make resume`) and the API job runner check `reports/token_calibration.json` before the warm-up. If it is missing or stale, they raise `CalibrationMissingError` before any model call. An API job then ends as `failed` with that message.
- Two commands work without a valid calibration: `tripartite model calibrate`, and the tokenizer-only first step of `measure-context`. Neither applies the post-check.
- The fake LLM client (`TRIPARTITE_LLM=fake`, CI and web development) reports `prompt_eval_count == prompt_tokens`, runs the post-check in mode `total`, and needs no calibration file.

Alternatives considered:
- MLX (`mlx-lm`): possibly faster on Apple silicon, and the brief lists it. It lacks a content-addressed model digest and the per-call load/prefill/generation split. It is reserved for Phase 8 LoRA.
- q8_0: better fidelity, but about 14.7 GB resident at 32k with f16 KV, which is too tight beside dev tools. q8_0 weights with a q8_0 KV cache come to about 12.3 GB, but KV quantization adds a second source of precision loss.
- Thinking on: better reasoning, but it adds thousands of tokens per call, forces sampling-only decoding, strains context and multiplies the ~6–9 h baseline (A-010). It is a candidate ablation later, and tokens are already logged separately.
- Greedy T=0 (as official): makes 3 seeds identical and the brief's 3-seed requirement empty. See Open questions.
- Concurrency above 1: multiplies KV memory and breaks timing comparability.

## D5 (e). Evaluator integration

**Vendoring.** Copy these paths **unmodified** from `OSU-NLP-Group/TravelPlanner@e52c87f4ac348a3410c46dc3553c519db5ec5e23` into `vendor/travelplanner/`, keeping their relative layout: `evaluation/` (all 3 files), `tools/` (entire directory, including subpackages), `utils/`, `agents/prompts.py`, `postprocess/example_evaluation.jsonl`, `database/README.md`, `LICENSE`, `README.md`. Excluded: `database/*_ref_info.jsonl` (including test), `images/`, `finetuning_data/`, and everything else. `vendor/travelplanner/VENDOR.lock` lists every vendored file with its sha256 and the upstream commit. `vendor/travelplanner/VENDOR.md` explains provenance and licence (code MIT; data CC BY 4.0).

**Database.** The zip is downloaded manually from the Google Drive link in the upstream README into `data/downloads/database.zip`, because Drive links are not scriptable reliably. `make data` verifies its sha256 against `data/MANIFEST.json` (trust on first use, A-013) and unzips it into `vendor/travelplanner/database/` (gitignored except the upstream `README.md`). The evaluator then finds `../database/...` from its own cwd.

**Separate environment.** `evalenv/` is its own uv project (`evalenv/pyproject.toml`, `evalenv/uv.lock`, same Python version). Dependencies: pandas 2.2.x, numpy, requests, tqdm, datasets and gradio, pinned by the lock. It is kept separate because gradio would conflict with our FastAPI pins, and because the evaluator has import-time side effects (`os.chdir`, globals).

**Bridge** (`evalenv/bridge.py`: standalone, stdlib only plus the vendored modules, no `tripartite` imports):
- Started as a long-lived subprocess: `uv run --project evalenv python evalenv/bridge.py` with `cwd=vendor/travelplanner/evaluation` and `PYTHONPATH=vendor/travelplanner:vendor/travelplanner/evaluation`. It speaks JSON Lines over stdin/stdout, and logs go to stderr. Loading the database CSVs happens once per process.
- Request `{"op": "per_plan", "id", "query": <EvalRecord dict>, "plan": <list|null>}`. It calls `commonsense_constraint.evaluation(query, plan)`. Only if `is_not_absent[0]` and `is_valid_information_in_sandbox[0]` are both true does it call `hard_constraint.evaluation(query, plan)`, which is the same gating as `eval.py`. It returns `{"id", "delivered", "commonsense": {key: [value, message]}, "hard": {key: [value, message]} | null}` with values `true`/`false`/`null`. A plan of null or empty returns `delivered: false` with both groups null.
- Request `{"op": "aggregate", "id", "set_type": "validation", "plans_path", "records_path"}`. It replaces the module attribute `eval.load_dataset` with a function that returns `{"validation": <records from records_path>}`, which removes the `force_redownload` network call (F2). No vendored file is edited. It then calls `eval.eval_score("validation", plans_path)` and returns `{"id", "scores": <six official keys>, "detailed": <second return value>}`. It refuses any `set_type` other than `validation`.
- Python exceptions inside the evaluator are returned as `{"id", "error": {"type", "message"}}`. For `per_plan`, the pipeline records the plan as `evaluation_error` and **aborts the run**, because an evaluator crash is a bug, not a model failure.

**Wrapper** (`src/tripartite/evaluation/`, main env):
- `bridge_client.py`: `EvaluatorBridge` protocol with `RealBridge` (subprocess) and `FakeBridge` (fixture-driven, for CI and the web dev loop via `TRIPARTITE_EVAL_BRIDGE=fake`).
- `constraints.py`: turns a per-plan result into the UI list `[{key, label, group, status, message}]`. `label` is the paper name from `eval.py::paper_term_mapping` (for example `valid_cost`→"Budget"). `status` is `pass` (true), `fail` (false), `not_applicable` (null), or `not_evaluated` (the hard group was skipped by gating). There are always 8 commonsense rows plus 5 hard rows.
- `aggregate.py`: `aggregate(results: list[PerPlanResult], records: list[EvalRecord]) -> Metrics`. It reimplements exactly the formulas of `eval_score`, with denominators computed from the subset (commonsense micro = passes/(8n); hard micro = passes/Σ applicable hard constraints, using eval.py's rules, including the medium/hard `mapping_constraint_record` logic). It is used for subsets (smoke, single runs). Full 180-query runs use the bridge's `aggregate` op, and the pipeline asserts the two agree to 1e-12.
- **Golden equivalence test:** once, locally, the data-eval session runs the real bridge on `example_evaluation.jsonl` and commits the per-plan results and official scores to `tests/fixtures/eval_golden/`. The CI test asserts `aggregate(per_plan) == official scores`.

**Metrics reported — Approved 2026-09-22 (micro added).** For each seed and as the 3-seed mean ± SD: Delivery Rate, Commonsense Micro, Commonsense Macro, Hard Micro, Hard Macro and Final Pass Rate. These are the evaluator's own six keys, unchanged. The brief names macro only. Micro is added because published 8B macro and final rates are at or near 0, so micro may be the only signal that moves. Also reported: per-constraint pass rates (from `detailed`), tokens and latency.

## D6 (f). Prompt policy — Approved 2026-09-22, conditional on A-009

- **Phase 1 prompt = the official sole-planning "direct" prompt, verbatim**: `PLANNER_INSTRUCTION` from `vendor/travelplanner/agents/prompts.py`. It is copied to `prompts/sole_planning_direct_v1.txt`, and its sha256 is recorded in the config. Test `test_prompt_matches_upstream` extracts the string with `ast` (without importing langchain) and asserts byte equality.
- `{text}` = the exact reference-information JSON line (D3). `{query}` = the query text. The whole prompt is sent as a single user turn with no system message, matching F5. The only wrapper is the Qwen3 chat template (D4).
- **In-context example:** only the one already inside the official prompt (Ithaca→Charlotte, written by the benchmark authors). We add no examples. No example is ever drawn from `annotated_plan`, train or validation data, or any evaluator output. Its provenance is A-009. If it turns out to be copied from a train annotated plan, the non-negotiable applies and D6 must be revisited before Phase 1 numbers are final.
- **Forbidden in any prompt:** hand-written hints about constraints or commonsense rules beyond the official text, structured restatements of the query, evaluator field values, and retries that feed back evaluator results.
- **Retries:** transport errors (connection refused, HTTP 5xx, timeout at 600 s) are retried up to 2 times with the same seed. Model outputs are never retried because they are bad. Retries are logged.
- **Versioning:** `prompt_version = "sp-direct-v1"`. Any byte change means a new version, a new file and an architecture decision.
- Alternatives considered: a custom prompt (rejected: risks "evaluation cues" and breaks comparability); the official CoT prompt (it adds a diversity hint of its own, so it is kept for later as an ablation); zero-shot with the example removed (possible if A-009 fails).

## D7 (g). Run log and tracking

**Location and immutability.** `runs/<run_id>/`, gitignored. `run_id = <UTC YYYYMMDDTHHMMSSZ>-<kind>-<config_hash[:8]>-<4 hex>`. A finished run is never modified. Re-scoring writes to `runs/<run_id>/rescore-<ts>/`, and `make eval` compares.

**Run directory:**
```
manifest.json            # = payload of run_start, plus final status
events.jsonl             # all events, append-only, one JSON object per line
blobs/<sha256>.txt       # rendered prompts (stored once; shared across seeds)
plans_seed{n}.jsonl      # evaluator input: 180 lines (or subset) {"idx","query","plan"}
per_plan_eval_seed{n}.jsonl
metrics_seed{n}.json     # official scores (full runs) or subset aggregate
metrics.json             # summary across seeds + tokens/latency stats
reproduce_check.json     # only when produced by reproduce-check
```

**Event envelope** (every line): `{"schema_version": 1, "event_id": <uuid4>, "seq": <int, per run, from 0>, "ts": <RFC3339 UTC>, "run_id", "event_type", ...payload}`. Readers MUST ignore unknown `event_type`s and unknown fields.

**Event types:**
- `run_start`: `kind` (batch|single), `mode` ("sole-planning"), `context_mode` ("full"), `split`, `query_ids`, `seeds`, `order`, `config` (fully resolved), `config_hash` (sha256 of canonical JSON: sorted keys, no whitespace, excluding `run.name`), `model{runtime, runtime_version, tag, digest, quant, tokenizer_repo, tokenizer_revision}`, `prompt_version`, `prompt_sha256`, `parser_version`, `evaluator{upstream_commit, vendor_lock_sha256}`, `dataset{revision, files_sha256}`, `database_zip_sha256`, `env{python, uv_lock_sha256, evalenv_lock_sha256, git_commit, git_dirty, macos, chip, ollama_env{…}}`, `agents: [{"agent_id": "planner", "role": "planner", "model_tag"}]`, `resumed_from` (null or run_id).
- `llm_call`: `call_id`, `query_id`, `seed`, `agent_id` ("planner"), `role` ("planner"|"warmup"), `round` (null), `parent_call_id` (null), `attempt`, `request{endpoint, num_ctx, num_predict, temperature, top_p, top_k, min_p, repeat_penalty, seed, think: false, stop}`, `prompt_sha256` (→ blobs/), `tokens{input: <local count>, input_reported: prompt_eval_count, input_cached_reported: <or null>, output_visible: <local count>, output_thinking: <local count, 0 in Phase 1>, output_reported: eval_count, tokenizer: "<repo>@<rev>"}`, `timing_ms{load, prefill, generation, total_reported, wall_client}` (from `load_duration`, `prompt_eval_duration`, `eval_duration`, `total_duration`, ns→ms float; null if absent), `done_reason`, `output_text`, `thinking_text`, `error` (null or `{type, message}`).
- `parse`: `query_id`, `seed`, `call_id`, `parser_version`, `ok`, `failure_reason`, `warnings`, `n_days`, `parse_ms`.
- `eval`: `query_id`, `seed`, `delivered`, `commonsense{…}`, `hard{…}|null`, `commonsense_pass`, `hard_pass`, `final_pass` (per-plan pass means no `false` values, as in eval.py).
- `query_result`: `query_id`, `seed`, `status` (delivered|not_delivered), `failure_reason`, `totals{input_tokens, output_tokens, thinking_tokens, llm_calls, wall_ms, prefill_ms, generation_ms, load_ms, parse_ms}`. There is **exactly one per (query, seed)**, and this is the resume key.
- `retrieval`: **reserved and empty** (a seam for Phase 3). The schema exists (`{call_id, agent_id, query_id, seed, payload: {}}`), and Phase 1 never emits it. A test asserts the Phase 1 pipeline emits zero `retrieval` events and that the schema validates an empty payload.
- `run_end`: `status` (succeeded|failed|interrupted), `counts`, `metrics_path`, `error`.
- `error`: any hard error (`ContextOverflowError`, `TruncationError`, `EvaluationError`, digest mismatch), with a traceback string.

Schemas are pydantic models in `src/tripartite/runlog/schema.py`, and JSON Schema is exported to `src/tripartite/runlog/schema.json`. `writer.py` flushes and fsyncs each line. `reader.py` streams events.

**Resume.** `tripartite run --resume <run_id>` requires the same `config_hash`. It skips (query, seed) pairs that already have a `query_result`, appends to the same `events.jsonl`, and sets `resumed: true` in the manifest.

**MLflow** is a derived, disposable index for comparing runs across time in a UI (params, headline metrics, artifact links). It is **not** the record: JSONL is the source of truth, and if they disagree, JSONL wins. It uses a local file store `./mlruns` (gitignored) and experiment `tripartite`. At the end of a batch run (and via `make mlflow-sync RUN=…`), one MLflow run is logged per Tripartite batch run: params = config_hash, model tag+digest, prompt_version, parser_version, seeds; metrics = the six official metrics per seed (`step = seed`) plus mean; artifacts = manifest.json and metrics.json. Single UI runs are not synced. The API never reads MLflow.

## D8 (h). Backend and UI contract (Phase 1)

**Process model.** `uvicorn tripartite.api.app:app --host 127.0.0.1 --port 8000`. There is one in-process job runner: an asyncio task with blocking work in a thread. At most one job runs at a time and there is no queue. Evaluation batch runs are **CLI-only**, and the API cannot start them. Run history comes from scanning `runs/*/manifest.json` (plus `metrics.json` / the single-run result); there is no database. When the server starts, any single run left in `running` state is marked `interrupted`, and a `run_end` event is written.

**Endpoints** (JSON; pydantic response models; OpenAPI exported to `api-contract/openapi.json`):
- F1:
  - `GET /api/health` → `{status: "ok", model_reachable: bool, model_digest_ok: bool, evaluator_ready: bool}`
  - `GET /api/queries` → `{items: [{query_id, query}]}` (180, in order; only PlannerInput fields)
  - `GET /api/queries/{query_id}` → `{query_id, query}`; 404 if unknown
- F2:
  - `POST /api/runs` body `{query_id, seed: int = 0}` → `202 {run_id, status: "queued"}`. Returns `409 {detail, active_run_id | null}` if a job is running or `runs/.model.lock` is held (for example by a CLI batch), and `404` for an unknown query_id. It uses `configs/single.yaml` (identical to baseline.yaml except `kind: single`, `queries: [id]`, `seeds: [seed]`), so single runs share the baseline `config_hash` semantics.
  - `GET /api/runs/{run_id}` → `RunDetail`
  - `GET /api/runs/{run_id}/events` → `text/event-stream`. It sends `event: snapshot` (RunDetail) immediately, `event: stage` `{stage}` on each change (`queued → generating → parsing → evaluating → done`), and finally `event: done` (RunDetail) or `event: error` `{message}`, then closes. It sends a `: ping` comment every 15 s. For a finished run it sends `snapshot` then `done` and closes. Polling `GET /api/runs/{id}` is the supported fallback.
- F3:
  - `GET /api/runs?limit=50&before=<run_id>` → `{items: [RunSummary], next_before: run_id|null}`, newest first, both kinds
  - `GET /api/runs/{run_id}/items?seed=<n>` → `{items: [{query_id, seed, delivered, final_pass, commonsense_pass, hard_pass}]}` (batch runs)
  - `GET /api/runs/{run_id}/items/{query_id}/{seed}` → `ItemDetail`

**Schemas:**
- `DayPlan {day, current_city, transportation, breakfast, attraction, attractions: [str], lunch, dinner, accommodation}`. `attractions` is `attraction` split on `;`, trimmed, with empty strings and `-` removed, so the web client does no parsing.
- `Constraint {key, label, group: "commonsense"|"hard", status: "pass"|"fail"|"not_applicable"|"not_evaluated", message: str|null}`
- `Usage {input_tokens, output_tokens, thinking_tokens, load_ms, prefill_ms, generation_ms, total_ms, wall_ms}`
- `ItemDetail {query_id, seed, query, delivered, failure_reason, plan: [DayPlan]|null, constraints: [Constraint], commonsense_pass, hard_pass, final_pass, usage: Usage, raw_output: str}`
- `RunDetail {run_id, kind, status: "queued"|"running"|"succeeded"|"failed"|"interrupted", stage, created_at, finished_at, config_hash, model: {tag, digest}, prompt_version, error: str|null, item: ItemDetail|null (single), summary: {progress: {done, total}, metrics: {<official key>: {per_seed: {seed: value}, mean, sd}}}|null (batch)}`
- `RunSummary {run_id, kind, status, created_at, query_id|null, seed|null, final_pass|null, delivered|null, headline: {final_pass_rate_mean, delivery_rate_mean}|null}`

**UI (web/, React + Vite + TypeScript; no Leaflet or Recharts).** Exactly five features, each built only after its endpoint exists on `main`:
- W1 query picker (searchable list of the 180 queries, from F1)
- W2 run button with live stage (SSE, falling back to polling), and day-by-day plan cards (F2)
- W3 pass/fail per constraint, grouped commonsense/hard with status badges and message tooltips (F2)
- W4 tokens and latency panel (F2)
- W5 run history list, opening a single run's detail or a batch run's metrics table and item list → item detail (F3)

Types are generated from `api-contract/openapi.json` with `openapi-typescript` into `web/src/api/types.gen.ts`. The dev server proxies `/api` to `127.0.0.1:8000`. There is no global state library; use React state plus `fetch`/`EventSource`. The UI never shows evaluator-only query fields except through `constraints`.

## D9 (i). Repo layout, path ownership, build order

**Sessions:** `architecture` (this one), `foundation`, `data-eval`, `model`, `api`, `web`.

```
tripartite/
├── ARCHITECTURE.md                      architecture
├── assumptions.md                       architecture
├── README.md  LICENSE  NOTICE           foundation
├── Makefile                             foundation
├── pyproject.toml  uv.lock  .python-version  foundation
├── .gitignore  .editorconfig            foundation
├── .github/ (workflows/ci.yml, pull_request_template.md)   foundation
├── configs/  (stack.yaml, baseline.yaml, smoke.yaml, single.yaml)   model  [smoke.yaml query_ids = output of `tripartite eval smoke-ids`]
├── prompts/  (sole_planning_direct_v1.txt)    model
├── reports/  (context_report.json)            model
├── results/phase1/<run_id>/…                  model
├── api-contract/openapi.json                  api
├── scripts/vendor_check.py                    data-eval
├── scripts/ci/repo_hygiene.py                 foundation
├── src/tripartite/
│   ├── __init__.py  cli.py                    foundation
│   ├── runlog/  (schema.py, schema.json, writer.py, reader.py, mlflow_sync.py, cli.py)   foundation
│   ├── data/    (planner_inputs.py, download.py, manifest.py, cli.py)                    data-eval
│   ├── evaluation/ (records.py, bridge_client.py, constraints.py, aggregate.py, cli.py)  data-eval
│   ├── config.py                                                                         model
│   ├── llm/     (ollama_client.py, fake_client.py, chat_template.py, tokenizer.py, errors.py, doctor.py)   model
│   ├── planner/ (prompt.py, sole_planner.py)                                             model
│   ├── parse/   (text_plan_parser.py)                                                    model
│   ├── pipeline/ (run.py, resume.py, lock.py, metrics.py, reproduce.py, cli.py)          model
│   └── api/     (app.py, jobs.py, sse.py, schemas.py, routes_queries.py, routes_runs.py, history.py, cli.py)   api
├── evalenv/ (pyproject.toml, uv.lock, bridge.py)      data-eval
├── vendor/travelplanner/ (VENDOR.lock, VENDOR.md, upstream files)   data-eval
├── data/MANIFEST.json  (data/raw, data/downloads gitignored)       data-eval
├── tests/
│   ├── conftest.py                     foundation
│   ├── runlog/                         foundation
│   ├── data/  evaluation/  fixtures/eval_golden/   data-eval
│   ├── llm/  planner/  parse/  pipeline/  leak/  fixtures/model/   model
│   └── api/                            api
└── web/  (everything, incl. package.json, package-lock.json, .nvmrc, e2e/)   web
```
Every path belongs to exactly one session. A session MUST NOT edit another session's paths. If it needs a change there, it writes the request under "Architecture questions" in its PR.

**Foundation obligations** (so that no other session needs root files):
- `pyproject.toml` declares all Phase 1 dependencies up front. Runtime: pydantic, pyyaml, httpx, tokenizers, jinja2, huggingface_hub, filelock, typer, fastapi, uvicorn, sse-starlette, mlflow. Dev: pytest, pytest-asyncio, ruff, mypy, import-linter, types-PyYAML. Pick the latest stable versions at creation; `uv.lock` fixes them. Also add import-linter contracts (D3) and pytest markers `local`.
- `cli.py`: a Typer root app that registers sub-apps **lazily by module path**, so missing modules do not break import: `data` → `tripartite.data.cli:app`, `eval` → `tripartite.evaluation.cli:app`, `model` → `tripartite.llm.cli:app`, `run` → `tripartite.pipeline.cli:app`, `log` → `tripartite.runlog.cli:app`, `api` → `tripartite.api.cli:app`.
- `Makefile` targets (exact names; each calls the CLI):

| Target | Command |
|---|---|
| `setup` | `uv sync` · `uv sync --project evalenv` · `npm ci --prefix web` |
| `serve-model` | `ollama serve` with the D4 env (foreground) |
| `pull-model` | `tripartite model pull` |
| `doctor` | `tripartite data verify` · `tripartite model doctor` |
| `data` | `tripartite data fetch` · `tripartite data verify` |
| `measure-context` | `tripartite model measure-context` · `tripartite model calibrate` (the calibration needs `make serve-model` running) |
| `baseline` | `tripartite run start --config $(CONFIG)`, default `configs/baseline.yaml` |
| `baseline-smoke` | `$(MAKE) baseline CONFIG=configs/smoke.yaml` |
| `resume` | `tripartite run start --resume $(RUN)` |
| `eval` | `tripartite eval rescore --run $(RUN)` |
| `reproduce-check` | `tripartite run reproduce-check --run $(RUN) --run2 $(RUN2)` |
| `test` | `uv run pytest -m "not local"` |
| `test-local` | `uv run pytest -m local` |
| `lint` | ruff check, ruff format --check, mypy, lint-imports |
| `api` | `tripartite api serve` |
| `openapi` | `tripartite api export-openapi > api-contract/openapi.json` |
| `web` | `npm run dev --prefix web` |
| `e2e-local` | `npm run e2e --prefix web` |
| `mlflow-sync` | `tripartite log mlflow-sync --run $(RUN)` |
| `mlflow-ui` | `uv run mlflow ui --backend-store-uri ./mlruns` |

- `.gitignore` (the repository is public, so this is a safety boundary, not tidiness — see §8): `.venv/`, `evalenv/.venv/`, `data/*` with `!data/MANIFEST.json`, `vendor/travelplanner/database/*` with `!vendor/travelplanner/database/README.md`, `runs/`, `mlruns/`, `web/node_modules/`, `web/dist/`, `*.log`, `.env`, `.env.*`, `*.zip`. `results/` is **not** ignored: `results/phase1/<run_id>/{manifest.json,metrics.json,reproduce_check.json}` is committed on purpose, and those three files carry no plan text and no database rows.
- `NOTICE`: TravelPlanner attribution (MIT code, CC BY 4.0 data) and Qwen3 licence reference.

**Shared files across milestones.** Three paths are needed by every session but owned by one: `Makefile`, `.github/workflows/ci.yml` and `pyproject.toml` (foundation). The rule, so that no session ever edits another's path:

1. **Written once, complete, at M0.** Foundation writes the final Makefile, CI workflow and dependency list from this document, covering every milestone. Nothing later is expected to change them.
2. **Guard by existence; mandatory on appearance.** Every CI step and Makefile target whose input a later milestone creates is guarded by that path existing (`if: hashFiles('<path>') != ''` in Actions, `test -e` in the Makefile). A guarded step skips with the printed line `skipped: <path> not present yet`, and it is mandatory as soon as the path exists. Paths only ever appear, so no check can be silently switched off, and the CI summary lists what was skipped. Guarded Makefile targets are `setup` (its `npm ci --prefix web` step), `web`, `e2e-local`, `openapi`, `api`, and `serve-model` (which reads the D4 env from `configs/stack.yaml`, created at M3). A guarded step inside a larger target prints the skip line and the target continues; a guarded target invoked by name exits 1 with the same message, so a skip is never mistaken for success.
3. **Package skeleton at M0.** Foundation creates `src/tripartite/{data,evaluation,llm,planner,parse,pipeline,api,runlog}/__init__.py` as empty files, plus empty `tests/{data,evaluation,llm,planner,parse,pipeline,api,leak}/` directories with `__init__.py`. This is a one-time creation: from that commit on, each directory including its `__init__.py` belongs to the owner named in the tree above. It exists so that `mypy` and the D3 import-linter contracts, which name these modules, resolve and run from M0 onwards.
4. **Owner of the vendor integrity check:** the **data-eval** session owns `scripts/vendor_check.py`, together with `vendor/` and `VENDOR.lock` (M2). CI calls it as a guarded step. Foundation owns `scripts/ci/repo_hygiene.py` (§8), which always runs.
5. **Read-only shared paths (the rest of the sweep).** These are owned by one session and consumed by another, always read-only, so nobody needs to edit another's path. The consumer treats a missing file as a clear error, never as a reason to edit: `data/MANIFEST.json` (data-eval → model's `doctor`); `api-contract/openapi.json` (api → web's type generation and the CI drift check); `reports/token_calibration.json` (model → the api job runner, D4 §Before calibration has run); the output of `tripartite eval smoke-ids` (data-eval → `configs/smoke.yaml`, committed by model, D1); and the lock file `runs/.model.lock` plus the run directory layout (D7), which the model and api sessions share by this contract rather than by shared code. `tests/conftest.py` (foundation, M0) holds only the `local` marker registration and the fake-mode environment fixtures; each session adds its own `conftest.py` inside the test package it owns.
6. **Escape hatch.** If a session finds it needs a new dependency, Makefile target or CI step that the M0 versions cannot express as a guarded step, it does not edit those files. It writes the request under "Architecture questions" in its PR. The architecture session updates this document, and the foundation session makes the edit in its own follow-up PR.

**"CI green at M0" means exactly:** `ruff check` and `ruff format --check` pass over `src/` and `tests/`; `mypy src` passes over the empty packages plus `runlog/` and `cli.py`; `lint-imports` runs every D3 contract and they hold vacuously; `pytest -m "not local"` collects and passes the runlog tests (schema round trip, writer/reader, unknown-event-type tolerance) and nothing else; `scripts/ci/repo_hygiene.py` passes; and each guarded step prints its skip line. The web job does not run, because `web/package.json` does not exist yet.

**Build order** (a milestone may start when its dependencies are merged to `main`):

| # | Session | Milestone | Depends on |
|---|---|---|---|
| M0 | foundation | Skeleton, all root files, CI green on an empty package, runlog schema + writer/reader + tests | none |
| M1 | data-eval | `data fetch/verify`, `PlannerInput` loader, test-split refusal, `records.py` | M0 |
| M2 | data-eval | Vendoring + VENDOR.lock, evalenv, bridge, constraints, aggregate, golden fixtures | M0 |
| M3 | model | config.py + configs, Ollama client, fake client, chat template, tokenizer, `doctor`, `measure-context`, `calibrate` + `reports/token_calibration.json` | M1 |
| M4 | model | Prompt v1, parser, pipeline (run/resume/lock/metrics), leak tests → **Phase 0 exit** (`make baseline-smoke`) | M2, M3, **and A-009 confirmed** in `assumptions.md` (or a recorded user decision to proceed). M4 MUST NOT start before that. |
| F1 | api | health, queries, OpenAPI export | M1 |
| W1 | web | Vite skeleton, generated types, query picker | F1 |
| F2 | api | POST runs, job runner, run detail, SSE | M4 |
| W2 | web | Run + live stage + plan cards | F2 |
| W3 | web | Constraint pass/fail | F2 |
| W4 | web | Tokens and latency | F2 |
| F3 | api | History, batch items, item detail | F2 |
| W5 | web | Run history | F3 |
| M5 | model | Full baseline, second run, reproduce-check, results/phase1 → with W1–W5 + `e2e-local`: **Phase 1 exit** | M4, W5 |

Note on M3 vs the A-009 gate: `measure-context` and `calibrate` need the rendered official prompt only to count tokens and to send `num_predict: 1` probes. No plan is generated and no output is used. M3 may therefore create `prompts/sole_planning_direct_v1.txt` and `planner/prompt.py` for that purpose before A-009 is settled. Everything else in M4 waits for the gate. If A-009 fails, `measure-context` and `calibrate` are re-run with the replacement prompt.

The web session never builds against mock data: every component calls an endpoint that already exists on `main`. The backend's fake modes (`TRIPARTITE_LLM=fake`, `TRIPARTITE_EVAL_BRIDGE=fake`) are real backend code paths, and web may use them in development and CI.

# 5. Seams for later phases (named, not designed)

| Seam | What Phase 1 must do (and no more) | Why it matters |
|---|---|---|
| S1 Retrieval events | Keep the reserved `retrieval` event type with empty payload; readers ignore unknown types. | The brief's non-negotiable "every run logs retrievals", Phase 3 per-agent retrieval, and retrieval recall scoring all need retrievals in the same log as calls. |
| S2 Multiple agents per run | `agent_id`, `role`, `round` and `parent_call_id` on every `llm_call`; an `agents` list in the manifest; `query_result.totals` summed over all calls, not one. | Phases 3–4 run 3+ agents and several rounds, and matched budgets are summed per run. |
| S3 Citation fields / record IDs | Keep the evaluator's plan format as an **output** serialization (`plans_seed*.jsonl`), not the internal storage model. Pin the database zip by sha256 (A-013). Do not invent IDs. | The benchmark has no record IDs. A later phase must define them over the pinned database, and citation checks compare cited values against that exact snapshot. |
| S4 Token accounting | Local-tokenizer input, output-visible and output-thinking counts **separately**, plus runtime-reported and cached counts, the tokenizer id@revision on every call, and prefill vs generation time. | Phase 4 must decide whether input tokens count toward matched budgets ("tokens per tokenizer + wall-clock"). It can only do that if nothing was merged earlier. |
| S5 Full-context runs as controls | Manifest records `context_mode: "full"` and `mode`; runs are immutable; raw outputs and rendered prompts (blobs) are kept; `config_hash` is stable. | The non-negotiable "retrieval is always compared against a full-context control" lets Phase 4 reuse the Phase 1 baseline as the control when its config matches, instead of re-running for hours. |
| S6 Sandbox store | The evaluator reads the vendored CSVs. Nothing else in Phase 1 reads the database. | The deferred DuckDB/SQLite port must later be checked for equivalence against these CSVs, so there is only one reference. |
| S7 Mode | `mode: "sole-planning"` is recorded on every run. | Phase 5 two-stage mode must be distinguishable in history and metrics. |

# 6. Pins (the reproducibility set)

| Item | Pin | Where recorded |
|---|---|---|
| Upstream evaluator | `OSU-NLP-Group/TravelPlanner@e52c87f4ac348a3410c46dc3553c519db5ec5e23` | VENDOR.lock |
| HF dataset | `osunlp/TravelPlanner@8736504ecfc31b7f8b7e40122873c337e83fff7c`, files validation.csv and validation_ref_info.jsonl with sha256 | data/MANIFEST.json |
| Sandbox database | database.zip sha256 (first download, A-013) | data/MANIFEST.json |
| Python | exact version in `.python-version` (3.12.x) | repo |
| Python deps | `uv.lock`, `evalenv/uv.lock` | repo |
| Node / web deps | `web/.nvmrc`, `web/package-lock.json` | repo |
| Ollama | exact version | configs/stack.yaml |
| Model | `qwen3:8b-q4_K_M` + full sha256 digest | configs/stack.yaml |
| Tokenizer | `Qwen/Qwen3-8B` tokenizer.json + chat template at a pinned HF revision (downloaded by `tripartite model pull` into `data/tokenizer/`) | configs/stack.yaml |
| Ollama server env | the D4 env vars | configs/stack.yaml; checked by doctor |
| Prompt | `sp-direct-v1` + sha256 | configs/baseline.yaml |
| Parser | `rule-text/v1` | code constant |
| Hardware/OS | recorded, not pinned (chip, macOS, `iogpu.wired_limit_mb`) | manifest env |

# 7. Estimated run cost (for planning, not a gate)

540 calls at roughly 40–60 s each (about 10k prefill tokens and about 1k generated tokens) is about 6–9 hours per full baseline (A-010). Two full runs are needed for Phase 1 exit. Runs are resumable, and the lock prevents UI jobs from interleaving.

# 8. Repository and publication hygiene

The repository is **public**: `github.com/Magnus0320/Tripartite`, with its root at this project's folder (`/Users/abhimanyu/Desktop/tripartite`). `ARCHITECTURE.md` and `assumptions.md` live at the repository root, as the D9 tree shows. The architecture session edits them in place; the user commits. Commit `8205414` contains v0.2.

Because every push is public, and because some of this is a licence and fair-evaluation matter rather than only a privacy one, these are never committed, at any milestone:

1. **Dataset files:** anything under `data/` except `data/MANIFEST.json`, which holds names, revisions and sha256 only. That covers `validation.csv`, `validation_ref_info.jsonl` and every derivative.
2. **Any test-split artefact:** `test.csv`, `test_ref_info.jsonl`, or any path matching `*test*ref_info*`. D3 keeps them off the machine; this keeps them out of git even if one appears locally.
3. **The sandbox database:** `data/downloads/database.zip` and everything unzipped under `vendor/travelplanner/database/` except the upstream `README.md`. It is a third-party download with its own licence (A-017), redistributed by its authors only.
4. **Run output:** `runs/` and `mlruns/` in full — prompts, raw model output, plans, logs. Only the three small `results/phase1/<run_id>/` files are published.
5. **Secrets:** `.env` files, API keys, tokens. The project has no API keys by design (₹0 cap, local models), so any key-shaped string in a diff is a mistake.

Enforcement: the `.gitignore` in D9 covers all of the above; `scripts/ci/repo_hygiene.py` (foundation; runs on every CI run, unguarded) fails the build if any tracked file matches those patterns, if a tracked file is larger than 2 MB (lockfiles excepted), or if a tracked file matches a key-shaped pattern (`sk-`, `hf_`, `ghp_`, `AKIA`). The vendor integrity check (D9 §Shared files, item 4) additionally fails if `VENDOR.lock` lists a `*ref_info*` or `*.csv` path. D3's `test_test_split_forbidden` and `test_no_test_files_on_disk` cover the loading side.

Publishing the repository changes no decision above. The prompts, the vendored evaluator (MIT, attributed in `NOTICE`) and our own code (MIT) are publishable; the data and the runs are not.

# Brief issues

1. **Micro vs macro.** Phase 1 lists "commonsense/hard macro pass rates" only. The official evaluator also produces micro rates, and at 8B scale macro and final rates are near 0. D5 adds micro (approved 2026-09-22).
2. **"Reproducible" is undefined**, and "3 seeds" conflicts with the official temperature-0 decoding. With greedy decoding all seeds are identical. D1 and D4 choose sampling with a metric-tolerance definition. Plan-level identity cannot be guaranteed on this runtime.
3. **Comparability target unstated.** The brief does not say whether Phase 1 numbers should be comparable with published results. They cannot be directly (D2 comparability note: GPT-4 parser, 12k-token cutoff, evaluator fix 2025-11, decoding, model).
4. **"All agent models kept loaded" vs 24 GB.** Three 8B Q4 models with 32k KV caches need about 30 GB against a ~16 GB GPU budget (A-005, A-011). Phase 3/4 must shrink the context (retrieval), share one model, or run agents sequentially. Flagged now so that Phase 1 choices (a single `.model.lock`, NUM_PARALLEL=1) are not mistaken for later-phase requirements.
5. **Two sources of truth for the sandbox.** The architecture says "sandbox in DuckDB/SQLite", but the official evaluator reads the CSVs directly (F1). Any port must be proven equivalent to the CSVs, or citation checks and the evaluator will disagree (seam S6).
6. **In-context example provenance.** The non-negotiable forbids annotated or reference plans. The official prompt embeds an example whose origin is unknown (A-009).
7. **"Every run logs … retrievals"** has nothing to log in Phase 1. It is handled as the empty event type (S1).
8. **Test-set data ships with the upstream repo** (`database/test_ref_info.jsonl`). The brief says the test set stays untouched but does not say how that is enforced. D3 and D5 enforce it by exclusion plus CI checks.
9. **Field list.** Validation contains `budget` (the evaluator needs it), which the supplied field list omits. The brief itself does not list fields, but the boundary non-negotiable depends on the complete list, hence the allowlist in D3.
10. **Proposed items still open in the brief**: the model ("(proposed)") and static replay hosting ("(proposed)"). The model is D4 (approved 2026-09-22). Hosting is not needed for v0.1.
11. **Database download.** The database is a Google Drive link, which cannot reliably be fetched by a script or in CI. D5 makes it a manual step with checksum verification. The brief's Phase 0 "data loading" implies automation.

# Open questions

Still open:
1. If `measure-context` shows the maximum prompt does not fit in 32768 − 4096 − 256 tokens: approve YaRN, lower `num_predict`, or exclude? The default is still to stop and ask. Nothing is excluded silently.
2. A-009: the user will check by hand on the HF viewer whether the official prompt's example (`F3633413`, "Nagaland's Kitchen") appears in a train `annotated_plan`. No Code session downloads train.csv for this. M4 waits on the answer.

Resolved 2026-09-22:
- D4 (model and serving): approved as written.
- D5 (micro alongside macro and final): approved.
- D6 (official direct prompt, verbatim): approved on condition that A-009 holds.
- Extra temperature-0 pass for comparability with published numbers: declined, not planned.
- Repository licence: MIT (`LICENSE`, foundation session).

Resolved 2026-09-23:
- The repository is public, at `github.com/Magnus0320/Tripartite`, rooted at this project's folder. §8 states what is never committed.
- `num_ctx` is a pin at 32768, and `make measure-context` is a gate (D4).
- Shared files across milestones: guarded steps written once at M0, the package skeleton at M0, and `scripts/vendor_check.py` owned by data-eval (D9).
- R3 tolerance: kept at ±2.0 pp. A-016 remains the trigger to revisit it after the first full run.
