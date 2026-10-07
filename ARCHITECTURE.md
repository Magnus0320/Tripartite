ARCHITECTURE.md · v0.11 · 2026-10-07

# Changelog

- v0.11 (2026-10-07): records FU-26, FU-27 and FU-29 (`f62fe29`, merged in `dba2ac2`, PR #14) as merged, with CI green. **Open question 1 is resolved:** the runner prompt cache is off for M5 (`LLAMA_ARG_CACHE_RAM: "0"`, approved 2026-09-29, verified by FU-26). D4 records the new `runtime.env` key, doctor's `OLLAMA_*`-only env comparison and its runner-prompt-cache check, and the measured effect. **v0.10's expected time saving is withdrawn:** the bookkeeping gap vanished (A-044 confirmed), but wall time did not improve, so M5a's estimate stays at about 8.2–8.5 h per run. Memory is much better: the runner sits at 10.25–10.28 GB and swap stayed flat. New §9 records two user decisions. First, a budget rule: ₹0 API spend forever, plus a capped infrastructure budget of up to ₹500 a month from Phase 6, which replaces the brief's paid-hosting exclusion for the Phase 6 demo only. Second, the Phase 6 demo on AWS, named as seam S8 only. A note defers Phase 4 cloud GPUs. The model session's AQ1–AQ11 and all its deviations are ratified as recommended: D7 §Resume gains the clean-tree, same-commit, `runtime.env` and `allow_dirty` rules, and FU-30 (foundation, with M6) declares `allow_dirty` in `RunStart`. **M5a is specified:** the exact `reproduce_check.json` schema, how R1, R2 and R3 are computed, the identity diagnostic overall, per seed and for first calls, the warnings, output and exit codes, and the rule that any failure stops M5a for an architecture question. M5a is split into M5a.1 (`reproduce-check` PR), M5a.2 (two runs from one pinned commit in a dedicated worktree, no code changes) and M5a.3 (results PR), with a resume procedure. `reproduce_check.json` lives outside both run directories, because succeeded runs are immutable. Readiness lists cover M5a.1–M5a.3, F2, W1, W2, M5b and M6. New assumptions A-047 to A-051, including the open observation that the two smoke runs produced identical scores (A-051).
- v0.10 (2026-09-29): **Phase 0 exit met.** Records FU-21/FU-22 (`39c8aeb`, merged in `9df47a8`, PR #12) and M4 with FU-25 (`4729292`, merged in `af77514`, PR #13) as merged. The Phase 0 exit is recorded with M4's evidence: smoke run `20260929T041153Z-batch-9b45ed9e-f6c1`, 27/27 delivered; `make eval` byte-identical on 7 files; CI green on the M4 PR. The smoke scores are a pipeline check on 9 queries, not a result. M4's architecture questions are ratified: AQ1 upholds §8.4 and strikes D2 7(c); AQ2 writes the pinned round-trip counts into D2; AQ3 fixes the `per_plan_eval` line format (D7); AQ4 and AQ5 reword D7 so that only succeeded runs are immutable and failed or interrupted runs resume by appending, against a stated set of pins; AQ6–AQ11 are accepted as built; AQ12 is recorded and explained. All M4 deviations are accepted. New facts from the relayed runner log: Ollama 0.33.2's `llama-server` keeps a host-RAM prompt cache of up to 8,192 MiB by default. It explains AQ12, part of the swapping and a per-call save cost of 2.7–3.6 s; D4's "known by construction" is corrected; `--context-shift` makes the pre-flight check permanent; the GGUF blob hash is recorded as a derived pin. **Disabling that cache with `LLAMA_ARG_CACHE_RAM=0` for M5 is proposed, NEEDS APPROVAL** (Open question 1; FU-26 is conditional on it). Fake mode is synthetic-data-only (FU-27, FU-28). D3 gains the medium-level transportation note, and M5 gets an operations checklist and a clean-commit guard (FU-29). M5 is split into M5a (the two full runs, reproduce-check and results; may start before the UI) and M5b (`e2e-local` and the Phase 1 exit). Readiness lists are given for F2, W1, M5a, M5b and M6. New assumptions A-040 to A-046.
- v0.9 (2026-09-28): **M4's gate is cleared.** A-009 is confirmed by the user's SQL check of the train split (A-030), so D6's condition is met. Records M3 (`88d9555`, merged in `2c2367c`), the data-eval follow-ups FU-16/18/20/24 (`0efdea5`, merged in `802e575`) and the model follow-ups (`e7043f7`, merged in `28b6a01`) as merged. M3's measurements are recorded as facts and new entries. The GPU budget is 17.8 GiB, not ~16 GB (A-031, superseding A-005). Calibration mode is `total`, so the post-check is plain equality: A-018, A-019, A-021 and A-022 are confirmed (A-032 to A-035), and A-020 is retired as not applicable (A-036). The context measurements confirm A-006 (A-037): max 20,214 tokens, headroom 8,202. The memory measurement confirms A-011 (A-038): 9.23 GiB loaded, KV cache 4,608 MiB. The v0.8 health-check assumptions are confirmed (A-039, confirming A-029). F8 is corrected. M3's run-config layout is recorded (D4 §Run configs), and all seven M3 deviations, all four model follow-up deviations and all six data-eval follow-up deviations are accepted. D4 and the M3 row say that the fake tokenizer and template arrived as a model follow-up after M3, because M3 was built against v0.7. FU-19 is corrected to use `TRIPARTITE_LLM` unset, since `llm_mode()` accepts only `fake`, `ollama` or unset. In fake mode, `measure-context` and `calibrate` must refuse to overwrite the committed reports (FU-25). D8 records that `evaluator_ready()` needs `make setup`. D3 records what M4 must rewrite when it aggregates synthetic rows. Both open questions are resolved. New §M4 readiness list in D9.
- v0.8 (2026-09-28): records FU-13/FU-14 (`3083c05`, merged in `57bb32d`), M2 (`5385ea2`, merged in `8378f2a`) and F1 (`d408cdd`, merged in `af2f1b9`) as merged. Decisions that block M4: re-scoring becomes `tripartite run rescore` in the model session's pipeline (M4), because R1 needs byte-identical output from the same code that scored the run; `make eval` keeps its name and calls it (FU-21). Fake mode gets a supported tokenizer in `src/tripartite/llm/` (byte-level, `fake-bytes@v1`) with a fixed Qwen3-format chat template, selected by `TRIPARTITE_LLM=fake`, so M4 and F2 tests never need the real tokenizer (D4, M3). The shared synthetic set is extended so that every evaluator-only field except `days` carries a detectable canary on every row (FU-16); `days` is excluded from `test_canary_no_leak` and covered structurally (D3). `/api/health`'s three readiness flags are defined: two cheap model checks (`/api/version` and `/api/tags`, 1 s timeouts, no model load) and a stat-only evaluator check, all `true` in fake mode (D8; FU-17 to FU-19). M2 rulings: the golden `queries.jsonl` is a named §8.1 exception; `not_evaluated` now also covers undelivered plans; the subset hard-micro denominator is accepted; `evaluation.aggregate.Metrics` is renamed `OfficialScores` (FU-20); the three bridge deviations are accepted and written into D5; A-014 is confirmed (A-027); A-017 is narrowed but not closed (A-028); the upstream drift in `example_evaluation.jsonl` line 162 is recorded (D5); `evalenv/uv.lock` is checked in CI and synced `--locked` (FU-22). FU-13/FU-14 and F1 rulings recorded, including a 503 for missing data on `/api/queries` (FU-23). A-027 confirms A-014, A-028 narrows A-017, and A-029 records the health-check assumptions about Ollama's endpoints. New follow-ups FU-16 to FU-24.
- v0.7 (2026-09-26): records M1 as merged (`c5190c5`, merged to main in `7d5303f`) and FU-11/FU-12 as merged (`3cdc1a5`, merged in `ea4c8ab`). M1's questions: `tripartite eval smoke-ids` is now an M2 deliverable, and `configs/smoke.yaml` moves from M3 to M4, so M3 no longer waits on it (build order). Other sessions' tests get planner inputs through a documented `TRIPARTITE_DATA_DIR` environment variable plus a shared synthetic data set in `tests/fixtures/synthetic_data.py`, both owned by data-eval; F1, M3 and M4 must use them, and F1 and M3 now depend on FU-13 and FU-14 (D3, D9). D3 test 1 stays in `tests/data/` only, and D3 now names an owner for every boundary test. M1's two deviations on A-007 (git blob ids, the in-memory city list) are accepted, and A-007 is confirmed by the new entry A-024. FQ4: the warm-up rule is "null **only when** `role == "warmup"`", as the code enforces, and D7 §Where the rules live is corrected to match. Item 3 was checked against source at `e52c87f4`: `eval.py` converts `local_constraint` from a string itself, so the bridge's records file must hold the raw `load_dataset` row, field by field (D5 §Bridge records file). That needs `EvalRecord` to keep the verbatim string (FU-15). A-025 records the `load_dataset` field types; they were then confirmed from the dataset's feature metadata at `8736504e` (A-026, superseding A-025). Before commit, the draft was checked and corrected: the evaluator-exception bullet moved back from the records-file list to §Bridge, the description of how `commonsense_constraint.py` uses the numeric fields was corrected (it compares and multiplies them; it never calls `range()`), the Follow-ups preamble now records the FU-11/FU-12 merge, and D1 item 3 and D3 now state the M1-AQ1 milestone and the two A-007 rulings in the body, not only here.
- v0.6 (2026-09-26): the sandbox database is pinned. The user's first download (2026-09-25) is `sandbox_database.zip`, 59,039,278 bytes, sha256 `de345b0c243cd8c85355a264c5124db5db275327d2a38fa8685c6e69fabb650b`, now the trust-on-first-use pin (A-013) in D5 and §6. The upstream file name is kept, so `data/downloads/sandbox_database.zip` replaces `database.zip` everywhere, and no rename is needed. D5's unpacking is rewritten, because the zip nests everything under a top-level `database/` folder: `tripartite data fetch` (data-eval, M2) strips that prefix, skips `__MACOSX/`, `.DS_Store` and `._*`, refuses unsafe or unexpected entries, and checks the result against exactly 8 expected files, pinning sizes in code and per-file sha256 in `data/MANIFEST.json`. The evaluator's reads were confirmed from source at `e52c87f4`: 6 of the 8 files; `citySet.txt` and `stateSet.txt` are unpacked but never read. The vendor integrity check now covers only git-tracked files, and the unpacked database is verified by `tripartite data verify` instead (D1, D9, item 4). Foundation questions: the `data/` hygiene rule now matches only paths under a `data/` directory (FQ1); `schema.json` stays structural, with the conditional rules carried as field descriptions (FQ2); the schema checks `ok <= attempted` and the `failure_rate` value (FQ3). Both of foundation's additions are accepted. FU-8 to FU-10 are marked merged (`c1515f5`, merged to main in `57f2a74`), and the FU-1 to FU-5 citation is corrected to cite its merge commit `458c34b`. New follow-ups FU-11 and FU-12.
- v0.5 (2026-09-23): **sync repair first.** The v0.4 committed to the repo (`9b2f28f`) was an intermediate draft. Its `ARCHITECTURE.md` still listed a follow-up FU-7 (add `mlflow` to `pyproject.toml`), which the final v0.4 withdrew because M0 already pins `mlflow`; that is why the v0.4 entry below says "seven" follow-ups. Its `assumptions.md` was not updated at all and stopped at A-021. v0.5 is built on the final v0.4 (the Project copy), `assumptions.md` now has A-022 and A-023 appended exactly as in the Project copy, and FU-7 is retired, so new follow-ups start at FU-8. No Code session acted on FU-7, so nothing needs undoing. Then the foundation session's questions on FU-1 to FU-5: `make serve-model` creates `runs/` and fails fast if `serve-env` fails, and the server log path is a fixed constant rather than a `stack.yaml` key (D4; AQ2–AQ4). `RunManifest.created_at` and `.updated_at` are non-null and `finished_at` is set exactly when the status is terminal (AQ5). The seven `run_end.counts` keys are enforced by the schema (AQ6). The five choices in AQ7 are confirmed, with `parse.failure_rate` defined as null when nothing was attempted (D7). `tests/scripts/test_repo_hygiene.py` is added to D9 as a foundation path, and "CI green at M0" now includes it (AQ8). The three extras in the follow-up PR are accepted (§8, D9, D7). New follow-ups FU-8 to FU-10, all foundation's.
- v0.4 (2026-09-23): answers M0's 12 architecture questions and accepts all 6 of its deviations. New in D4: the `configs/stack.yaml` schema and the `tripartite model serve-env` contract (Q1). New in D7: the `manifest.json` model and its five statuses (Q5), the `metrics.json` / `metrics_seed*.json` schemas, MLflow naming, tags and idempotency with sync now manual-only and scheduled to a new milestone M6 (Q4), the resume tail-repair rule (Q10), and the confirmed nullable and closed-set field decisions (Q9). §8 and D9: the test-split pattern now matches the **file name**, not the path, and only data extensions, which unblocks data-eval's own tests (Q6); `/runs/` and `/mlruns/` are anchored (Q7); `.claude/settings.local.json` and `.claude/worktrees/` are listed (Q11); the guard list gains `evalenv/pyproject.toml` and names `src/tripartite/api/cli.py` for `api` and `openapi` (Q2, B1); guarded targets are described as make exit 2 (Q12, B2); `llm/cli.py` belongs to the model session (Q3); the Typer and mypy conventions and the `make test-local` empty-collection rule are recorded (C). §6 pins Python 3.12.13 (B6). Deviations B3–B5 accepted as written. A new "Follow-ups" section lists the seven file changes this version requires, all owned by the foundation session. A-022 and A-023 added.
- v0.3 (2026-09-23): the repository is public, its root is this project's folder, and its remote is `github.com/Magnus0320/Tripartite`; commit 8205414 holds v0.2. New §8 (repository and publication hygiene) states what is never committed and names the check that enforces it; D9's `.gitignore` and vendor lines were tightened to match, and `scripts/` was added to the tree with owners. Open question 5 is fully closed. Fix: `num_ctx` is now **fixed at 32768** rather than computed, so nothing can disagree with the running server or invalidate the calibration; `make measure-context` has an explicit two-step order, and the measurement is a pass/fail gate, not an input (D4, D1). Fix: shared files across milestones. M0 creates the empty package skeleton, every CI step and Makefile target written at M0 is guarded by the existence of its input and becomes mandatory as soon as that input exists, `scripts/vendor_check.py` is owned by the data-eval session, and "CI green at M0" is defined exactly (D9 §Shared files). The same rule, plus a list of read-only shared paths (MANIFEST, openapi.json, the calibration report, smoke-ids, the model lock, conftest), resolves the other cross-session paths found in a sweep of D9.
- v0.2 (2026-09-22): user decisions recorded. D4 and D5 approved. D6 approved on condition that A-009 holds, and M4 is now gated on A-009 (D9 build order). A note there lets M3 use the official prompt only for token counting and calibration probes. Open question 4 (extra temperature-0 pass) declined. Licence MIT (open question 5; public/private still open). Open questions 6 and 7 unchanged in substance: R3 stays at ±2.0 pp, and A-016 remains the trigger to revisit it. NEEDS APPROVAL markers removed and Open questions updated. Fix: the tokenizer-agreement check and the truncation post-check assumed uncached calls, but every planner prompt shares the official instruction and example before `{text}`, so later calls hit the prompt cache. Both checks are redesigned in D4 around a Phase 0 calibration (`tripartite model calibrate`, run by `make measure-context`), cold probes made uncached by unloading the model, a unique-nonce warm-up, and a per-call bound that uses the token prefix shared with the previous prompt. Before calibration, real-model runs refuse to start. The measure-context row of the Makefile table, D1 Phase 0 exit item 2 and milestone M3 were updated to match. A-018–A-021 added; A-018 supersedes A-002 and A-019 supersedes A-003. Brief issues 1 and 10 no longer say "pending approval".
- v0.1 (2026-09-22): initial. Covers Phases 0 and 1 in full. Later phases appear only as named seams.

# 0. How to use this document

- This file is the build contract for the Claude Code sessions. Only the architecture session edits it. If you are a Code session and something here is ambiguous, wrong or missing: do not guess. Implement nothing for that point, write it under "Architecture questions" in your PR description, and carry on with the rest of your work.
- "MUST" is a requirement. "SHOULD" is a default that you may break only with a reason written in the PR. Anything not listed here is out of scope for v0.1.
- Assumptions are referenced as A-xxx and live in `assumptions.md`, which is append-only.
- Decisions are D1–D9, one for each item a–i in the architecture request. Decisions marked **NEEDS APPROVAL** are provisional. Build them as written, because they are the default, but Phase 1 exit numbers are not final until the user approves. As of v0.2 no decision was marked; D6's A-009 condition was met in v0.9. v0.10 marked one proposal NEEDS APPROVAL (the runner prompt cache for M5); it was approved on 2026-09-29 and built as FU-26. As of v0.11 nothing is marked.

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
| F8 | In `database/validation_ref_info.jsonl` (repo), each line is one JSON object. **Corrected in v0.9 (M3's measurement):** counted without the trailing newline, lines run 11,706 to 51,627 characters, and the nearest-rank 95th percentile is 44,590. The v0.1 figures (11,707 to 51,628, p95 45,002) counted the newline and used a different percentile index. The median was about 26,810. | Measured on the file; corrected by M3's `reports/context_report.json` |
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

**Status: met (v0.10).** Evidence from M4 (`4729292`, merged in `af77514`, PR #13):
- **Item 1:** `make setup && make data && make pull-model && make doctor` exit 0. Doctor shows the context report and the token calibration (mode `total`) as valid, and `data/MANIFEST.json` is unchanged.
- **Item 2:** met by M3's committed `reports/context_report.json` and `reports/token_calibration.json`, which doctor reports as valid. The local tests `test_the_committed_context_report_reproduces` and `test_tokenizer_agreement` pass. The commands were not re-run.
- **Item 3:** `make baseline-smoke` exits 0: run `20260929T041153Z-batch-9b45ed9e-f6c1`, 27/27 delivered, 24 min 50 s.
- **Item 4:** every D7 file is present (`reproduce_check.json` is M5's), `metrics.json` has `"subset": true`, and the truncation scan is clean (0 `truncating input prompt`, 0 WARN or ERROR lines).
- **Item 5:** `make eval RUN=20260929T041153Z-batch-9b45ed9e-f6c1` exits 0 with 7 files byte-identical, and a manual `cmp` agrees.
- **Item 6:** CI green; all of the M4 pull request's checks passed before it was merged.
- The smoke run's scores (for example final pass rate 0.074 mean over 9 queries) are a **pipeline check, not a result**. They are never quoted as Phase 0 or Phase 1 numbers.
- The smoke run was `git_dirty`; M5's full runs must not be (D9 §M5 operations, FU-29).

1. `make setup && make data && make doctor` succeed on the M4 Pro.
2. `make measure-context` runs its two steps in order (D4 §Context measurement). Step 1 writes `reports/context_report.json` for all 180 validation queries and **fails** unless `max(prompt_tokens) + num_predict + 256 ≤ 32768`. Step 2 writes a valid `reports/token_calibration.json` (D4 §Token calibration), with tokenizer agreement passed on every cold probe and a classified cache mode.
3. `make baseline-smoke` exits 0. It runs `make baseline CONFIG=configs/smoke.yaml`: **9 queries × 3 seeds (0, 1, 2) = 27 calls**. The 9 queries are one per (level × days) cell (easy/medium/hard × 3/5/7). Each is the lowest-index query in its cell. The data-eval session provides `tripartite eval smoke-ids` in **M2** (the first M2 deliverable; v0.7, M1-AQ1), which computes them from the EvalRecords and prints them. The model session commits its output as explicit `query_ids` in `configs/smoke.yaml` in **M4**, so M3 does not wait on it. Selecting on `level`/`days` is an evaluator-side act done once, offline; the planner never sees those fields.
4. The smoke run directory contains every artifact listed in D7 §Run directory, including `metrics.json` computed by the subset aggregator (D5) and flagged `"subset": true`.
5. `make eval RUN=<smoke run>` re-scores it and produces byte-identical `metrics.json` and `per_plan_eval_seed*.jsonl` (R1 below). `make eval` runs `tripartite run rescore --run <id>`, built by the model session in M4 inside `pipeline/` (v0.8, item 1a): re-scoring must reuse the exact code path that scored the run, or R1 would test two implementations against each other. It reads the run's stored `plans_seed*.jsonl`, never re-parses or re-generates, writes into `runs/<run_id>/rescore-<UTC ts>/`, compares every re-written file byte for byte with the original, prints each mismatch, and exits non-zero on any difference.
6. CI is green on `main`.

### Phase 1 exit (all must hold)
1. `make baseline` (configs/baseline.yaml: all 180 queries × seeds 0, 1, 2 = 540 calls) completes with no hard errors, possibly after `make resume`.
2. Per seed: the official `eval_score` output (six official keys, verbatim) is in `metrics_seed{n}.json`. `metrics.json` holds per-seed values, mean and sample SD (ddof=1) for final pass rate, commonsense macro/micro, hard macro/micro and delivery rate. It also has input, output and thinking tokens, and load/prefill/generation/total/wall latency per query (mean, median, p95).
3. Reproducibility per the definition below: R1, R2 and R3 pass for a second full run, checked by `make reproduce-check RUN=<first> RUN2=<second>`.
4. `results/phase1/<run_id>/` (manifest.json, metrics.json, reproduce_check.json) is committed for both runs.
5. UI: `make e2e-local` passes. It drives the real stack in the browser for 3 query_ids drawn with a fixed RNG seed (42) from the 180: pick query, run, see day cards, see pass/fail per constraint, see tokens and latency, see the run in history. The CI API test also shows that every one of the 180 query_ids can be started and completes with the fake LLM, on the **synthetic** data set (fake mode is synthetic-only, D4 §Fake mode and data, v0.10).

### Definition of "reproducible"
- **R1, re-scoring (required, exact).** Re-running evaluation on stored parsed plans gives byte-identical `metrics_seed*.json` and `per_plan_eval_seed*.jsonl`.
- **R2, re-parsing (required, exact).** Re-running the parser on stored raw outputs gives byte-identical parsed plans.
- **R3, regeneration (required, tolerance).** A fresh run with an identical `config_hash` on the same pinned stack gives, for each of the six official metrics, a 3-seed mean within **±2.0 percentage points** of the first run. `reproduce_check.json` also reports, as a diagnostic with no threshold, the fraction of the 540 (query, seed) pairs whose raw output is byte-identical, **overall, per seed, and for each seed's first call** (v0.11, A-051). The exact computation is D9 §M5a: `reproduce-check`.
- Alternatives considered: (i) identical plans for every (query, seed). Rejected as an exit gate: Ollama gives no determinism guarantee on Metal across prompt-cache states or runtime restarts (A-001), so the gate would depend on something outside our control. It is kept as a diagnostic. (ii) Metrics-only with no R1/R2. Rejected because it cannot tell evaluator or parser nondeterminism from model noise. ±2 pp is about 3.6 queries out of 180 at the macro level. Micro rates have larger denominators.
- Pins required for R1–R3 are in §6. `make doctor` MUST fail if any runtime pin differs from `configs/stack.yaml`.

### CI (GitHub Actions, ubuntu-latest; no model, no database, no HF network)

The whole workflow is written once, by the foundation session at M0, and every step that depends on a path a later milestone creates is **guarded by that path's existence** (D9 §Shared files across milestones). A guarded step skips while its input is absent and is mandatory from the moment the input appears.

- **python job (always runs):** uv (pinned) and Python from `.python-version`. Runs `ruff check`, `ruff format --check`, `mypy src`, `lint-imports` (import-linter contracts, D3), the repository hygiene check (§8) and `pytest -m "not local"` with `TRIPARTITE_LLM=fake` and `TRIPARTITE_EVAL_BRIDGE=fake`. Guarded steps inside this job:
  - vendor integrity check, `python scripts/vendor_check.py` — guard: `vendor/travelplanner/VENDOR.lock` exists (M2). Every **git-tracked** file under `vendor/travelplanner/` matches the lock (sha256), and every lock entry is tracked and present. The lock lists no path matching `*ref_info*` or `*.csv`, and no such file is committed under `vendor/`. Untracked, ignored files — the unpacked database — are outside this check (D9 §Shared files, item 4);
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
7. Golden tests: (a) round trip: render each delivered plan in `vendor/.../postprocess/example_evaluation.jsonl` into the official text format and parse it back; (b) hand-written fixtures for every rule and warning.
   - **7(c) is struck (v0.10, M4 AQ1).** It asked for the smoke run's raw outputs to be committed as fixtures. That contradicts §8.4 (raw model output is never committed), and those outputs quote sandbox-database rows (A-028). Parser coverage comes from 7(a) and 7(b) alone.
   - **7(a) compares a projection (v0.10, M4 AQ2).** The upstream file cannot round-trip literally, so the test compares each plan with the projection the official text format can express, and pins these counts of the file at `e52c87f4`: 161 delivered plans; 123 of them key days as `day`, not `days`; 4 days lack an `attraction` key; some day dicts carry extra keys (dropped by the projection, count pinned in the test); and 2 dicts have no integer day. A change in any pinned count fails the test.
8. **Corner cases, as built in M4 (accepted v0.10, AQ10):**
   - an orphan line before a day's first field is dropped;
   - a continuation line of an ignored duplicate field is dropped with it;
   - `$` is deleted before whitespace is stripped;
   - every closed `<think>…</think>` block is removed, and their contents are joined into `thinking_text`; an unclosed `<think>` is left in the text;
   - warnings are emitted per occurrence, except `day_sequence`, which is emitted once per plan.

**Non-delivery precedence (as built in M4, accepted v0.10, AQ8).** `failure_reason` is `llm_error` if the call failed after retries, else `length_no_plan` if `done_reason == "length"` and the parser found no plan, else the parser's own reason. An `EvaluationError` is not a non-delivery: it writes an `error` event and aborts the run with no `query_result` for that pair, so a resume re-evaluates it.

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
- `EvalRecord` (all columns, with `local_constraint` parsed by `ast.literal_eval`, never `eval`, and from FU-15 also kept as its verbatim string) lives in `src/tripartite/evaluation/records.py`, not in `tripartite.data`.
- **Row alignment is confirmed (A-024, confirming A-007; M1).** Both of M1's deviations are accepted. (1) File identity was checked by git blob id rather than sha256, because GitHub exposes no sha256 for a plain blob; a blob id is a SHA-1 over the exact bytes, so equal ids mean identical files, and the sha256 pins stay in `data/MANIFEST.json`. (2) `tests/data/test_ref_info_alignment.py` reads `citySet_with_states.txt` in memory from the zip verified against the D5 pin, without unpacking it; this keeps M1 independent of M2's unpacking. It passes 180/180, and fails 162/180 with the lines shifted by one, so it discriminates.
- **Import contracts** (import-linter, in `pyproject.toml`; CI fails on violation): `tripartite.planner`, `tripartite.llm` and `tripartite.parse` MUST NOT import `tripartite.evaluation` or `tripartite.api`. `tripartite.data` MUST NOT import `tripartite.evaluation`. The runtime (`tripartite.pipeline`) may import both sides, but passes only `PlannerInput` to `tripartite.planner`.
- `tripartite.planner.render_prompt(inp: PlannerInput) -> RenderedPrompt` raises `TypeError` unless `type(inp) is PlannerInput`.

**Test split refusal.**
- `load_planner_inputs("test")` and `load_eval_records("test")` raise `TestSplitForbiddenError` before any I/O. Any split other than `"validation"` raises `ValueError` (train is not needed in Phase 1 and carries annotated plans).
- The downloader fetches by explicit filename from the allowlist `{"validation.csv", "validation_ref_info.jsonl"}` via `huggingface_hub.hf_hub_download(repo_id="osunlp/TravelPlanner", repo_type="dataset", revision=<pinned>, filename=…)`. It MUST NOT use `snapshot_download` or `datasets.load_dataset`.
- The vendored evaluator excludes `database/test_ref_info.jsonl` and `train_ref_info.jsonl` (D5).
- The evaluator bridge refuses any `set_type` other than `validation`.

**Tests that prove the boundary.** Each test has exactly one owner and one location (v0.7, M1-AQ3). Tests 1, 4 and 5 test data-eval's own types and files and live in `tests/data/`. Tests 2 and 3 exercise the planner path and live in `tests/leak/` (model session). The model session does **not** copy test 1: it would test the same dataclass twice, and D9's ownership rule means only data-eval may change that dataclass anyway. Test 6 is foundation's `pyproject.toml`.
1. `test_planner_input_fields` (`tests/data/`, data-eval, merged in M1): the dataclass fields are exactly `{"query_id", "query", "reference_information"}`.
2. `test_prompt_purity` (CI, over committed fixtures; plus `local` over all 180): for every input, the rendered prompt bytes equal `chat_template(PLANNER_TEMPLATE.format(text=ref, query=query))` built independently in the test. The prompt is therefore a pure function of the two allowed fields.
3. `test_canary_no_leak` (CI, `tests/leak/`, model, M4): use the shared synthetic data set (D3 §Planner inputs in other sessions' tests). From FU-16, **every evaluator-only field except `days` holds a detectable canary on every row** (v0.8, item 1c): `org`, `dest`, `level`, `date` and the CSV's own `reference_information` column as `CANARY_` strings; `budget`, `visiting_city_number` and `people_number` as unique numbers of at least eight digits; and `local_constraint` with at least one canary string on every row, while the rows still vary which keys are `None`. `canaries(i)` lists all of them for row `i`. Their `query` and `reference_information` do not contain the canaries. Run the full pipeline (`pipeline.run_one`) with the fake LLM client, which records every request body byte for byte, and assert that no canary appears in any recorded request.
   **Scope.** `days` is excluded: the evaluator needs it in {3, 5, 7}, so its value is a single digit that no substring check can detect. It is covered structurally instead, by tests 1 and 2: the planner input has no `days` field, and the prompt is a pure function of `query` and `reference_information`. A real query may state its own length in words; that is the query, which the planner is allowed to see.
4. `test_test_split_forbidden` (`tests/data/`, data-eval; the bridge-client part lands in M2): both loaders and the bridge client raise before any file or network access (checked by patching `open` and `hf_hub_download` to fail if called).
5. `test_no_test_files_on_disk` (local, `tests/data/`, data-eval): no file named `test.csv` or `test_ref_info.jsonl` (or matching `*test*ref_info*`) exists anywhere under `data/` or `vendor/`.
6. The import-linter contracts above.

**Planner inputs in other sessions' tests (v0.7, M1-AQ2).** CI has no dataset, so every session that needs `PlannerInput`s or `EvalRecord`s in a test uses one supported mechanism, owned by data-eval:
- **`TRIPARTITE_DATA_DIR`** (environment variable). If set, it replaces `<repo>/data` as the data root for every path the `tripartite.data` and `tripartite.evaluation.records` loaders resolve. It is read **at call time**, never cached at import. It must be an absolute path to an existing directory, otherwise the loader raises `DataError` naming the variable. Unset means `<repo>/data`. It is a supported interface, documented here and in the `src/tripartite/data/manifest.py` docstring. The module attribute `manifest.DATA_DIR` becomes internal to data-eval's own tests.
- **`tests/fixtures/synthetic_data.py`** (data-eval). `write_synthetic_data_dir(root: Path) -> Path` writes a complete data root under `root`: `raw/validation.csv` with the 11 F7 columns and 180 rows, and a matching `raw/validation_ref_info.jsonl`. It returns the root to put in `TRIPARTITE_DATA_DIR`. The content is M1's existing synthetic set: canaries in every evaluator-only field, and byte-exactness traps in `query` and the reference lines. It never contains a row of real data (§8). Other sessions import it and never copy or edit it.
- **Who must use it:** F1 (the API tests, including starting all 180 `query_id`s with the fake LLM), M3 (any test that renders or counts prompts) and M4 (pipeline tests and `test_canary_no_leak`). Each sets the variable with `monkeypatch.setenv` in its own `conftest.py`. None of them may monkeypatch `tripartite.data` internals. The loaders do not check `data/MANIFEST.json`, so the synthetic tree needs no manifest; `tripartite data verify` is the only thing that checks pins.
- The mechanism is delivered by FU-13 and FU-14 before F1 and M3 start (D9 build order); both merged in `57bb32d` (v0.8).
- **For M4 and anything else that aggregates synthetic rows (v0.9):** since FU-16 (merged in `802e575`), no synthetic row has all-`None` local constraints, and `level` is a canary (`CANARY_LVL_…`), not `easy`/`medium`/`hard`. Code that feeds synthetic rows into `aggregate()`, `smoke-ids` or the metrics writer must therefore rewrite both in its own test setup: `level` to a real level, and `local_constraint` to the pattern the test needs. It must never weaken the canaries in the shared set. **Also (v0.10):** the shared set puts a `transportation` constraint on odd rows at every level, but `eval.py` counts `transportation` in the hard-constraint denominator only for `hard`-level queries (medium counts house rule, cuisine and room type). Its pass count, however, includes every `true` result, so a medium row with `transportation` set can push the pass count past the denominator. Anyone aggregating synthetic rows must clear `transportation` on medium-level rows in its own copy, as M4 did, or set those rows' level to `hard`. The accepted FU-16 deviations: the even-row canary sits in `room type` (not the `house rule` of FU-16's example), so every key is `None` in some rows and set in others; row numbers in canaries are zero-padded; `canaries(i)` lists each canary token on its own; `LOCAL_CONSTRAINTS` is replaced by `local_constraint(i)` and `LOCAL_CONSTRAINT_ODD`.
- **Confirmed in v0.8:** an **empty** `TRIPARTITE_DATA_DIR` is refused with `DataError`, not treated as unset. An empty value is almost always a shell mistake (`TRIPARTITE_DATA_DIR= make …`), and silently falling back to the real data would break test isolation. Both FU-13/FU-14 deviations are accepted: `tripartite data verify` catches `DataError` and prints a clean one-line error with exit code 1 instead of a traceback, and `tests/data/synthetic.py` keeps `matching_manifest` as a data-eval-internal helper. Other sessions use only `tests/fixtures/synthetic_data.py`.

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
| Server | A dedicated `ollama serve` started by `make serve-model` on `127.0.0.1:11435` with `OLLAMA_CONTEXT_LENGTH=<num_ctx>`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=f16`, `LLAMA_ARG_CACHE_RAM=0` (v0.11: passed through to the runner, which turns its host-RAM prompt cache off; D4 §Runner prompt cache), and the log written to `runs/ollama-server.log`. The desktop-app server on 11434 must have no model loaded; `make doctor` checks `/api/ps` and fails otherwise. |
| API | Native `POST /api/generate` with `raw: true`, `stream: false`, `keep_alive: -1`, `think: false` at the top level, and `options{…}` including `stop: ["<|im_end|>", "<|endoftext|>"]` (as built in M3 and accepted in v0.9: Ollama reads `stop` from `options`). The prompt is rendered by us from the pinned HF chat template (jinja2), so our local token count covers exactly the bytes the runtime sees. The OpenAI-compatible endpoint is not used, because it drops `num_ctx`. |
| Concurrency | 1 request at a time, system-wide. A file lock `runs/.model.lock` (filelock) is held by any process that calls the model (CLI batch or API job). |
| Warm-up | Each run, and each API single-run job, starts with one warm-up call (`num_predict: 1`), logged with `role: "warmup"` and excluded from metrics, so measured calls exclude model load. The warm-up prompt is the chat template around the fixed text `Reply with OK. nonce=<uuid4 hex>`, with a fresh nonce each time. The only token prefix it shares with any planner prompt is the chat-template header. **Corrected in v0.10 (M4 AQ12):** this does *not* make the cache state known. The runner also keeps a host-RAM prompt cache that survives the warm-up (D4 §Runner prompt cache), so a run's first call can reuse a prompt cached by an earlier process. Under calibration mode `total` the post-check does not depend on the cache state. The warm-up uses seed 0 and goes through the post-check (as built in M4, AQ11). After it, the pipeline checks the running server's version, loaded digest and `context_length` against the pins (`StackMismatchError`, `DigestMismatchError`; accepted v0.10). |

**`configs/stack.yaml` (Q1; owner: model session, M3).** One file holds every runtime pin, and both `make serve-model` and `tripartite model doctor` read it. Keys:

```yaml
schema_version: 1
runtime:
  name: ollama
  version: "0.x.y"                  # exact; doctor compares `ollama --version`
  url: "http://127.0.0.1:11435"     # the dedicated server this project uses
  env:                              # exported verbatim before `ollama serve`
    OLLAMA_HOST: "127.0.0.1:11435"
    OLLAMA_CONTEXT_LENGTH: "32768"
    OLLAMA_NUM_PARALLEL: "1"
    OLLAMA_MAX_LOADED_MODELS: "1"
    OLLAMA_KEEP_ALIVE: "-1"
    OLLAMA_FLASH_ATTENTION: "1"
    OLLAMA_KV_CACHE_TYPE: "f16"
    LLAMA_ARG_CACHE_RAM: "0"           # v0.11 (FU-26): runner prompt cache off; required key
  desktop_app_url: "http://127.0.0.1:11434"   # must have no model loaded
model:
  tag: "qwen3:8b-q4_K_M"
  digest: "sha256:<64 hex>"
  quant: q4_K_M
  num_ctx: 32768
tokenizer:
  repo: "Qwen/Qwen3-8B"
  revision: "<hf commit sha>"
  local_dir: data/tokenizer
```

`runtime.env` is the single source of the D4 server environment: the table above is its prose, and if the two ever disagree the table wins and the file is wrong. The model session provides `tripartite model serve-env [--format sh]`, which validates the file and prints one `KEY=VALUE` line per `runtime.env` entry (`--format sh` prints `export KEY='VALUE'`). `make serve-model` evaluates that output and then runs `ollama serve`; it never parses YAML itself.

**`make serve-model`, exactly (v0.5; AQ2–AQ4).** The whole recipe body is one shell line, after the `configs/stack.yaml` guard:

```
mkdir -p runs; env_sh="$$(uv run tripartite model serve-env --format sh)" || exit 1; set -a; eval "$$env_sh"; set +a; exec ollama serve >> runs/ollama-server.log 2>&1
```
- `mkdir -p runs` first, because on a fresh clone nothing else has created it (AQ2).
- If `serve-env` fails (a missing or invalid `stack.yaml`, an unknown key), the recipe exits 1 **before** starting anything, so an unpinned server with Ollama's default context can never come up (AQ3).
- The server log path is the **fixed constant `runs/ollama-server.log`**, not a `stack.yaml` key (AQ4). Four places use it — this recipe, the post-run truncation scan (D4 §Truncation, 3), `doctor` (A-005 and A-022 evidence) and the `.gitignore`d `runs/` rule — and a configurable path would be one more thing that can disagree. The `runtime.log_path` key present in v0.4 is removed. `serve-env` MUST reject it, like any unknown key, so a stale file fails loudly.

`tripartite model doctor` checks: the file validates; `ollama --version` equals `runtime.version`; the server at `runtime.url` answers; its effective context length and loaded model match `model.num_ctx` and `model.digest` (A-022); `desktop_app_url` has no model loaded (`/api/ps` empty, a warning rather than a failure if that server is not running at all); `reports/token_calibration.json` is missing, valid or stale (D4 §Token calibration); and `data/MANIFEST.json` matches (`tripartite data verify`). **As built (v0.11, AQ2):** Ollama's `server config` log line lists only Ollama's own variables, so doctor compares only the `OLLAMA_*` keys of `runtime.env` with that line. A separate **runner prompt cache** check reads `runs/ollama-server.log` since the last server start. It fails if the latest runner start says `prompt cache is enabled`, or if any `updating prompt cache` / `prompt cache update took` / `cache state:` line appears. It passes when the startup says `prompt cache is disabled`. `config.py` treats `LLAMA_ARG_CACHE_RAM: "0"` as a required D4 key, so `serve-env` rejects a `stack.yaml` without it.

**Measured on the M4 Pro in M3 (v0.9).** Ollama 0.33.2 does not log `recommendedMaxWorkingSetSize`. Its log shows Metal `total="17.8 GiB"` and `18185 MiB free`, with `iogpu.wired_limit_mb = 0` (the macOS default). **So the GPU budget is 17.8 GiB, not the ~16 GB estimated below** (A-031). The loaded model takes 9.91 GB (9.23 GiB, all in VRAM), the runner peaked at 9.58 GiB during calibration, and the KV cache logged at 4,608 MiB, exactly the arithmetic below (A-038). The estimate below is kept as the design record.

**Memory budget (24 GB unified, dev tools and Claude apps running).** Weights take 5.2 GB. f16 KV cache is 2 × 36 layers × 8 heads × 128 × 2 B = 147,456 B/token, which is 4.8 GB at 32,768 tokens; the compute graph adds about 1 GB. Total resident is about 11 GB (A-011). That is under the ~16 GB default GPU working-set limit (A-005) and leaves about 13 GB for macOS, IDE, browser and the Claude apps.

**Context measurement (Phase 0, `make measure-context`).** The target runs exactly two commands, in this order, and stops at the first failure:

1. `tripartite model measure-context` — tokenizer only, no server needed. Tokenizer: HF `Qwen/Qwen3-8B` `tokenizer.json` at the pinned revision, loaded with `tokenizers`. For each of the 180 queries, record `ref_tokens` (reference_information alone) and `prompt_tokens` (the full rendered raw prompt). Write `reports/context_report.json`: `{tokenizer, revision, num_ctx: 32768, num_predict, per_query: [{query_id, ref_chars, ref_tokens, prompt_tokens}], summary: {min, median, p95, max} for each, fits: bool, headroom_tokens}`. Exit non-zero when `fits` is false, that is when `max(prompt_tokens) + num_predict + 256 > num_ctx`. From the character counts in F8, the maximum should be around 15–20k tokens (A-006), leaving ample headroom.
2. `tripartite model calibrate` — needs `make serve-model` running with the same pinned `num_ctx`. It refuses to run if `reports/context_report.json` is missing, if its `fits` is false, or if its `num_ctx` differs from the running server's (read from `/api/show` / the server env check in `make doctor`).

Because `num_ctx` is a pin and never recomputed, no server restart happens between the two steps.

**Result (M3, v0.9; A-037):** `prompt_tokens` min 4,885, median 10,808, p95 17,768, max 20,214 (slightly above the predicted 15–20k). `fits = true`, headroom 8,202 of the 28,416 available (32,768 − 4,096 − 256). `context_report.json` also carries `prompt_version` and `prompt_sha256` (accepted as built). The logic lives in `llm/context.py` and `llm/calibration.py` (accepted as built).

**Truncation is a hard error.**
- (1) Pre-flight: if `prompt_tokens + num_predict > num_ctx`, raise `ContextOverflowError` before calling. The run aborts; the query is never silently recorded as non-delivered. **This check is permanent and may never be relaxed (v0.10).** Ollama 0.33.2 starts `llama-server` with `--context-shift --keep 4`, so if a prompt plus its answer ever overflowed `num_ctx`, the runner would drop tokens and carry on rather than fail. The pre-flight check is the only guard against that; the post-check would not see tokens dropped during generation.
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

**Calibration result (M3, v0.9).** Mode **`total`**. The tokenizer agreed exactly on all 9 cold probes, each with a fresh load of 2.0–2.6 s (A-032, A-034). Both warm probes reported the full prompt in `prompt_eval_count` (A-033), and `/api/ps` showed `context_length` 32768 (A-035). So the **post-check is plain equality**, `prompt_eval_count == prompt_tokens`, and A-020's bound is not used (A-036). An omitted `prompt_eval_count` is treated as 0 (accepted as built). Because `prompt_tokens > 0`, that can only make the check fail, never pass. The event still logs the reported field as null.

**Runner prompt cache (v0.10; from `runs/ollama-server.log` in the M4 worktree).** Ollama 0.33.2 runs the model in llama.cpp's `llama-server`, started with `-c 32768 -np 1 --cache-type-k f16 --cache-type-v f16 --flash-attn on -b 512 -ub 512 --context-shift --keep 4`. Ollama passes no cache flag, so the runner's default **host-RAM prompt cache** is on: `limits: 8192.000 MiB, 32768 tokens`. Before each new request it saves the previous prompt's state into ordinary RAM, evicting the oldest entry first ("prompt cache update took 2656.95 ms … 3599.29 ms"; "cache state: 5 prompts, 6970.931 MiB").
- **AQ12 explained.** `val-001` was the last prompt of `make test-local`. It was still in this cache 2.5 h later, so the smoke run's first measured call restored it (0.0 s prefill for 6,448 tokens) despite the warm-up. The post-check still held (mode `total` counts the whole prompt either way).
- **Memory.** Up to 8 GiB of host RAM, outside Ollama's accounting. That explains Activity Monitor showing `llama-server` at 17.32 GB against 9.91 GB in `/api/ps`, and part of the swapping during the smoke run (A-043).
- **Hits in seed-major order: essentially none (confirmed reasoning).** An entry takes about 1.6–2.5 GiB (prompt tokens × 147,456 B/token; about 16k tokens → 2.4 GiB), so the cache holds 3–5 prompts. Seed-major order revisits a prompt only after 9 other prompts (smoke) or 180 (full run), and eviction is oldest-first, so no full-prompt hit is possible within a run. The exceptions are the **first call of a run, and the first call after a resume**, which can hit an entry left by an earlier process on the same server. A cached entry can also serve a partial prefix match on the shared ~450-token instruction head, which is negligible. Under mode `total`, no hit changes a token count.
- **Where the save time lands (A-044).** The save happens when the next request arrives, before its prompt is processed. So it is inside that call's `wall_client` (and Ollama's `total_duration`) but **not** inside `prefill` or `generation`. This fits the smoke run: mean wall 54.3 s against mean prefill + generation 52.6 s, a gap of about 1.8 s per call, of which the save is the bulk. `latency_ms.wall` therefore includes about 2.7–3.6 s of cache bookkeeping on most calls; `prefill` and `generation` are clean.
- **It can be bounded or disabled without changing the Ollama pin.** Ollama passes its environment through to `llama-server`, and llama.cpp reads `LLAMA_ARG_CACHE_RAM` (MiB; `0` disables, `-1` means unlimited) when no flag is given (ollama/ollama#18264 on 0.31.2; #17351; llama.cpp server README). Not yet verified on 0.33.2 (A-045).
- **Decision for M5 (approved by the user 2026-09-29; FU-26, merged in `dba2ac2`).** `runtime.env` carries `LLAMA_ARG_CACHE_RAM: "0"`. It is not a pin change in the §6 sense (the Ollama version, model digest, tokenizer and `num_ctx` are unchanged); `doctor`, the run manifest (`run_start.env.ollama_env`) and resume (D7) all compare it. The calibration was re-run: mode `total`, all 9 cold probes exact, and only `calibrated_at` and the `load_ms` values changed. The calibration report does not record `runtime.env`; that is left as is for Phase 1, because under mode `total` the cache setting cannot change any count (AQ9). Revisit only if the runtime env ever affects calibration.
- **Verified (A-047).** On Ollama 0.33.2 the variable reaches `llama-server` through the environment (the `ollama serve` process carries it; the runner command line has no cache flag). All 19 runner starts after the restart log `prompt cache is disabled`, and there are 0 `updating prompt cache`, 0 `prompt cache update took`, 0 `cache state:` and 0 `truncating input prompt` lines over doctor, calibration, `make test-local` and the smoke run `20261007T053937Z-batch-9b45ed9e-5fd2`.
- **Effect, measured on that smoke run against v0.10's.**
  - The bookkeeping gap, wall − (prefill + generation), fell from about 1.8 s to 0.02 s per call (A-044 confirmed, A-048).
  - **No time saving:** mean wall was 54.56 s against 54.3 s, because prefill came out about 4% slower (283 tok/s against about 294 tok/s for v0.10 once its cache-restored first call is excluded). With one run each, that is recorded as run-to-run variance, not a cause. v0.10's "about 6%, 25–30 min per run" is **withdrawn** (A-049).
  - **Memory:** `llama-server` sat at 10.25–10.28 GB (`footprint`) against 17.32 GB, and swap stayed flat at 2.68–2.70 GB against 10–18.8 GB. Apps were closed this time, so the swap comparison is not like for like (A-050).
  - The first measured call is now computed (20.7 s prefill for `val-001`), not restored.
- M5's operations still restart the dedicated server before each full run (D9 §M5 operations). With the cache off, only the slot's own KV prefix reuse of the immediately previous prompt remains, which is harmless under mode `total`.
- **The model file (v0.10).** `llama-server`'s `--model` path is the GGUF blob `sha256-a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`, not the manifest digest `500a1f067a9f…` we pin. That is expected: the pinned digest is the hash of Ollama's manifest, which names its layer blobs by their own sha256, and Ollama verifies blobs against those hashes on pull. The manifest pin therefore implies the blob. The blob hash is recorded in §6 as a derived value. `doctor` does not need to check it; a mismatch would mean local blob-store corruption, which the manifest digest check plus Ollama's own verification make negligible.

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

**Fake-mode tokenizer (v0.8, item 1b; owner: model).** Delivered as a model follow-up after M3 (`e7043f7`, merged in `28b6a01`), because M3 was built against v0.7. Accepted as built in v0.9: `Tokenizer` is a `Protocol`, the HF class is `HFTokenizer`, and the fake template is a jinja string constant rendered by the same `ChatTemplate` class as the real one, so both modes share one code path. The renderer cache is keyed on the `TRIPARTITE_LLM` mode, so tests can switch modes. `llm_mode()` accepts only `fake`, `ollama` or unset (= `ollama`), and raises on anything else. CI has no network and no `data/tokenizer/`, so fake mode needs its own tokenizer and chat template. The supported mechanism is the same environment switch as the fake client, and it lives in `src/`, not `tests/`, because the API server itself runs in fake mode for web development and CI:
- `tripartite.llm.tokenizer.tokenizer_from_env() -> Tokenizer` returns the real HF tokenizer (pinned revision, `data/tokenizer/`) normally, and `FakeTokenizer` when `TRIPARTITE_LLM=fake`. It never touches the network or `data/tokenizer/` in fake mode.
- `FakeTokenizer` (in `src/tripartite/llm/fake_client.py`) is byte-level: one token per UTF-8 byte, id = byte value. Its identifier `fake-bytes@v1` is what `tokens.tokenizer` records, so a fake run can never be mistaken for a real one.
- `tripartite.llm.chat_template.template_from_env()` returns the pinned HF template normally, and in fake mode a fixed Qwen3 non-thinking template committed as a string constant (`<|im_start|>user\n{content}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n`), so the purity and leak tests exercise the same structure.
- M3's functions keep taking the tokenizer as an argument; `tokenizer_from_env()` is only the default the pipeline, the CLI and the API use. `tests/fixtures/model/` stays the model session's own unit-test helper. Other sessions (F2's tests, web e2e in CI) use the environment switch and never import it.
- Fake token counts are self-consistent but not real Qwen counts, so fake runs are never reported as results.

**Fake mode and data (v0.10).** `FakeTokenizer` counts bytes. Real prompts are 11.7k–51.6k characters, so most exceed the 28,416-token budget in fake mode, and fake runs against the real data raise `ContextOverflowError`. **Decision: fake mode is synthetic-data-only.**
- `tripartite run start` and the API job runner, both through the pipeline's `open_run`, refuse to start a run in fake mode unless `TRIPARTITE_DATA_DIR` is set to a data root other than `<repo>/data`. They raise `FakeModeRealDataError` with a message naming the variable (FU-27, merged in `dba2ac2`). As built and accepted (v0.11, AQ8): resolved paths are compared, and only a root that resolves to `<repo>/data` itself is refused; a directory inside it is accepted. Resume is covered through `open_run`.
- Listing queries (`/api/queries`) is unaffected, because it involves no tokenizer.
- For web development and `make api` in fake mode, data-eval provides `tripartite data synthetic --out DIR`, which writes the shared synthetic set (FU-28).
- Alternatives rejected: scaling the fake budget would let fake runs produce run directories built on real data with fake outputs, which could be mistaken for results; documenting the limit without enforcing it would leave the failure to be rediscovered.

**Health checks for `/api/health` (v0.8, item 1d; owner: model, FU-17 — merged in `28b6a01`).** As built, both functions take `StackConfig | Path` (default `configs/stack.yaml`) plus a `transport` argument for tests (accepted, v0.9). Measured (A-039): with the model loaded or not, both returned true in 3–29 ms; with no server, false in 3–25 ms; `/api/ps` stayed empty across 20 calls, and the server log shows only `/api/version` and `/api/tags`. In `src/tripartite/llm/doctor.py`, reusing `doctor`'s `stack.yaml` loader:
- `model_reachable(stack) -> bool`: `GET {runtime.url}/api/version` with a 1.0 s total timeout; true iff HTTP 200 with a `version` field. It sends no generate request, so it never loads the model.
- `model_digest_ok(stack) -> bool`: `GET {runtime.url}/api/tags` with a 1.0 s total timeout; true iff an entry's `name` (or `model`) equals `model.tag` and its `digest`, compared without any `sha256:` prefix, equals `model.digest`. It uses **`/api/tags`, not `/api/ps`**: `/api/tags` lists installed models whether or not they are loaded, while `/api/ps` lists only loaded ones and would report false before the first warm-up. It does not check the Ollama version; `make doctor` does.
- Any exception, timeout or missing `configs/stack.yaml` returns false; neither function raises. In fake mode both return true without any network call.

**Run configs (`configs/baseline.yaml`, `configs/single.yaml`; as built in M3, recorded v0.9).** Top-level `kind`, `queries` (`all` or a list of query_ids) and `seeds`; `run.name` (excluded from `config_hash`, D7); `prompt{version, path, sha256}`; and `generation{…}`, holding the D4 sampling options plus `timeout_s` and `transport_retries` (D6 §Retries). `configs/single.yaml` holds `val-001` / seed 0 only as placeholders; the API job runner replaces `queries` and `seeds` per job (D8).

**Other M3 behaviour, accepted as built (v0.9):**
- `tripartite model doctor` loads the model with no options, under `runs/.model.lock`, when nothing is loaded, so that `/api/ps` can show the effective context length and digest (A-022, A-035). It never generates. The health checks (FU-17) never load.
- `data/tokenizer/.pinned.json` records the repo and revision of the downloaded tokenizer (gitignored with the rest of `data/`).
- `make pull-model` needs `make serve-model` running, because Ollama pulls through the server.
- `prompts/.editorconfig` stops editors from rewriting the byte-exact prompt file (trailing whitespace, final newline).

Alternatives considered:
- MLX (`mlx-lm`): possibly faster on Apple silicon, and the brief lists it. It lacks a content-addressed model digest and the per-call load/prefill/generation split. It is reserved for Phase 8 LoRA.
- q8_0: better fidelity, but about 14.7 GB resident at 32k with f16 KV, which is too tight beside dev tools. q8_0 weights with a q8_0 KV cache come to about 12.3 GB, but KV quantization adds a second source of precision loss.
- Thinking on: better reasoning, but it adds thousands of tokens per call, forces sampling-only decoding, strains context and multiplies the ~6–9 h baseline (A-010). It is a candidate ablation later, and tokens are already logged separately.
- Greedy T=0 (as official): makes 3 seeds identical and the brief's 3-seed requirement empty. See Open questions.
- Concurrency above 1: multiplies KV memory and breaks timing comparability.

## D5 (e). Evaluator integration

**Vendoring.** Copy these paths **unmodified** from `OSU-NLP-Group/TravelPlanner@e52c87f4ac348a3410c46dc3553c519db5ec5e23` into `vendor/travelplanner/`, keeping their relative layout: `evaluation/` (all 3 files), `tools/` (entire directory, including subpackages, but **no `__pycache__/` or `*.pyc`**: upstream at `e52c87f4` tracks `tools/restaurants/__pycache__/*.pyc`, and compiled bytecode is not source; v0.8, M2 deviation accepted), `utils/`, `agents/prompts.py`, `postprocess/example_evaluation.jsonl`, `database/README.md`, `LICENSE`, `README.md`. Excluded: `database/*_ref_info.jsonl` (including test), `images/`, `finetuning_data/`, and everything else. `vendor/travelplanner/VENDOR.lock` lists every vendored file with its sha256 and the upstream commit. `vendor/travelplanner/VENDOR.md` explains provenance and licence (code MIT; data CC BY 4.0).

**Database — the pin (v0.6).** The zip is downloaded manually from the Google Drive link in the upstream README, because Drive links are not scriptable reliably. The upstream file name is kept, so the user saves the file unrenamed as **`data/downloads/sandbox_database.zip`**. The trust-on-first-use pin (A-013), from the user's first download on 2026-09-25:

| Field | Value |
|---|---|
| name | `sandbox_database.zip` |
| bytes | `59039278` |
| sha256 | `de345b0c243cd8c85355a264c5124db5db275327d2a38fa8685c6e69fabb650b` |

M1 and M2 **check against this value**; they never pin whatever file they happen to find. The value lives in two places, both owned by data-eval: the constant `DATABASE_ZIP` in `src/tripartite/data/manifest.py`, and the `database_zip` entry of `data/MANIFEST.json`. A CI test asserts that the two agree and equal the table above. `tripartite data verify` refuses a zip whose size or sha256 differs, and names the expected and actual values. A mismatch is an architecture question (A-013), never a reason to update the pin.

**Database — unpacking (v0.6; M2).** Every data file in the zip sits under a top-level `database/` folder, so unpacking it *into* `vendor/travelplanner/database/` would create `database/database/…`. The evaluator's `../database/` paths would then find nothing. Unpacking is done by `tripartite data fetch` (data-eval), in Python with `zipfile`, never the `unzip` tool, exactly as follows:
1. **Verify the zip first** against the pin above. Nothing is extracted from an unverified zip.
2. **Look at every entry before writing anything.** Normalize the name to POSIX (`/`). Refuse the **whole** zip, writing nothing, if any entry:
   - has an absolute path, a drive letter, or a backslash;
   - has a `..` component;
   - is a symlink (Unix mode `S_IFLNK` in `external_attr`);
   - has a first component other than `database` or `__MACOSX`.
3. **Skip, silently:** directory entries; everything under `__MACOSX/`; any entry whose final component is `.DS_Store` or starts with `._` (AppleDouble). The pinned zip contains `__MACOSX/database/background/._.DS_Store` and five `.DS_Store` files, and all of them are skipped.
4. **Map the remaining entries.** Strip the leading `database/` component, so `database/<rest>` → `vendor/travelplanner/database/<rest>`.
5. **The mapped set must equal exactly this expected list.** A missing or extra file refuses the whole zip. Sizes are pinned in code (`EXPECTED_DATABASE_FILES` in `src/tripartite/data/manifest.py`) and checked against both the zip's `file_size` and the written bytes:

   | Path under `vendor/travelplanner/database/` | Bytes | Read by the evaluator |
   |---|---|---|
   | `background/citySet_with_states.txt` | 5,921 | yes: `commonsense_constraint.py` (module level) |
   | `background/citySet.txt` | 3,064 | no (only `agents/tool_agents.py`, not vendored) |
   | `background/stateSet.txt` | 642 | no (nothing at `e52c87f4` reads it) |
   | `attractions/attractions.csv` | 817,982 | yes: `tools/attractions/apis.py` |
   | `flights/clean_Flights_2022.csv` | 304,807,007 | yes: `tools/flights/apis.py` |
   | `googleDistanceMatrix/distance.csv` | 795,427 | yes: `tools/googleDistanceMatrix/apis.py` |
   | `restaurants/clean_restaurant_2022.csv` | 683,023 | yes: `tools/restaurants/apis.py` |
   | `accommodations/clean_accommodations_2022.csv` | 520,458 | yes: `tools/accommodations/apis.py` |

   All 8 are unpacked, because the database is kept as upstream ships it; the two unread files cost 3.7 kB.
6. **Per-file sha256: both sizes and hashes are pinned.** On the first successful unpack, `data fetch` records the sha256 of each of the 8 files in `data/MANIFEST.json` under `database_files: {<path>: {bytes, sha256}}`. They are fully determined by the pinned zip, so this is not a second trust decision. It lets `tripartite data verify` check the **unpacked** tree, which is what the evaluator actually reads (R1), without the zip. Sizes are checked from M2 on; hashes from the first recorded unpack on.
7. **Write through a temporary folder.** Extract into `vendor/travelplanner/database/.unpack-tmp/`, which is covered by the existing `vendor/travelplanner/database/*` ignore rule, then verify, then move the files into place. The upstream `README.md` in that folder is tracked and is never touched. Re-running on an already-verified tree is a no-op.

**Confirmed from source at `e52c87f4` (v0.6).** Through `eval.py` → `commonsense_constraint.py` / `hard_constraint.py` → `tools/{flights,accommodations,restaurants,googleDistanceMatrix,attractions}/apis.py`, the evaluator opens exactly six paths relative to its cwd `vendor/travelplanner/evaluation`: `../database/background/citySet_with_states.txt`, `../database/flights/clean_Flights_2022.csv`, `../database/accommodations/clean_accommodations_2022.csv`, `../database/restaurants/clean_restaurant_2022.csv`, `../database/googleDistanceMatrix/distance.csv` and `../database/attractions/attractions.csv`. `utils/func.py` also opens `citySet_with_states.txt`, but only inside `get_city_list`, which the evaluator does not call. These are the six "yes" rows above, and they resolve to `vendor/travelplanner/database/…` because the bridge runs with `cwd=vendor/travelplanner/evaluation` (D5 §Bridge).

**Separate environment.** `evalenv/` is its own uv project (`evalenv/pyproject.toml`, `evalenv/uv.lock`, same Python version). Dependencies: pandas 2.2.x, numpy, requests, tqdm, datasets and gradio, pinned by the lock. It is kept separate because gradio would conflict with our FastAPI pins, and because the evaluator has import-time side effects (`os.chdir`, globals).

**Bridge** (`evalenv/bridge.py`: standalone, stdlib only plus the vendored modules, no `tripartite` imports):
- Started as a long-lived subprocess: `uv run --locked --project <repo>/evalenv python <repo>/evalenv/bridge.py`, with absolute paths, `cwd=<repo>/vendor/travelplanner/evaluation` and `PYTHONPATH=<repo>/vendor/travelplanner:<repo>/vendor/travelplanner/evaluation` (v0.8: absolute paths and `--locked` accepted as built in M2). Its environment is the parent's minus `VIRTUAL_ENV`, plus `HF_HUB_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, `GRADIO_ANALYTICS_ENABLED=False`, `PYTHONDONTWRITEBYTECODE=1` (nothing is written into `vendor/`) and `PYTHONHASHSEED=0` (accepted as built). It speaks JSON Lines over stdin/stdout, and logs go to stderr. Loading the database CSVs happens once per process.
- Request `{"op": "per_plan", "id", "query": <one bridge record, §Bridge records file below>, "plan": <list|null>}`. Before evaluating, the bridge applies to that record exactly the one conversion `eval.py` applies (lines 74–75): if `local_constraint` is a string, it is replaced by `ast.literal_eval(local_constraint)`. `ast.literal_eval` is used instead of upstream's `eval`; both give the same dict for these literals, and M1 validated all 180. It then calls `commonsense_constraint.evaluation(query, plan)`. Only if `is_not_absent[0]` and `is_valid_information_in_sandbox[0]` are both true does it call `hard_constraint.evaluation(query, plan)`, which is the same gating as `eval.py`. It returns `{"id", "delivered", "commonsense": {key: [value, message]}, "hard": {key: [value, message]} | null}` with values `true`/`false`/`null`. A plan of null or empty returns `delivered: false` with both groups null.
- Request `{"op": "aggregate", "id", "set_type": "validation", "plans_path", "records_path"}`. It replaces the module attribute `eval.load_dataset` with a function that returns `{"validation": <records from records_path>}`, which removes the `force_redownload` network call (F2). No vendored file is edited. It then calls `eval.eval_score("validation", plans_path)` and returns `{"id", "scores": <six official keys>, "detailed": <second return value>}`. It refuses any `set_type` other than `validation`. Here the bridge does **not** convert anything: `eval.py` converts `local_constraint` itself.
- Python exceptions inside the evaluator are returned as `{"id", "error": {"type", "message"}}`. For `per_plan`, the pipeline records the plan as `evaluation_error` and **aborts the run**, because an evaluator crash is a bug, not a model failure.

**Bridge records file (v0.7; checked against source at `e52c87f4`).** What the evaluator reads from each query row, and what it converts itself:
- `eval.py` indexes rows by position, zips them with the plans file, and only calls `eval()` on a row that is a whole string (not our case) and on `local_constraint` when it is a string (lines 70–75). The conversion mutates the row in place, so its second pass over the rows (lines 98–103, the hard-constraint denominators) sees the parsed dict.
- It uses `level` (a key into `{"easy", "medium", "hard"}`) and `days` (a key into `{3, 5, 7}`), so `days` must be an `int`.
- `commonsense_constraint.py` compares `org` and `dest` with city and state names, and uses the numbers arithmetically: `question['days'] > 3`, `lens != question['days']`, `needed_info = 6 * question['days']`, `len(city_set) != question['visiting_city_number']`. So the numbers must be `int`s, and the failure mode of getting this wrong is mostly **silent**: with a string, `len(city_set) != "2"` is always true and `6 * "3"` is `"333333"`, so checks would fail quietly rather than crash. Only `days > 3` would raise.
- `hard_constraint.py` reads `people_number` (multiplied), `budget` (compared with a float total) and `local_constraint['house rule' | 'cuisine' | 'room type' | 'transportation']` (after conversion).
- **Nothing in the evaluator reads `date`, `query` or `reference_information`**, and nothing parses `date`.

So `records_path` (and each `per_plan` record) is **exactly what `datasets.load_dataset` would return per row**, serialized as JSON Lines:
- One JSON object per line; line *i* is row *i* of `validation.csv` (`val-00i`), in dataset order. For `aggregate` there are exactly 180 lines, and the bridge refuses any other count.
- Keys: exactly the 11 F7 columns, `org, dest, days, visiting_city_number, date, people_number, local_constraint, budget, query, level, reference_information`. No `query_id` and no extra keys.
- `days`, `visiting_city_number`, `people_number`, `budget`: JSON integers. This is what `load_dataset` returns: the validation config's features at revision `8736504e` declare these four `int64` and the other seven `string` (A-025, confirmed by A-026).
- Every other field: the **verbatim CSV string**, byte for byte. That includes `local_constraint` as its Python-literal **string**, not the parsed dict (`eval.py` converts it), and `date` as its list-literal string (never parsed).
- Written by `tripartite.evaluation.records.to_bridge_row(record) -> dict` with `json.dumps(row, ensure_ascii=False)`. `EvalRecord` therefore keeps the verbatim `local_constraint` string alongside the parsed dict (FU-15). Re-serializing the dict with `repr()` is **not** allowed, because it need not reproduce the original bytes.
- A data-eval test asserts, for all 180 rows, that `to_bridge_row` round-trips to the original CSV cell strings. A local M2 test runs both bridge ops on the same row and checks that they agree.

**Wrapper** (`src/tripartite/evaluation/`, main env):
- `bridge_client.py`: `EvaluatorBridge` protocol with `RealBridge` (subprocess) and `FakeBridge` (fixture-driven, for CI and the web dev loop via `TRIPARTITE_EVAL_BRIDGE=fake`).
- `constraints.py`: turns a per-plan result into the UI list `[{key, label, group, status, message}]`. `label` is the paper name from `eval.py::paper_term_mapping` (for example `valid_cost`→"Budget"). `status` is `pass` (true), `fail` (false), `not_applicable` (null), or `not_evaluated`: the evaluator did not run that check, **either** because the plan was not delivered (all 13 rows) **or** because gating skipped the hard group (the 5 hard rows) (v0.8, M2 ruling). The UI tells the two apart through `delivered`. There are always 8 commonsense rows plus 5 hard rows.
- `aggregate.py`: `aggregate(results: Sequence[PerPlanResult], records: Sequence[ScoredQuery]) -> OfficialScores`. `ScoredQuery` is a structural protocol (`query_id`, `level`, `days`, and a `local_constraint` mapping), so `EvalRecord` and the golden test's query rows both satisfy it; accepted as built. The return type is renamed from `Metrics` to **`OfficialScores`** (FU-20), because `runlog.schema.Metrics` is the `metrics.json` model and the pipeline imports both. It reimplements exactly the formulas of `eval_score`, with denominators computed from the subset (commonsense micro = passes/(8n); hard micro = passes/Σ applicable hard constraints, using eval.py's rules, including the medium/hard `mapping_constraint_record` logic). It is used for subsets (smoke, single runs). Full 180-query runs use the bridge's `aggregate` op, and the pipeline asserts the two agree to 1e-12. The subset hard-micro denominator is counted from the subset's own records by `eval.py`'s rules, including the medium/hard `mapping_constraint_record` logic, and gives 420 on the full set (accepted, v0.8).
- **Golden equivalence test:** once, locally, the data-eval session runs the real bridge on `example_evaluation.jsonl` and commits the per-plan results and official scores to `tests/fixtures/eval_golden/`. The CI test asserts `aggregate(per_plan) == official scores`. Merged in M2 (`8378f2a`). Every key in all 180 per-plan results is a `[value, message]` pair, which confirms A-014 (A-027).
- **Upstream drift (recorded v0.8).** Line 162 of the vendored `postprocess/example_evaluation.jsonl` has a `query` saying "allow parties" where row 162 of `validation.csv` says "allow smoking". The golden scores are unaffected, because `eval.py` pairs plans with dataset rows by position and never reads the submission's `query`. The file is vendored unmodified; do not "fix" it.

**Metrics reported — Approved 2026-09-22 (micro added).** For each seed and as the 3-seed mean ± SD: Delivery Rate, Commonsense Micro, Commonsense Macro, Hard Micro, Hard Macro and Final Pass Rate. These are the evaluator's own six keys, unchanged. The brief names macro only. Micro is added because published 8B macro and final rates are at or near 0, so micro may be the only signal that moves. Also reported: per-constraint pass rates (from `detailed`), tokens and latency.

## D6 (f). Prompt policy — Approved 2026-09-22, conditional on A-009

- **Phase 1 prompt = the official sole-planning "direct" prompt, verbatim**: `PLANNER_INSTRUCTION` from `vendor/travelplanner/agents/prompts.py`. It is copied to `prompts/sole_planning_direct_v1.txt`, and its sha256 is recorded in the config. Test `test_prompt_matches_upstream` extracts the string with `ast` (without importing langchain) and asserts byte equality.
- `{text}` = the exact reference-information JSON line (D3). `{query}` = the query text. The whole prompt is sent as a single user turn with no system message, matching F5. The only wrapper is the Qwen3 chat template (D4).
- **Condition met (v0.9):** A-009 is confirmed (A-030). On 2026-09-28 the user queried the train split in the Hugging Face SQL console: 0 of 45 `annotated_plan`s contain `F3633413`, and 0 contain `Nagaland`. D6 therefore holds without condition, and M4's gate is cleared.
- **In-context example:** only the one already inside the official prompt (Ithaca→Charlotte, written by the benchmark authors). We add no examples. No example is ever drawn from `annotated_plan`, train or validation data, or any evaluator output. Its provenance is A-009. If it turns out to be copied from a train annotated plan, the non-negotiable applies and D6 must be revisited before Phase 1 numbers are final.
- **Forbidden in any prompt:** hand-written hints about constraints or commonsense rules beyond the official text, structured restatements of the query, evaluator field values, and retries that feed back evaluator results.
- **Retries:** transport errors (connection refused, HTTP 5xx, timeout at 600 s) are retried up to 2 times with the same seed, with a 1 s pause between attempts, and failed attempts count in `query_result.totals` (as built in M4, accepted v0.10). These are **not** retried and are hard errors (`ServerError`): any HTTP 4xx including 404 model-not-found; a 2xx body that is not JSON; a 2xx body with an `error` field; a response with `done: false`; and a response that does not validate. Model outputs are never retried because they are bad. Retries are logged.
- **Versioning:** `prompt_version = "sp-direct-v1"`. Any byte change means a new version, a new file and an architecture decision.
- Alternatives considered: a custom prompt (rejected: risks "evaluation cues" and breaks comparability); the official CoT prompt (it adds a diversity hint of its own, so it is kept for later as an ablation); zero-shot with the example removed (possible if A-009 fails).

## D7 (g). Run log and tracking

**Location and immutability.** `runs/<run_id>/`, gitignored. `run_id = <UTC YYYYMMDDTHHMMSSZ>-<kind>-<config_hash[:8]>-<4 hex>`. `manifest.json` is the one mutable file while a run is in progress. **Reworded in v0.10 (M4 AQ4):** only a **succeeded** run is immutable. A `failed` or `interrupted` run, or a stale `running` one (no process holds `runs/.model.lock` for it), may be resumed, and the resume appends to it. A `queued` run is never resumed. Re-scoring writes to `runs/<run_id>/rescore-<ts>/`, and `make eval` compares. These `rescore-<ts>/` subfolders are the only additions allowed in a succeeded run's directory; its own files never change. **`reproduce_check.json` is written outside both run directories** (v0.11), to `runs/reproduce/<run_a>__<run_b>/reproduce_check.json`, and copied into `results/phase1/<run_id>/` for both runs in M5a.3.

**Run directory:**
```
manifest.json            # RunManifest: the run_start payload plus live status (Q5)
events.jsonl             # all events, append-only, one JSON object per line
blobs/<sha256>.txt       # rendered prompts (stored once; shared across seeds)
plans_seed{n}.jsonl      # evaluator input: 180 lines (or subset) {"idx","query","plan"}
per_plan_eval_seed{n}.jsonl   # one line per query: {"idx","query_id","delivered","commonsense","hard"} (v0.10, AQ3)
metrics_seed{n}.json     # official scores (full runs) or subset aggregate
metrics.json             # summary across seeds + tokens/latency stats
rescore-<UTC ts>/        # only from `make eval` / reproduce-check R1; never changes the run's own files
```

**`manifest.json` (Q5).** Model `RunManifest` in `src/tripartite/runlog/schema.py`:

```
{"schema_version": 1,
 "run_start": <the run_start payload, without the envelope>,
 "status": "queued" | "running" | "succeeded" | "failed" | "interrupted",
 "stage": "queued" | "generating" | "parsing" | "evaluating" | "done" | null,
 "created_at": <RFC3339 UTC>, "updated_at": <RFC3339 UTC>,
 "finished_at": <RFC3339 UTC | null>,
 "progress": {"done": int, "total": int},
 "resumed": bool, "repaired_tail_bytes": int,
 "metrics_path": str | null,
 "error": {"type", "message"} | null}
```
`created_at` and `updated_at` are never null (v0.5, AQ5): the manifest is first written when the run is created, so both exist from the start. `finished_at` is null exactly while `status` is `queued` or `running`, and non-null exactly when it is terminal; a model validator enforces both directions. `status` and `stage` are closed sets, and they are exactly what D8's `RunDetail` reports, so the API maps rather than invents. `queued` and `running` are included, because an API job is written to disk before it starts. `run_end.status` keeps its three terminal values. Every update rewrites the file atomically (temp file plus `os.replace`). The CLI writes `status: "running"` at the start; the API job runner writes `"queued"` when the job is accepted. On API start-up, a run still marked `queued` or `running` becomes `interrupted` (D8).

**`metrics_seed{n}.json`:** `{"schema_version": 1, "run_id", "seed", "subset": bool, "n_queries": int, "source": "official_eval_score" | "subset_aggregate", "scores": {<the six official keys, verbatim, as rates in [0, 1]>}, "detailed": <eval.py's second return value, or the subset equivalent>}`.

**`metrics.json`:** `{"schema_version": 1, "run_id", "kind", "config_hash", "created_at", "finished_at", "subset": bool, "n_queries": int, "seeds": [int], "post_check_mode": str, "metrics": {<official key>: {"per_seed": {"<seed>": float}, "mean": float, "sd": float | null}}, "non_delivery": {<failure_reason>: int}, "parse": {"attempted": int, "ok": int, "failure_rate": float | null}, "tokens": {"input" | "output" | "thinking": {"mean", "median", "p95"}}, "latency_ms": {"wall" | "load" | "prefill" | "generation": {"mean", "median", "p95"}}}`. `sd` is the sample SD (ddof=1), or null with fewer than two seeds. Token and latency statistics are over the per-(query, seed) values, excluding warm-ups; `p95` is the nearest-rank percentile (index `ceil(0.95 n) - 1` of the sorted values); a statistic over an empty set or over values that are all null is null. Rates are in [0, 1] everywhere; only the CLI's printed report shows percentages.

Confirmed in v0.5 (AQ7): `parse.failure_rate` is `1 - ok / attempted`, and **null when `attempted == 0`** (for example a run where every call failed before parsing); the field is required but nullable, and MLflow skips `parse_failure_rate` when it is null. `Metrics.created_at` and `Metrics.finished_at` are non-null UTC, because `metrics.json` is only written once a run has finished. The committed `schema.json` has one root, which validates a single `events.jsonl` line; `RunManifest`, `MetricsSeed` and `Metrics` sit under its `$defs`, and anything validating those files points at `#/$defs/<Model>`.

**Where the rules live (v0.6; FQ2, FQ3).** The pydantic models in `runlog/schema.py` are the **normative** validator. Every writer and reader in this repository uses them, and nothing outside Python validates run logs. `schema.json` is a **structural** contract: types, required keys (including the seven `run_end.counts` keys, accepted as foundation built them), enums and bounds. It does not carry `if`/`then`, because pydantic cannot generate it and hand-written fragments would drift from the models. The cross-field rules are instead written into the generated schema as field `description` text, so a reader of `schema.json` sees them:
- warm-up nulls: `llm_call.query_id` and `.seed` may be null **only when** `role == "warmup"` (v0.7, FQ4: one-directional, as the v0.4 Q9 decision and the code say; a warm-up call *may* carry a `query_id` and `seed`, and the Phase 1 pipeline writes null for both);
- `RunManifest.finished_at` is null iff `status` ∈ {queued, running};
- `parse.failure_rate` is null iff `attempted == 0`;
- `ok <= attempted`, and `failure_rate == 1 - ok / attempted`.

The last two are **enforced** by the model as well (FQ3): `ok <= attempted`, and when `attempted > 0`, `failure_rate` equals `1 - ok / attempted` within an absolute 1e-12. A writer computes the value with that expression and never rounds it.

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

**Field decisions confirmed in v0.4 (Q9), all as M0 built them unless noted:**
- `llm_call.query_id` and `.seed` are null **only** when `role == "warmup"`, and a model validator enforces that. The runtime-reported counts (`input_reported`, `input_cached_reported`, `output_reported`), every `timing_ms` field except `wall_client`, `done_reason`, `output_text` and `thinking_text` are nullable, because a failed call reports none of them. `tokens.input`, `tokens.output_visible`, `tokens.output_thinking` and `timing_ms.wall_client` are always present.
- The `error` event carries `{type, message, traceback}`.
- `run_end.error` is `{type, message}` or null; `metrics_path` is nullable; `counts` is `dict[str, int]` and MUST contain at least `queries`, `seeds`, `pairs_total`, `pairs_done`, `delivered`, `llm_calls`, `errors`. **The schema enforces those seven keys** (v0.5, AQ6): a `run_end` without any of them fails validation, and extra keys are still allowed. Documentation alone would let the pipeline and the API drift apart.
- `dataset.files_sha256` maps file name to sha256.
- `eval.commonsense` and `eval.hard` are both nullable: the bridge returns null groups for an undelivered plan, and `hard` is also null when D5's gating skipped it.
- `query_result.totals.load_ms`, `.prefill_ms` and `.generation_ms` are nullable; `wall_ms` and `parse_ms` are not.
- `env` additionally carries `iogpu_wired_limit_mb: int | null` and `gpu_recommended_max_working_set_bytes: int | null` (§6, A-005). Null means the value could not be read.
- Free strings: `mode`, `context_mode`, `split`, `order`, `role`, `agent_id`, `parser_version`, `prompt_version`, `failure_reason`. Closed sets: `kind` (batch|single), `query_result.status`, `run_end.status`, and the manifest's `status` and `stage`.

Schemas are pydantic models in `src/tripartite/runlog/schema.py`, and JSON Schema is exported to `src/tripartite/runlog/schema.json`. `writer.py` flushes and fsyncs each line. `reader.py` streams events.

**Resume.** `tripartite run start --resume <run_id>` skips (query, seed) pairs that already have a `query_result`, appends to the same `events.jsonl`, and sets `resumed: true` in the manifest. **What it compares (v0.10, M4 AQ4/AQ5, as built):**
- It refuses a `succeeded` or `queued` run.
- The stored `run_start.config` must re-hash to its own `config_hash`, so the config is exactly the one that was run.
- The run's stack pins must equal the current ones (Ollama version, model digest, `num_ctx`), as must the prompt sha256, the parser version and the calibrated mode. **The `runtime.env` block** recorded in `run_start.env.ollama_env` must equal the current one (FU-26, merged).
- **Full runs, all 180 queries (FU-29, merged; v0.11, AQ4):**
  - A dirty tree refuses the resume unless `--allow-dirty` is passed.
  - A current git commit different from the run's first `run_start.env.git_commit` refuses the resume, naming both commits; **`--allow-dirty` does not override this**.
  - Once any session of the run used `--allow-dirty`, every later `run_start` keeps `allow_dirty: true`, and the flag is recorded whenever it is passed (AQ5).
  - Subset runs (smoke) may resume across commits and from a dirty tree.
- **Order of checks (deviation 4, accepted):** the dirty-tree refusal happens before the log is touched. The commit and `runtime.env` checks run after `repair_tail`, so a refused resume may already have cut off a half-written last line. That is acceptable: `repair_tail` removes only a crash artefact that any resume would remove, and keeps it in `events.corrupt-<ts>.txt`.
- `make baseline` and `make resume` cannot pass `--allow-dirty`. A run that needs it is started with `uv run tripartite run start … --allow-dirty`. That friction is intended, and there is no Makefile change (AQ6).
- `allow_dirty` is currently an undeclared extra field on `run_start` (the model allows extras). FU-30 declares it as `allow_dirty: bool = False`. Nothing blocks on that (AQ3).

**Other D7 details as built in M4 (accepted v0.10):**
- `per_plan_eval_seed{n}.jsonl` lines are `{"idx", "query_id", "delivered", "commonsense", "hard"}`, with `idx` as in `plans_seed{n}.jsonl` and each group's keys in `eval.py`'s `key_dict` order (AQ3).
- The truncation scan reads only the server-log bytes written since this run or resume session started (AQ6).
- `metrics.json`'s `created_at` and `finished_at` come from the manifest, so a rescore reproduces them byte for byte (AQ7).
- `rescore_run` lives in `pipeline/run.py` and scores through the same `metrics.write_scores` as the run (R1 compares one code path with itself).
- In fake mode, `run_start.model.runtime` is `"fake"` and the tokenizer is `fake-bytes`/`v1`.
- The model lock is taken with `acquire_model_lock()`, which returns the held `FileLock` (`ModelLockHeldError` if held), because one run holds it across `open_run`, `execute` and `close_run`.

**A crash can leave a half-written last line (Q10).** The reader stays strict by default, because a corrupt log is normally a bug. Resume alone repairs, and only the tail:
- `runlog.reader.repair_tail(path) -> int` inspects the **final line only**. If the file does not end with `\n`, or that last line is not a decodable JSON object with a valid envelope, the file is truncated at the offset of the last newline before it, and the discarded bytes are written to `runs/<run_id>/events.corrupt-<UTC ts>.txt`. It returns the number of bytes discarded, 0 when there was nothing to repair.
- A malformed line anywhere other than the end is a hard `RunLogError`, never repaired. This is the crash model in A-023: the writer appends whole lines and fsyncs, so only the last line can be partial.
- `tripartite run start --resume` calls `repair_tail` before reading, records the result as `repaired_tail_bytes` in the manifest, and writes its new `run_start` event with `resumed_from: <the same run_id>`. Nothing else in the pipeline or the API calls it, and `make eval`, `reproduce-check` and the API read with the strict reader, so a corrupt run cannot be scored silently.
- `read_events(path, tolerate_partial_tail=False)` gains that keyword for read-only callers that want the same leniency without touching the file; resume uses `repair_tail` instead, because it is about to append.
- Confirmed in v0.5 (AQ7): `tolerate_partial_tail` skips **only** a final line that fails `repair_tail`'s own test (no trailing newline, not decodable JSON, not an object, or no valid envelope). A complete final line with a valid envelope but an invalid payload is a bug, not a crash artefact, so it still raises `RunLogError`, and `repair_tail` does not remove it either.
- Accepted in v0.5 (extra): a line that is not valid UTF-8 raises `RunLogError`, like any other undecodable line. If it is the final line, it counts as undecodable for `repair_tail` and is repaired; anywhere else it is a hard error.

**MLflow (Q4)** is a derived, disposable index for comparing runs across time in a UI. It is **not** the record: JSONL is the source of truth, and if they disagree, JSONL wins. The API never reads MLflow, and it is not part of any exit criterion.

- **Manual only.** The pipeline does **not** sync at the end of a run (changed in v0.4, to keep M4 free of MLflow). Syncing happens through `make mlflow-sync RUN=<run_id>` → `tripartite log mlflow-sync --run <run_id>`.
- **Scheduled to M6** (foundation), after M4, because it needs a real run directory to test against. Files: `src/tripartite/runlog/mlflow_sync.py` and `src/tripartite/runlog/cli.py`.
- Store: local file store `./mlruns` (gitignored). Experiment: `tripartite`. Run name: the `run_id`.
- **Only `kind == "batch"` runs are synced.** A single run exits 0 with `skipped: run <id> is kind=single`.
- Tags: `tripartite.run_id`, `tripartite.kind`, `tripartite.config_hash`, `tripartite.prompt_version`, `tripartite.parser_version`, `tripartite.model_tag`, `tripartite.model_digest`, `tripartite.evaluator_commit`, `tripartite.dataset_revision`, `tripartite.git_commit`, `tripartite.architecture_version`.
- Params: `config_hash`, `model_tag`, `model_digest`, `quant`, `num_ctx`, `num_predict`, `temperature`, `top_p`, `top_k`, `min_p`, `seed_list` (JSON array), `prompt_version`, `parser_version`, `evaluator_commit`, `dataset_revision`, `n_queries`, `subset`.
- Metric keys (snake_case of the official names): `delivery_rate`, `commonsense_micro`, `commonsense_macro`, `hard_micro`, `hard_macro`, `final_pass_rate`, each logged once per seed with `step = seed`, plus `<key>_mean` and `<key>_sd` at `step = 0`, plus `tokens_input_mean`, `tokens_output_mean`, `latency_wall_ms_median` and `parse_failure_rate`. Values are rates in [0, 1].
- Artifacts: `manifest.json`, `metrics.json` and every `metrics_seed*.json`. Never `events.jsonl`, plans or prompts.
- **Idempotent.** Sync looks for an existing MLflow run whose `tripartite.run_id` tag matches; if it finds one it deletes it and creates a new one, so repeated syncs converge on one run per `run_id` and never duplicate. Anything it cannot find (a missing `metrics.json`) is an error, not a partial sync.

## D8 (h). Backend and UI contract (Phase 1)

**Process model.** `uvicorn tripartite.api.app:app --host 127.0.0.1 --port 8000`. There is one in-process job runner: an asyncio task with blocking work in a thread. At most one job runs at a time and there is no queue. Evaluation batch runs are **CLI-only**, and the API cannot start them. Run history comes from scanning `runs/*/manifest.json` (plus `metrics.json` / the single-run result); there is no database. When the server starts, any single run left in `running` state is marked `interrupted`, and a `run_end` event is written.

**Endpoints** (JSON; pydantic response models; OpenAPI exported to `api-contract/openapi.json`):
- F1:
  - `GET /api/health` → `Health {status: "ok", model_reachable: bool, model_digest_ok: bool, evaluator_ready: bool}`, served from `app.py` (accepted as built in F1). Each flag has one owner and one function, and the route only calls them (FU-19, after FU-17 and FU-18):
    - `model_reachable`, `model_digest_ok`: `tripartite.llm.doctor.model_reachable` / `model_digest_ok` (model session; D4 §Health checks). Each takes at most about 1 s and never loads the model. `true` in fake mode.
    - `evaluator_ready`: `tripartite.evaluation.readiness.evaluator_ready() -> bool` (data-eval, FU-18). It is cheap by construction: `os.stat` only, with **no hashing** and no subprocess. It checks that `vendor/travelplanner/VENDOR.lock` exists; that the evalenv interpreter `evalenv/.venv/bin/python` exists; that `data/MANIFEST.json` loads and has `database_files` recorded; that each of the 8 database files exists with exactly the recorded byte size; and that `raw/validation.csv` exists with its recorded size. Full hash verification stays in `tripartite data verify` / `make doctor`. `true` when `TRIPARTITE_EVAL_BRIDGE=fake`, and `false` for an unrecognised value of that variable (accepted as built, v0.9). Merged in `802e575`. **`evalenv/.venv` exists only after `make setup`**, so F2 and any API server that runs real jobs must run `make setup` first; otherwise `evaluator_ready` is false by design.
    - `status` is always `"ok"` while the process answers; the flags never turn the endpoint into an error.
  - `GET /api/queries` → `QueryList {items: [QueryItem {query_id, query}]}` (180, in order; only PlannerInput fields). If the data is missing or invalid (the loaders raise `DataError`), both query routes return **503** with `ErrorDetail {detail}`, where `detail` is the `DataError` message; never FastAPI's default 500 (v0.8, F1 AQ-3; FU-23). The 503 is documented in the OpenAPI `responses`.
  - `GET /api/queries/{query_id}` → `QueryItem`; 404 with `ErrorDetail {detail}` if unknown (as built in F1); 503 as above.
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

Types are generated from `api-contract/openapi.json` into `web/src/api/types.gen.ts`. The canonical command (Q8), run from `web/`, is exactly the one CI diffs against:

```
npx --no-install openapi-typescript ../api-contract/openapi.json -o src/api/types.gen.ts
```
`openapi-typescript` is a pinned devDependency in `web/package.json`, and `npm run types` MUST be exactly that command, so that regenerating locally and the CI check can never differ. CI writes to a temporary file and diffs. The dev server proxies `/api` to `127.0.0.1:8000`. There is no global state library; use React state plus `fetch`/`EventSource`. The UI never shows evaluator-only query fields except through `constraints`.

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
├── prompts/  (sole_planning_direct_v1.txt, .editorconfig)    model
├── reports/  (context_report.json, token_calibration.json)            model
├── results/phase1/<run_id>/…                  model
├── api-contract/openapi.json                  api
├── scripts/vendor_check.py                    data-eval
├── scripts/ci/repo_hygiene.py                 foundation
├── src/tripartite/
│   ├── __init__.py  cli.py                    foundation
│   ├── runlog/  (schema.py, schema.json, writer.py, reader.py, mlflow_sync.py, cli.py)   foundation
│   ├── data/    (planner_inputs.py, download.py, manifest.py, cli.py)                    data-eval
│   ├── evaluation/ (records.py, bridge_client.py, constraints.py, aggregate.py, readiness.py, cli.py)  data-eval
│   ├── config.py                                                                         model
│   ├── llm/     (ollama_client.py, fake_client.py, chat_template.py, tokenizer.py, errors.py, doctor.py, context.py, calibration.py, cli.py)   model
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
│   ├── scripts/  (test_repo_hygiene.py)   foundation
│   ├── data/  evaluation/  fixtures/eval_golden/  fixtures/synthetic_data.py  fixtures/__init__.py   data-eval
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
| `setup` | `uv sync --locked` · `uv sync --locked --project evalenv` (v0.8, FU-22) · `npm ci --prefix web` |
| `serve-model` | `ollama serve` with the D4 env (foreground) |
| `pull-model` | `tripartite model pull` |
| `doctor` | `tripartite data verify` · `tripartite model doctor` |
| `data` | `tripartite data fetch` · `tripartite data verify` |
| `measure-context` | `tripartite model measure-context` · `tripartite model calibrate` (the calibration needs `make serve-model` running) |
| `baseline` | `tripartite run start --config $(CONFIG)`, default `configs/baseline.yaml` |
| `baseline-smoke` | `$(MAKE) baseline CONFIG=configs/smoke.yaml` |
| `resume` | `tripartite run start --resume $(RUN)` |
| `eval` | `tripartite run rescore --run $(RUN)` (v0.8: model session, M4; FU-21) |
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

- `.gitignore` (the repository is public, so this is a safety boundary, not tidiness — see §8): `.venv/`, `evalenv/.venv/`, `data/*` with `!data/MANIFEST.json`, `vendor/travelplanner/database/*` with `!vendor/travelplanner/database/README.md`, `/runs/`, `/mlruns/` (anchored to the repository root, so a future `web/src/runs/` is not swallowed — Q7), `web/node_modules/`, `web/dist/`, `*.log`, `.env`, `.env.*`, `*.zip`, the tool caches (`__pycache__/`, `*.py[cod]`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.import_linter_cache/` (accepted as built, v0.5), `*.egg-info/`, `dist/`, `build/`) and the local machine and agent state `.DS_Store`, `__MACOSX/`, `._*` (v0.6: macOS archive clutter, for a zip the user unpacks by hand — `data fetch` never writes them), `.claude/settings.local.json`, `.claude/worktrees/` (Q11, B5). `results/` is **not** ignored: `results/phase1/<run_id>/{manifest.json,metrics.json,reproduce_check.json}` is committed on purpose, and those three files carry no plan text and no database rows.
- `NOTICE`: TravelPlanner attribution (MIT code, CC BY 4.0 data) and Qwen3 licence reference.

**Shared files across milestones.** Three paths are needed by every session but owned by one: `Makefile`, `.github/workflows/ci.yml` and `pyproject.toml` (foundation). The rule, so that no session ever edits another's path:

1. **Written once, complete, at M0.** Foundation writes the final Makefile, CI workflow and dependency list from this document, covering every milestone. Nothing later is expected to change them.
2. **Guard by existence; mandatory on appearance.** Every CI step and Makefile target whose input a later milestone creates is guarded by that path existing (`if: hashFiles('<path>') != ''` in Actions, `test -e` in the Makefile). A guarded step skips with the printed line `skipped: <path> not present yet`, and it is mandatory as soon as the path exists. Paths only ever appear, so no check can be silently switched off, and the CI summary lists what was skipped. The guard list (Q2, B1), each with its guard path:

   | Target or step | Guard path | Milestone |
   |---|---|---|
   | `setup`: `uv sync --project evalenv` | `evalenv/pyproject.toml` | M2 |
   | `setup`: `npm ci --prefix web` | `web/package.json` | W1 |
   | `serve-model` | `configs/stack.yaml` | M3 |
   | `api`, `openapi` | `src/tripartite/api/cli.py` | F1 |
   | `web`, `e2e-local` | `web/package.json` | W1 |
   | CI: vendor integrity check | `vendor/travelplanner/VENDOR.lock` | M2 |
   | CI: test-split refusal tests | `tests/data/test_loader_refusals.py` | M1 |
   | CI: aggregator golden test | `tests/fixtures/eval_golden/` | M2 |
   | CI: OpenAPI drift check | `api-contract/openapi.json` | F1 |
   | CI: `uv lock --check --project evalenv` (v0.8, FU-22) | `evalenv/uv.lock` | M2 |
   | CI: web job | `web/package.json` | W1 |

   A guarded step inside a larger target prints the skip line and the target continues. A guarded target invoked by name prints the skip line and its recipe exits 1, which makes `make` itself exit 2 (Q12, B2) — the point is the non-zero exit and the message, not the number.
3. **Package skeleton at M0.** Foundation creates `src/tripartite/{data,evaluation,llm,planner,parse,pipeline,api,runlog}/__init__.py` as empty files, plus empty `tests/{data,evaluation,llm,planner,parse,pipeline,api,leak}/` directories with `__init__.py`. This is a one-time creation: from that commit on, each directory including its `__init__.py` belongs to the owner named in the tree above. It exists so that `mypy` and the D3 import-linter contracts, which name these modules, resolve and run from M0 onwards.
4. **Owner of the vendor integrity check:** the **data-eval** session owns `scripts/vendor_check.py`, together with `vendor/` and `VENDOR.lock` (M2). CI calls it as a guarded step. Foundation owns `scripts/ci/repo_hygiene.py` (§8), which always runs.
   **Which files it checks (v0.6).** The check covers the **git-tracked** set, `git ls-files -z -- vendor/travelplanner`, and never walks the file system. Every tracked file must appear in `VENDOR.lock` with a matching sha256, and every lock entry must be tracked and present. Under `vendor/travelplanner/database/`, only the upstream `README.md` is tracked and locked. The 8 unpacked data files and `.unpack-tmp/` are untracked and gitignored, so the check never sees them, and it passes both on a fresh clone and after `make data` on the user's Mac. The unpacked database is verified separately, by `tripartite data verify`, against the sizes in code and the per-file sha256 in `data/MANIFEST.json` (D5 §Database — unpacking). If a database file were ever force-added to git, both `repo_hygiene.py` (§8.3, force-added) and this check (a tracked file missing from the lock) would fail.
5. **Read-only shared paths (the rest of the sweep).** These are owned by one session and consumed by another, always read-only, so nobody needs to edit another's path. The consumer treats a missing file as a clear error, never as a reason to edit: `data/MANIFEST.json` (data-eval → model's `doctor`); `api-contract/openapi.json` (api → web's type generation and the CI drift check); `reports/token_calibration.json` (model → the api job runner, D4 §Before calibration has run); the output of `tripartite eval smoke-ids` (data-eval → `configs/smoke.yaml`, committed by model, D1); and the lock file `runs/.model.lock` plus the run directory layout (D7), which the model and api sessions share by this contract rather than by shared code. `tests/conftest.py` (foundation, M0) holds only the autouse fake-mode environment fixture; the `local` marker is registered in `pyproject.toml` (B4). Each session adds its own `conftest.py` inside the test package it owns.
6. **Escape hatch.** If a session finds it needs a new dependency, Makefile target or CI step that the M0 versions cannot express as a guarded step, it does not edit those files. It writes the request under "Architecture questions" in its PR. The architecture session updates this document, and the foundation session makes the edit in its own follow-up PR.

**Conventions every session follows (recorded from M0's findings, C):**
- Each `<pkg>/cli.py` exposes `app: typer.Typer`, which `src/tripartite/cli.py` loads lazily by module path. Typer 0.27 no longer depends on click, so sessions use Typer's own API and never `import click`.
- The API listens on `127.0.0.1:8000` (D8). If another local server holds the port during a manual check, use another port for that check only and say so in the PR, as F1 did with 8001; code and docs keep 8000 (v0.8).
- A `DeprecationWarning` from `fastapi.testclient` about `httpx` is accepted as a warning. There is no follow-up while pytest does not treat warnings as errors; do not add or swap HTTP client dependencies to silence it (v0.8).
- `mypy --strict` with the pydantic plugin applies to all of `src/`. New code is fully annotated; `type: ignore` needs a reason in the PR.
- `make test-local` must not fail merely because no local test exists yet. Its recipe treats pytest's exit code 5 ("no tests collected") as success and prints `no local tests collected` (C). From M3 on, local tests exist, and an empty collection in a PR that touches the paths in D1's local gate is a review flag, not a pass.

**"CI green at M0" means exactly:** `ruff check` and `ruff format --check` pass over `src/` and `tests/`; `mypy src` passes over the empty packages plus `runlog/` and `cli.py`; `lint-imports` runs every D3 contract and they hold vacuously; `pytest -m "not local"` collects and passes the runlog tests (schema round trip, writer/reader, unknown-event-type tolerance) and the repository-hygiene tests in `tests/scripts/test_repo_hygiene.py` (added in v0.5, AQ8), and nothing else; `scripts/ci/repo_hygiene.py` passes; and each guarded step prints its skip line. The web job does not run, because `web/package.json` does not exist yet.

**Build order** (a milestone may start when its dependencies are merged to `main`):

| # | Session | Milestone | Depends on |
|---|---|---|---|
| M0 | foundation | Skeleton, all root files, CI green on an empty package, runlog schema + writer/reader + tests | none |
| M1 | data-eval | `data fetch/verify` (HF files, plus the database zip checked against the D5 pin), `PlannerInput` loader, test-split refusal, `records.py` | M0 |
| M2 ✓ | data-eval | `evaluation/cli.py` with `tripartite eval smoke-ids` (first, so M4 can commit `configs/smoke.yaml`; D1), `records.to_bridge_row` (FU-15), vendoring + VENDOR.lock, `scripts/vendor_check.py` (tracked files only), database unpacking and per-file manifest (D5), evalenv, bridge, constraints, aggregate, golden fixtures | M1 |
| M3 ✓ | model | config.py + `configs/{stack,baseline,single}.yaml` (not `smoke.yaml`, which moves to M4), Ollama client, fake client, **fake tokenizer and fake chat template with `tokenizer_from_env()` / `template_from_env()` (D4 §Fake-mode tokenizer; delivered after M3 as a model follow-up, `28b6a01`, because M3 was built against v0.7)**, chat template, tokenizer, `doctor`, `measure-context`, `calibrate` + `reports/token_calibration.json`; tests use `TRIPARTITE_DATA_DIR` + the synthetic set. The health functions (FU-17) landed in the same follow-up | M1, FU-13, FU-14 |
| M4 ✓ | model | Prompt v1, parser, pipeline (run/resume/lock/metrics), **`tripartite run rescore` (D1 Phase 0 exit item 5)**, leak tests, `configs/smoke.yaml` from `tripartite eval smoke-ids` → **Phase 0 exit** (`make baseline-smoke`, `make eval`) | M2 ✓, M3 ✓, the model follow-ups ✓, FU-16 ✓, FU-20 ✓, **and A-009 confirmed ✓** (A-030, 2026-09-28): all met; see §M4 readiness. Before M4 merges: FU-25. Before the Phase 0 exit: FU-21, FU-22. (The v0.2–v0.8 gate, "M4 MUST NOT start before A-009 is confirmed", is satisfied.) |
| F1 ✓ | api | health, queries, OpenAPI export; CI tests use `TRIPARTITE_DATA_DIR` + the synthetic set | M1, FU-13, FU-14 |
| W1 | web | Vite skeleton, generated types, query picker (including the 503 state) | F1 ✓, FU-23 |
| F2 | api | POST runs, job runner, run detail, SSE, and the health wiring (FU-19); fake mode is synthetic-only (FU-27); tests run with `TRIPARTITE_LLM=fake` and `TRIPARTITE_EVAL_BRIDGE=fake`, using the fake tokenizer through the environment switch; real jobs need `make setup` (D8) | M4 ✓, FU-17 ✓, FU-18 ✓, FU-27 |
| W2 | web | Run + live stage + plan cards | F2 |
| W3 | web | Constraint pass/fail | F2 |
| W4 | web | Tokens and latency | F2 |
| F3 | api | History, batch items, item detail | F2 |
| W5 | web | Run history | F3 |
| M5a.1 | model | `pipeline/reproduce.py` + `tripartite run reproduce-check` exactly as in D9 §M5a: `reproduce-check`, with its tests; one PR, merged with a merge commit (never squashed) | M4 ✓, FU-26 ✓, FU-29 ✓ |
| M5a.2 | model (operations; no code) | The two full baselines, one after the other, from a dedicated worktree pinned at one commit `C` on `main` (D9 §M5 operations); then `make reproduce-check` | M5a.1 merged; `C` = `main` after M5a.1 |
| M5a.3 | model | PR adding `results/phase1/<run_id>/{manifest.json, metrics.json, reproduce_check.json}` for both runs (D1 Phase 1 exit item 4) | M5a.2 with `reproduce-check` passing (exit 0), or an architecture ruling on its failure |
| M5b | model | `make e2e-local` → with M5a: **Phase 1 exit**. Before it, re-run `make eval` on both M5a runs at the then-current `main` if anything under `src/tripartite/{parse,pipeline,evaluation}`, `evalenv/` or `vendor/` changed after M5a (R1, R2 must still hold) | M5a.3, W5 |
| M6 | foundation | `runlog/mlflow_sync.py` + `runlog/cli.py` (D7 §MLflow), and FU-30. Not part of any exit criterion; may land any time after M4 | M4 ✓ |

**Merged to main (✓ in the table):** M0 (`3dccb88`, merged in `ce6645e`); M1 (`c5190c5`, merged in `7d5303f`); M2 (`5385ea2`, merged in `8378f2a`, PR #7); F1 (`d408cdd`, merged in `af2f1b9`, PR #8); M3 (`88d9555`, merged in `2c2367c`, PR #9); M4 with FU-25 (`4729292`, merged in `af77514`, PR #13). Foundation FU-21/FU-22: `39c8aeb`, merged in `9df47a8` (PR #12). Model FU-26/FU-27/FU-29: `f62fe29`, merged in `dba2ac2` (PR #14). Model follow-ups after M3: `e7043f7`, merged in `28b6a01` (PR #11). Data-eval follow-ups: `0efdea5`, merged in `802e575` (PR #10). Follow-ups: see Follow-ups.

**M4 readiness (v0.9).** Everything M4 depends on is merged or recorded:

| Dependency | State |
|---|---|
| M2 (bridge, aggregate, golden fixtures, `smoke-ids`, `to_bridge_row`) | merged, `8378f2a` |
| M3 (model layer, configs, context gate, calibration) | merged, `2c2367c` |
| Model follow-ups (fake tokenizer and template, FU-17) | merged, `28b6a01` |
| FU-16 (canaries), FU-20 (`OfficialScores`) | merged, `802e575` |
| A-009 (prompt example provenance) | confirmed, A-030 |
| `reports/context_report.json`, `reports/token_calibration.json` (mode `total`) | committed in M3 |

- **Must land before M4 starts:** nothing.
- **Must land before M4 merges:** FU-25 (fake mode refuses the committed report paths). M4's tests run in fake mode and could otherwise overwrite the committed reports.
- **Can land in parallel, required before the Phase 0 exit:** FU-21 (`make eval` → `tripartite run rescore`) and FU-22 (`--locked` syncs and the evalenv lock check in CI).
- **In parallel, not needed by M4:** FU-19 (blocks F2), FU-23 (blocks W1), FU-6/M6.

**Scheduling M5 (v0.10).** Yes, M5's two full runs may start before W1–W5. Batch runs are CLI-only (D8) and never touch the UI; only `e2e-local` needs it. So M5 is split into **M5a** (the runs, reproduce-check, results) and **M5b** (`e2e-local` and the Phase 1 exit). Both M5a runs must come from the **same commit**, one after the other, so that R3 compares like with like. While M5a holds the model lock (about 17 h across both runs), an API in real mode gets 409; F2 and web development continue in fake mode on synthetic data.

**Readiness lists (v0.10):**

| Milestone | Depends on | State |
|---|---|---|
| F2 | M4 | merged, `af77514` |
| | FU-17 (model health checks) | merged, `28b6a01` |
| | FU-18 (`evaluator_ready`) | merged, `802e575` |
| | FU-19 (health wiring) | part of F2 (api); not merged |
| | FU-27 (fake mode synthetic-only, item 4b) | model; not merged; must land before F2 merges |
| | `make setup` before any real job (D8) | operational |
| W1 | F1 | merged, `af2f1b9` |
| | FU-23 (503 on missing data) | api; not merged; must land before W1 merges |
| M5a | M4, the Phase 0 exit | met (D1) |
| | FU-21, FU-22 | merged, `9df47a8` |
| | FU-29 (clean-commit guard) | model; not merged; must land before M5a starts |
| | Open question 1 (runner cache) | NEEDS APPROVAL; if approved, FU-26 merged and verified before M5a starts |
| | D9 §M5 operations | operational |
| M5b | M5a, W5 | not started |
| M6 | M4 | merged; M6 may start now (FU-6) |

**M5 operations (v0.10, relayed item 4d).** Before each full run:
- `main` is at a clean commit: `git_dirty` must be `false` in the manifest. The smoke run was dirty; a full run must not be (FU-29 enforces it).
- Other apps are closed, and the Mac is kept awake for the whole run (for example `caffeinate -dimsu` in the terminal that runs `make baseline`).
- The dedicated server is restarted (`make serve-model`) so that the runner's prompt cache starts empty, and the desktop-app server on 11434 has no model loaded (doctor).
- `make doctor` passes, and swap used is noted before and after (A-043, A-050).

**Readiness lists (v0.11; these supersede the v0.10 lists above):**

| Milestone | Depends on | State |
|---|---|---|
| M5a.1 (`reproduce-check`) | M4 | merged, `af77514` |
| | FU-26 (cache off), FU-29 (clean-commit guard) | merged, `dba2ac2` |
| | the spec in D9 §M5a: `reproduce-check` | v0.11 |
| | | **may start now** |
| M5a.2 (two runs) | M5a.1 | not started; merge it first |
| | commit `C` = `main` right after M5a.1's merge; a dedicated worktree at `C` | operational |
| | D9 §M5 operations, including a server restart and `make doctor` | operational |
| M5a.3 (results PR) | M5a.2 finished; `reproduce-check` exit 0 or an architecture ruling | not started |
| F2 | M4 | merged, `af77514` |
| | FU-17, FU-18 | merged, `28b6a01`, `802e575` |
| | FU-27 (fake mode synthetic-only) | merged, `dba2ac2` |
| | FU-19 (health wiring) | part of F2 (api); not merged |
| | | **may start now**. While M5a.2 holds the model lock, test real mode only outside the run window (409 otherwise) |
| W1 | F1 | merged, `af2f1b9` |
| | FU-23 (503 on missing data) | api; not merged; must land before W1 merges |
| W2 | F2 | not started |
| | FU-28 (`tripartite data synthetic`) | data-eval; not merged; must land before W2 starts its fake-mode development loop |
| M5b | M5a.3, W5 | not started |
| M6 | M4 | merged; **may start now**, with FU-30 |

**M5a: `reproduce-check` (v0.11; built in M5a.1 by the model session).** `tripartite run reproduce-check --run <a> --run2 <b> [--allow-different-commit]`, in `pipeline/reproduce.py` (`make reproduce-check RUN=a RUN2=b`).
- **Preconditions** (any failure → exit 2, nothing written). Both runs exist, are `succeeded` and have equal `config_hash`, equal stack pins (Ollama version, model digest, `num_ctx`, `runtime.env`, tokenizer revision), equal prompt sha256, parser version and calibrated mode. Their first `run_start.env.git_commit` must be equal unless `--allow-different-commit` is passed. That flag exists for diagnostics only (for example two smoke runs); it adds a warning, and its output can never be used for the Phase 1 exit.
- **R1 (re-scoring, exact).** For each run, call the same `rescore_run` path as `make eval`, writing to that run's `rescore-<ts>/`, and compare every scoring output byte for byte with the original: `plans_seed{n}.jsonl`, `per_plan_eval_seed{n}.jsonl` and `metrics_seed{n}.json` for each seed, plus `metrics.json` (10 files for a 3-seed run). R1 passes if every file of both runs is identical.
- **R2 (re-parsing, exact).** For each run and each (query, seed) with a `query_result`, take the `output_text` of the call that produced its plan (the last `llm_call` for that pair with `error: null`). Re-run the current parser on it, serialize the plan exactly as the pipeline writes `plans_seed{n}.jsonl`, and compare it byte for byte with that pair's stored plan; also compare the failure reason. Pairs whose stored status is `llm_error` have no output and are skipped and counted. R2 passes if there are no mismatches in either run.
- **R3 (regeneration, tolerance).** For each of the six official metrics, take the 3-seed mean from each run's `metrics.json`: `diff_pp = abs(mean_a − mean_b) × 100`. It passes iff `diff_pp ≤ 2.0` (compared with a 1e-9 slack for float noise). R3 passes if all six pass.
- **Identity diagnostic (no threshold).** For each (query, seed) present in both runs, compare the two plan-producing `output_text` values byte for byte. Report `identical / total` and the fraction overall, per seed (`"0"`, `"1"`, `"2"`), and for **each seed's first call** in run order (`val-001` at seeds 0, 1, 2). The first-call figure separates any effect of a run's start, such as a cold server, from the rest (A-046, A-051).
- **Warnings** (printed and recorded; they do not change the exit code): either run has `allow_dirty: true` anywhere in its `run_start` events (AQ7); either run was resumed, with the number of sessions; `repaired_tail_bytes > 0`; `--allow-different-commit` was used; either run is a subset (`subset: true`).
- **Output file:** `runs/reproduce/<run_a>__<run_b>/reproduce_check.json`, schema:

```
{"schema_version": 1, "created_at": <RFC3339 UTC>, "tool_git_commit": <commit reproduce-check ran at>,
 "runs": {"a": RunRef, "b": RunRef},
 "preconditions": {"same_config_hash": true, "same_stack": true, "same_prompt": true,
                   "same_parser": true, "same_mode": true, "same_git_commit": bool},
 "r1": {"pass": bool, "per_run": {"<run_id>": {"files_compared": int, "mismatched": [<file name>]}}},
 "r2": {"pass": bool, "per_run": {"<run_id>": {"pairs_checked": int, "pairs_skipped_llm_error": int,
        "mismatched": [{"query_id", "seed"}]}}},
 "r3": {"pass": bool, "tolerance_pp": 2.0,
        "metrics": {"<official key>": {"mean_a": float, "mean_b": float, "diff_pp": float, "pass": bool}}},
 "identity": {"overall": Count, "per_seed": {"<seed>": Count}, "first_call": {"<seed>": bool}},
 "warnings": [str],
 "pass": bool}
RunRef = {"run_id", "git_commit", "config_hash", "allow_dirty": bool, "resumed": bool,
          "subset": bool, "n_queries": int, "seeds": [int]}
Count  = {"identical": int, "total": int, "fraction": float}
```
  `pass` = `r1.pass and r2.pass and r3.pass`. The file holds query_ids, seeds, file names and numbers only, never plan or output text, so it can be committed under §8.
- **What it prints:** one line per check (`R1 PASS|FAIL`, `R2 …`, `R3 …`), a six-row table of `mean_a`, `mean_b` and `diff_pp`, the identity fractions (overall, per seed, first calls), every warning, and the output path.
- **Exit codes:** 0 when R1, R2 and R3 all pass (warnings allowed); 1 when any of them fails (the file is still written); 2 for unmet preconditions or bad input (nothing written).
- **Tests (M5a.1).** Synthetic run directories built with the model fixtures cover: all pass; an R1 mismatch; an R2 mismatch; R3 at exactly 2.0 pp (pass) and 2.01 pp (fail); every precondition failure (exit 2); each warning; and the identity counts per seed and for first calls. A `local` test runs it on two smoke runs with `--allow-different-commit` if needed.

**M5a: if a check fails (v0.11).** Any failure stops M5a: no third run, no M5a.3, nothing under `results/phase1/`.
- **R3 fails:** raise an architecture question with `reproduce_check.json`, both runs' per-seed values and the seed-to-seed SD (A-016's trigger). The architecture session decides whether to change the tolerance or the decoding, or to run more runs. Re-running until it passes is not allowed.
- **R1 or R2 fails:** that is a determinism bug in scoring or parsing, not model noise. Raise an architecture question with the mismatching files or pairs. A fix lands on `main` as a new commit, and then `reproduce-check` is re-run with `--allow-different-commit` under an explicit ruling, because the runs' recorded `git_commit` stays the old one.

**M5a.2: order of work and the recorded commit (v0.11).** Your three-step proposal is adopted (M5a.1, M5a.2, M5a.3 in the build order).
- After M5a.1 merges (a merge commit, never squashed, as for every PR so far), let `C` = the commit at the tip of `main`. Create a dedicated worktree **pinned at `C`**, for example `git worktree add ../tripartite-m5a C`, detached at `C` rather than following `main`. Run `make setup`, `make data` and `make doctor` there.
- Both runs and any resumes happen in that worktree, so both record `git_commit = C`, even if `main` moves on meanwhile (for example the user committing a later `ARCHITECTURE.md`). No code changes happen in the worktree.
- M5a.3's PR adds only `results/phase1/…`. It is made from a normal branch off the then-current `main`; it does not need to be at `C`, and the recorded `C` stays reachable from `main` because merges are never squashed.

**M5a.2: resume procedure (v0.11).** If a full run is interrupted (sleep, crash, power):
- Use the same worktree, still at `C`, with no changes; check that `git status` is clean.
- Restart the dedicated server (`make serve-model`) and run `make doctor`.
- Then `make resume RUN=<run_id>`. Resume refuses a different commit, a dirty tree or a changed `runtime.env` (D7 §Resume).
- Note the interruption in the M5a.3 PR. `reproduce-check` warns about resumed runs, and the first call after a resume is computed cold, like a run's first call.

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
| Sandbox database | `sandbox_database.zip`, 59,039,278 bytes, sha256 `de345b0c243cd8c85355a264c5124db5db275327d2a38fa8685c6e69fabb650b` (first download 2026-09-25, trust on first use, A-013); per-file sizes (code) and sha256 (manifest) for the 8 unpacked files (D5) | `src/tripartite/data/manifest.py` and `data/MANIFEST.json` |
| Python | `.python-version` = `3.12.13`, the newest 3.12 uv can install, so CI matches local (B6) | repo |
| Python deps | `uv.lock`, `evalenv/uv.lock` | repo |
| Node / web deps | `web/.nvmrc`, `web/package-lock.json` | repo |
| Ollama | exact version | configs/stack.yaml |
| Model | `qwen3:8b-q4_K_M` + full sha256 digest | configs/stack.yaml |
| Model GGUF blob (derived, not checked) | `sha256-a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`, named by the pinned manifest (D4 §Runner prompt cache, v0.10) | this row only |
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

1. **Dataset files:** anything under the repository-root `data/` directory except `data/MANIFEST.json`, which holds names, revisions, sizes and sha256 only. The rule applies to paths *under* the directory; a root-level file that happens to be named `data` is not caught by it (v0.6, FQ1). That covers `validation.csv`, `validation_ref_info.jsonl` and every derivative, with **one named exception** (signed off in v0.8): `tests/fixtures/eval_golden/queries.jsonl`, which the CI golden test needs to recompute the official aggregates without the dataset. Each of its 180 lines holds exactly `query_id`, `level`, `days` and `constrained` (the names of the non-null local-constraint keys). It holds no query text, no reference information, no budget, no dates, no cities and no constraint values. The dataset is CC BY 4.0, attributed in `NOTICE`. Any other key, or any other derivative, needs its own sign-off (FU-24 adds a test that pins this key set).
2. **Any test-split artefact**, matched on the **file name only, never the whole path** (Q6): a file whose name is `test.csv` or `test_ref_info.jsonl`, or whose name matches `*test*ref_info*` **and** whose extension is a data extension (`.csv`, `.jsonl`, `.json`, `.parquet`, `.zip`, `.gz`, `.txt`). Both the name and the extension are compared **case-insensitively** (v0.5, AQ7), because macOS file systems are case-insensitive by default and `Test_Ref_Info.JSONL` is the same file to the user. Source and test files are never caught by this rule, so data-eval's own `tests/data/test_ref_info_alignment.py` (the A-007 check) is fine, while `tests/fixtures/test_ref_info.jsonl` is refused. D3 keeps the real files off the machine; this keeps them out of git even if one appears locally.
3. **The sandbox database:** `data/downloads/sandbox_database.zip` and everything unzipped under `vendor/travelplanner/database/` except the upstream `README.md`. It is a third-party download with its own licence (A-017), redistributed by its authors only.
4. **Run output:** the repository-root `runs/` and `mlruns/` directories in full — prompts, raw model output, plans, logs. The rule is anchored at the root (Q7), so a source directory that happens to be called `runs` elsewhere in the tree is unaffected. Only the three small `results/phase1/<run_id>/` files are published.
5. **Secrets and local agent state:** `.env` files, API keys, tokens, and `.claude/settings.local.json` and `.claude/worktrees/` (Q11) — Claude Code runs in this folder, and its local settings hold machine paths and tool permissions that are nobody else's business. `scripts/ci/repo_hygiene.py` refuses both paths as well, not only `.gitignore` (accepted in v0.5). The project has no API keys by design (₹0 cap, local models), so any key-shaped string in a diff is a mistake.

Enforcement: the `.gitignore` in D9 covers all of the above; `scripts/ci/repo_hygiene.py` (foundation; runs on every CI run, unguarded) fails the build if a file matches those patterns, is larger than 2 MB (lockfiles excepted), matches a key-shaped pattern (`sk-`, `hf_`, `ghp_`, `AKIA`), or is tracked although `.gitignore` ignores it (force-added). It checks tracked files **and** untracked files that are not ignored, which is a superset of "tracked" and catches a file before it is ever added (B3, accepted). The vendor integrity check (D9 §Shared files, item 4) additionally fails if `VENDOR.lock` lists a `*ref_info*` or `*.csv` path. D3's `test_test_split_forbidden` and `test_no_test_files_on_disk` cover the loading side.

Publishing the repository changes no decision above. The prompts, the vendored evaluator (MIT, attributed in `NOTICE`) and our own code (MIT) are publishable; the data and the runs are not.

# 9. Budget, and decisions for later phases (v0.11)

**Budget rule (user decision, 2026-10-07).**
- **API spend is ₹0, forever.** No hosted model API is used anywhere in this project, in any phase. Every model runs locally (D4), or on rented hardware the project controls (Phase 4 note below).
- **Infrastructure: a capped budget of up to ₹500 a month**, separate from the API rule. On the day the cloud account is first used, set an **AWS Budgets** alert and a spending limit. AWS Budgets on its own only alerts; enforcing a limit takes Budget Actions (for example an IAM or SCP deny policy), which Phase 6 sets up and tests.
- **No infrastructure money is spent before Phase 6.**
- This replaces the brief's blanket "Paid hosting" exclusion **for the Phase 6 demo only**. User accounts, a mobile app and anything else in the brief's exclusions stay excluded.

**S8: the Phase 6 demo on AWS (a seam; not designed; nothing is built for it before the Phase 1 exit).** This replaces "static replay hosting (proposed)". The user's intended shape, recorded only so that nothing earlier blocks it:
- the React replay site on S3 + CloudFront;
- the FastAPI backend serving **recorded** runs on AWS Lambda, packaged with Docker;
- the AWS setup as infrastructure as code, Terraform or AWS CDK, chosen in Phase 6.

What Phase 1 must not block: the API's read paths (run history and item detail, D8 F3) work from files alone, with no model; and run directories are immutable once succeeded (D7). **Before anything is published, the architecture session must rule on what a replay may contain**, under §8 (no dataset rows, no sandbox database, no raw run output in the public repository) and A-017/A-028 (the database's licence). Until then, no replay content leaves the machine.

**Note: Phase 4 compute (not a decision).** Renting cloud GPUs for the Phase 4 ablations is deferred; decide after Phase 3, from measured per-call costs. If it is ever used, **every system within one comparison runs on the same hardware**, because matched compute includes wall-clock (brief non-negotiables). It must also fit the infrastructure cap above, or come back to the user as a budget question.

# Follow-ups

Changes this document requires in files the architecture session does not own. FU-1 to FU-5: commit `038f2a8`, merged to main in `458c34b` (PR #2). FU-8 to FU-10: commit `c1515f5`, merged to main in `57f2a74` (PR #3). FU-11 and FU-12: commit `3cdc1a5`, merged to main in `ea4c8ab` (PR #4). FU-13 and FU-14: commit `3083c05`, merged to main in `57bb32d` (PR #6). FU-15: delivered in M2 (`5385ea2`, merged in `8378f2a`, PR #7). FU-6 is scheduled as M6. Each row names its owner: FU-1 to FU-12, FU-21 and FU-22 are the **foundation** session's; FU-13 to FU-16, FU-18, FU-20 and FU-24 are **data-eval**'s; FU-17 and FU-25 are **model**'s; FU-19 and FU-23 are **api**'s. FU-16, FU-18, FU-20 and FU-24: commit `0efdea5`, merged in `802e575` (PR #10). FU-17: commit `e7043f7`, merged in `28b6a01` (PR #11). FU-21 and FU-22: `39c8aeb`, merged in `9df47a8` (PR #12). FU-25: with M4, `4729292`, merged in `af77514` (PR #13). FU-26, FU-27 and FU-29: `f62fe29`, merged in `dba2ac2` (PR #14). FU-30 (v0.11) is **foundation**'s. New in v0.10: FU-26, FU-27 and FU-29 are **model**'s; FU-28 is **data-eval**'s. None of them changes a decision; they make main match this document. Nothing is needed in `pyproject.toml`: M0 already pins `mlflow` for M6. `.github/workflows/ci.yml` changes only through FU-22.

| # | Owner | File | Exact change | Blocks |
|---|---|---|---|---|
| FU-1 | foundation | `scripts/ci/repo_hygiene.py` | Test-split rule: match the **file name**, not the path, and only data extensions (`.csv`, `.jsonl`, `.json`, `.parquet`, `.zip`, `.gz`, `.txt`) — §8.2 as revised. Run-output rule: anchor `runs/`, `mlruns/` at the repository root instead of matching any nested directory. | **M1** (data-eval cannot add `tests/data/test_ref_info_alignment.py` until this lands) |
| FU-2 | foundation | `.gitignore` | Anchor `/runs/` and `/mlruns/` (Q7). The `.claude/` and cache entries already there are confirmed. | nothing; land with FU-1 |
| FU-3 | foundation | `Makefile` | `serve-model`: replace the placeholder error with `set -a; eval "$$(uv run tripartite model serve-env --format sh)"; set +a; exec ollama serve >> runs/ollama-server.log 2>&1`, keeping the `configs/stack.yaml` guard (D4 §configs/stack.yaml). `openapi`: `mkdir -p api-contract` before writing. `test-local`: treat pytest exit code 5 as success and print `no local tests collected` (C). | **M3** (calibration needs the server), and `make test-local` for every session |
| FU-4 | foundation | `src/tripartite/runlog/schema.py` | Add `RunManifest`, `MetricsSeed` and `Metrics` models (D7 §manifest.json, §metrics). Add the validator that `llm_call.query_id`/`.seed` may be null only when `role == "warmup"`. Add `EnvInfo.iogpu_wired_limit_mb` and `.gpu_recommended_max_working_set_bytes` (both nullable). Document the required `run_end.counts` keys. Regenerate `schema.json`. | **M4** |
| FU-5 | foundation | `src/tripartite/runlog/reader.py` | Add `repair_tail(path) -> int` and the `tolerate_partial_tail` keyword (D7 §A crash can leave a half-written last line). | **M4** (resume) |
| FU-6 | foundation | `src/tripartite/runlog/{mlflow_sync.py,cli.py}` | Build them per D7 §MLflow as milestone M6, after M4. Manual sync only; `tripartite log mlflow-sync --run <id>`. | nothing (not an exit criterion) |
| FU-7 | — | — | **Retired.** It appeared only in the intermediate v0.4 committed as `9b2f28f` (add `mlflow` to `pyproject.toml`); M0 already pins `mlflow`. The ID is not reused. | — |
| FU-8 | foundation — **merged** (`c1515f5`, merged to main in `57f2a74`) | `Makefile` | Replace the `serve-model` recipe body (after the `configs/stack.yaml` guard) with exactly: `mkdir -p runs; env_sh="$$(uv run tripartite model serve-env --format sh)" \|\| exit 1; set -a; eval "$$env_sh"; set +a; exec ollama serve >> runs/ollama-server.log 2>&1` (D4 §make serve-model, AQ2–AQ4). The current line on `main` starts an unpinned server if `serve-env` fails. | **M3** (calibration needs a pinned server) |
| FU-9 | foundation — **merged** (`c1515f5`, merged to main in `57f2a74`) | `src/tripartite/runlog/schema.py` (+ regenerated `schema.json`) | `RunManifest`: make `created_at` and `updated_at` non-null, and add a validator that `finished_at` is null iff `status` ∈ {queued, running} (AQ5). `RunEnd.counts`: enforce the seven keys in `RUN_END_COUNT_KEYS`, extra keys still allowed (AQ6). `Metrics.parse.failure_rate`: `Rate \| None`, with a validator that it is null iff `attempted == 0` (AQ7). | **M4** |
| FU-10 | foundation — **merged** (`c1515f5`, merged to main in `57f2a74`); the extra tests of the remaining §8 rules and the self-check are accepted | `tests/scripts/__init__.py`, `tests/scripts/test_repo_hygiene.py` (new) | Tests that build throwaway git repos in `tmp_path` and cover: file-name-only test-split matching with data extensions; case-insensitivity; root anchoring of `runs/` and `mlruns/`; the `.claude/` entries; force-added files. Any key-shaped sample string (`sk-`, `hf_`, `ghp_`, `AKIA`) MUST be assembled at runtime, never written as a literal, or the hygiene check would flag its own test file (AQ8). | nothing; should land before M1 merges, since M1 is the first milestone whose tests rely on the file-name rule |
| FU-11 | foundation — **merged** (`3cdc1a5`, merged to main in `ea4c8ab`) | `scripts/ci/repo_hygiene.py`, `tests/scripts/test_repo_hygiene.py`, `.gitignore` | Hygiene: change the dataset rule to `len(parts) > 1 and parts[0] == "data" and path != "data/MANIFEST.json"`, so only paths under a root `data/` directory match, like the `runs/` rule (FQ1, §8.1); add a test that a root file named `data` passes and `data/x.csv` fails. `.gitignore`: add `__MACOSX/` and `._*` next to `.DS_Store` (D9). | nothing; should land before M1 merges, since M1 creates `data/MANIFEST.json` |
| FU-12 | foundation — **merged** (`3cdc1a5`, merged to main in `ea4c8ab`) | `src/tripartite/runlog/schema.py` (+ regenerated `schema.json`) | In the metrics `parse` model: add validators that `ok <= attempted` and, when `attempted > 0`, `abs(failure_rate - (1 - ok / attempted)) <= 1e-12` (FQ3). Add field `description`s stating the four cross-field rules in D7 §Where the rules live (warm-up nulls, `finished_at` iff terminal, `failure_rate` null iff `attempted == 0`, `ok <= attempted` and the formula) (FQ2). Add no `if`/`then` to `schema.json`. | **M4** (the pipeline writes `metrics.json`) |
| FU-13 | data-eval — **merged** (`3083c05`, merged in `57bb32d`) | `src/tripartite/data/manifest.py` (+ `tests/data/`) | Add `data_dir() -> Path`: returns `Path(os.environ["TRIPARTITE_DATA_DIR"])` if set (absolute and an existing directory, else `DataError` naming the variable), else `REPO_ROOT / "data"`, read at every call. Make `raw_dir()`, `manifest_path()` and `database_zip_path()` use it. Keep `DATA_DIR` only as the default. Tests: set, unset, relative path refused, missing directory refused. | **F1** and **M3** tests (D3 §Planner inputs in other sessions' tests) |
| FU-14 | data-eval — **merged** (`3083c05`, merged in `57bb32d`) | `tests/fixtures/__init__.py`, `tests/fixtures/synthetic_data.py` (new; `tests/data/synthetic.py` re-exports from it or is replaced) | Public helper `write_synthetic_data_dir(root: Path) -> Path` that writes `raw/validation.csv` and `raw/validation_ref_info.jsonl` (M1's synthetic set: 180 rows, canaries in every evaluator-only field) and returns the data root for `TRIPARTITE_DATA_DIR`. A test proves that `load_planner_inputs()` and `load_eval_records()` load it through the environment variable alone. | **F1** and **M3** tests |
| FU-15 | data-eval — **merged** in M2 (`5385ea2`, merged in `8378f2a`) | `src/tripartite/evaluation/records.py` (+ `tests/evaluation/`) | Add `local_constraint_raw: str` (the verbatim CSV cell) to `EvalRecord`, alongside the parsed dict. Add `to_bridge_row(record) -> dict` producing exactly the D5 §Bridge records file object. Test: for all 180 rows (synthetic in CI, real under `local`), every string field of `to_bridge_row` equals the CSV cell byte for byte, and the four integers equal `int(cell)`. | **M2** (the bridge's records file) |
| FU-16 | data-eval — **merged** (`0efdea5`, merged in `802e575`) | `tests/fixtures/synthetic_data.py` (+ `tests/data/test_synthetic_data_dir.py`) | Canaries on every evaluator-only field except `days`, on every row: `date` becomes a list-literal string of `CANARY_DATE_<i>_<k>` values (still one entry per day); `visiting_city_number` = `97_531_000 + i` and `people_number` = `86_420_000 + i`; every row's `local_constraint` carries at least one `CANARY_` string (even rows e.g. `{'house rule': 'CANARY_RULE_even_<i>', 'cuisine': None, 'room type': None, 'transportation': None}`, odd rows as now), so the `None` and non-`None` paths both stay covered. Extend `canaries(i)` with all of them, numbers as strings. Test: for every row, every evaluator-only column except `days` contributes at least one entry to `canaries(i)`, and no canary occurs in `query(i)` or `ref_line(i)`. | **M4** (`test_canary_no_leak`) |
| FU-17 | model — **merged** (`e7043f7`, merged in `28b6a01`) | `src/tripartite/llm/doctor.py` (+ `tests/llm/`) | Add `model_reachable(stack) -> bool` and `model_digest_ok(stack) -> bool` exactly as in D4 §Health checks (`/api/version` and `/api/tags`, 1.0 s total timeout, no generate call, never raise, `true` in fake mode). Tests with a stub HTTP server: reachable, unreachable, timeout, digest match with and without the `sha256:` prefix, tag missing. | **F2** (FU-19); can land in M3 or right after it |
| FU-18 | data-eval — **merged** (`0efdea5`, merged in `802e575`) | `src/tripartite/evaluation/readiness.py` (new; + `tests/evaluation/`) | Add `evaluator_ready() -> bool` exactly as in D8 (stat-only; no hashing, no subprocess; `true` when `TRIPARTITE_EVAL_BRIDGE=fake`). Tests with `TRIPARTITE_DATA_DIR` and a temporary vendor and evalenv layout: all present → true; each missing piece or a wrong size → false; and a test proving no file is opened for reading beyond the manifest. | **F2** (FU-19) |
| FU-19 | api | `src/tripartite/api/app.py` (+ `tests/api/test_health.py`) | Replace the three hard-coded `False` values with calls to `model_reachable`, `model_digest_ok` (loading `configs/stack.yaml` through the model session's loader) and `evaluator_ready`. The route stays a sync `def`, so FastAPI runs it in its thread pool. Tests in fake mode expect all three `true`; with `TRIPARTITE_LLM` **unset** (or `ollama`), a `stack.yaml` whose `runtime.url` points at a closed local port, and no server, the model flags are `false` within 3 s. (Corrected in v0.9, M3.1 AQ1: `llm_mode()` accepts only `fake`, `ollama` or unset, and raises on anything else, so `real` is not a valid value.) | **F2** (lands with or before it); after FU-17 and FU-18 |
| FU-20 | data-eval — **merged** (`0efdea5`, merged in `802e575`) | `src/tripartite/evaluation/aggregate.py` and its importers (`bridge_client.py`, tests) | Rename `Metrics` to `OfficialScores`. No alias is kept; nothing outside data-eval imports it yet. | **M4** (the pipeline imports both it and `runlog.schema.Metrics`) |
| FU-21 | foundation — **merged** (`39c8aeb`, merged in `9df47a8`) | `Makefile` | Target `eval`: `$(TRIPARTITE) run rescore --run $(RUN)` instead of `eval rescore` (D1 Phase 0 exit item 5, D9 Makefile table). | **Phase 0 exit** (M4's `make eval`), not the start of M4 |
| FU-22 | foundation — **merged** (`39c8aeb`, merged in `9df47a8`) | `Makefile`, `.github/workflows/ci.yml` | `setup`: `uv sync --locked` and, still guarded by `evalenv/pyproject.toml`, `uv sync --locked --project evalenv`. CI python job: a guarded step (guard `evalenv/uv.lock`) running `uv lock --check --project evalenv`, next to the existing locked sync. A stale evalenv lock would make R1 depend on whatever versions were resolved that day. | **Phase 0 exit**; nothing earlier |
| FU-23 | api | `src/tripartite/api/routes_queries.py` (+ `tests/api/test_queries.py`, `api-contract/openapi.json`) | Catch `DataError` in both query routes and return 503 with `ErrorDetail {detail}`; declare 503 in `responses`; regenerate the OpenAPI contract. Tests: `TRIPARTITE_DATA_DIR` pointing at an empty directory gives 503 with the loader's message, for both routes. | **W1** (the query picker's error state) |
| FU-24 | data-eval — **merged** (`0efdea5`, merged in `802e575`); the test also pins the values (accepted, v0.9) | `tests/evaluation/` (new test) | Assert that every line of `tests/fixtures/eval_golden/queries.jsonl` has exactly the keys `{query_id, level, days, constrained}`, with `constrained` a sorted subset of `{house rule, cuisine, room type, transportation}` (§8.1 exception). | nothing; land with FU-16 or FU-20 |
| FU-25 | model — **merged** with M4 (`4729292`, merged in `af77514`); doctor also fails on `fits: false` (accepted v0.10) | `src/tripartite/llm/cli.py` (+ `tests/llm/`) | In fake mode (`llm_mode() == "fake"`), `measure-context` and `calibrate` refuse to write to the committed report paths: if `--out` resolves to `CONTEXT_REPORT_PATH` or `CALIBRATION_REPORT_PATH`, exit 1 with `refusing to overwrite <path> in fake mode; pass --out`. Also, independently of mode, `doctor`, `calibrate` and `run start` reject a committed report whose tokenizer is `fake-bytes@v1`, calling it stale. Tests: fake mode with the default `--out` exits 1 and leaves the file byte-identical; fake mode with `--out tmp_path/…` succeeds; a fake-tokenizer report at the real path is reported stale. | **M4 merge** (M4's fake-mode tests must not be able to overwrite the committed reports) |
| FU-26 | model — **merged** (`f62fe29`, merged in `dba2ac2`); Open question 1 approved 2026-09-29 | `configs/stack.yaml` (+ `reports/token_calibration.json`) | Add `LLAMA_ARG_CACHE_RAM: "0"` to `runtime.env`. Then: restart the dedicated server; confirm from `runs/ollama-server.log` that the runner inherited it (startup says the prompt cache is disabled, and no `updating prompt cache` lines appear over several calls); run `make doctor` and `tripartite model calibrate` (expect mode `total`; commit the new report if any field changed); run `make baseline-smoke` once and compare its per-call wall time and swap with the v0.10 smoke run. Make `--resume` also compare the run's recorded `runtime.env` (`run_start.env.ollama_env`) with the current one. Record the result for A-045. | **M5a** (if approved) |
| FU-27 | model — **merged** (`f62fe29`, merged in `dba2ac2`) | `src/tripartite/pipeline/run.py` (`open_run`), `src/tripartite/llm/errors.py` (+ `tests/pipeline/`) | In fake mode, refuse to open a run unless `TRIPARTITE_DATA_DIR` is set to a data root that is not `<repo>/data`, raising `FakeModeRealDataError` that names the variable. The API job runner inherits this through `open_run`. Tests: fake mode with no variable, or with the variable pointing at `<repo>/data`, refuses; fake mode with a synthetic root succeeds. | **F2** (must land before F2 merges) |
| FU-28 | data-eval | `src/tripartite/data/synthetic.py` (new), `src/tripartite/data/cli.py`, `tests/fixtures/synthetic_data.py` | Move the synthetic-set generator into `src/tripartite/data/synthetic.py`; `tests/fixtures/synthetic_data.py` re-exports it unchanged, so the set's bytes are identical. Add `tripartite data synthetic --out DIR`, which writes the set and prints the path to use as `TRIPARTITE_DATA_DIR`. It refuses an `--out` inside `<repo>/data`. | **W2** (the web development loop in fake mode) |
| FU-29 | model — **merged** (`f62fe29`, merged in `dba2ac2`) | `src/tripartite/pipeline/run.py`, `src/tripartite/pipeline/cli.py` (+ `tests/pipeline/`) | `run start` refuses a batch run over all 180 queries when `git_dirty` is true, unless `--allow-dirty` is passed. That flag is recorded in the manifest's `run_start` as `allow_dirty: true`, and `reproduce-check` warns if either run has it. Subset runs (smoke) are unaffected. | **M5a** |
| FU-30 | foundation | `src/tripartite/runlog/schema.py` (+ regenerated `schema.json`, `tests/runlog/`) | Declare `allow_dirty: bool = False` on `RunStart` (D7 §Resume, AQ3). Existing logs without the field still validate. | nothing; land with M6 |

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
10. **Proposed items still open in the brief**: the model ("(proposed)") and static replay hosting ("(proposed)"). The model is D4 (approved 2026-09-22). Hosting is replaced by the user's Phase 6 AWS decision (§9, seam S8; v0.11). The brief's "Paid hosting" exclusion is replaced, for the Phase 6 demo only, by the capped infrastructure budget in §9.
11. **Database download.** The database is a Google Drive link, which cannot reliably be fetched by a script or in CI. D5 makes it a manual step with checksum verification. The brief's Phase 0 "data loading" implies automation.

# Open questions

Still open:
None.

Resolved 2026-09-29 (recorded v0.11):
- Open question 1, the runner prompt cache for M5: **approved** by the user. `LLAMA_ARG_CACHE_RAM: "0"` is in `runtime.env`; built and verified by FU-26 (merged in `dba2ac2`; A-047).

Resolved 2026-09-28:
- The context fit: `measure-context` gives a maximum of 20,214 prompt tokens, so every prompt fits with 8,202 tokens of headroom (A-037). The YaRN / `num_predict` / exclusion question does not arise. The stop-and-ask rule stays in D4 in case the prompt ever changes.
- A-009: confirmed by the user's SQL check of the train split (A-030). D6's condition is met and M4's gate is cleared.

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
