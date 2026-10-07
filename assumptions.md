# assumptions.md

Append-only. Never edit or delete an entry. To change one, add a new entry that names the old ID (e.g. "Supersedes A-003"). Status: open / confirmed / retired.

---

### A-001
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: With a pinned Ollama version, model digest and options, `OLLAMA_NUM_PARALLEL=1` and the same `seed`, regenerating the same prompt on the same Mac usually yields byte-identical output. It is not guaranteed across prompt-cache states or server restarts.
- Why needed: Sets expectations for R3 in D1. Plan identity is reported as a diagnostic only, because no determinism guarantee is documented.
- How to check: In Phase 0, run `make baseline-smoke` twice with a server restart in between, then `make reproduce-check` to read the identical-output fraction.
- Status: open

### A-002
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The tokenizer inside Ollama's `qwen3:8b-q4_K_M` GGUF produces the same token count as HF `Qwen/Qwen3-8B` `tokenizer.json` at the pinned revision for the raw rendered prompt.
- Why needed: Local counts are the canonical input-token numbers (D7, S4) and the basis of the truncation post-check (D4).
- How to check: For uncached calls (the first call per query in seed 0 of the smoke run), `prompt_eval_count` must equal the local `prompt_tokens`. Any mismatch fails `make test-local`.
- Status: open

### A-003
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: In the pinned Ollama version, `prompt_eval_count` either counts the full prompt or counts only uncached tokens while `prompt_eval_cached_count` reports the cached remainder, so `prompt_eval_count + (prompt_eval_cached_count or 0)` equals the full prompt length when nothing is truncated.
- Why needed: The post-call truncation check in D4 relies on it. If it fails, only the pre-flight check and the server-log scan remain.
- How to check: In Phase 0, call the same prompt twice (the second call is cache-warm) and compare the reported fields with the local count.
- Status: open

### A-004
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The pinned Ollama version still truncates over-length prompts silently (warning only in the server log) instead of returning an error. ollama/ollama issue #8099 (Dec 2024) confirms this for an older version. Current docs do not describe the behaviour.
- Why needed: This is why D4 makes truncation a hard error in our code rather than trusting the runtime.
- How to check: In Phase 0, send a prompt longer than `num_ctx` on purpose to the pinned server and observe the HTTP response and `runs/ollama-server.log`.
- Status: open

### A-005
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: By default on a 24 GB M4 Pro, macOS lets Metal use about 2/3 of unified memory (≈16 GB). The coordinating chat's figure was ≈17 GB. The ~2/3 figure comes from the llama.cpp heuristic for machines with 32 GB or less (discussion ggml-org/llama.cpp#2182). It has not been measured on this machine.
- Why needed: Sets the memory ceiling for the D4 model, quantization and context choice.
- How to check: Read `recommendedMaxWorkingSetSize` from the ggml Metal init lines in `runs/ollama-server.log`, and record `sysctl iogpu.wired_limit_mb` (0 = default) in the run manifest.
- Status: open

### A-006
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The longest validation reference info (51,628 characters) is about 15–20k Qwen3 tokens (≈2.6–3.5 characters per token for this JSON). With about 0.8k of instruction and 4,096 output tokens, every query then fits in `num_ctx` ≤ 32768.
- Why needed: The provisional `num_ctx` and the memory budget in D4.
- How to check: `make measure-context` → `reports/context_report.json`.
- Status: open

### A-007
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: Line i of `validation_ref_info.jsonl` at HF revision 8736504e belongs to row i of `validation.csv` at the same revision, and the file is byte-identical to `database/validation_ref_info.jsonl` in the GitHub repo at e52c87f4.
- Why needed: `PlannerInput` pairs a query with its reference info by position (D3). A misalignment would give the planner the wrong evidence.
- How to check: A data-eval test checks, for all 180 rows, that the ref-info keys mention the row's `dest` city or its state's cities. The check runs on the evaluator side, and the test never passes these fields to the planner. Also compare the sha256 against the GitHub copy.
- Status: open

### A-008
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The vendored evaluator runs unmodified under Python 3.12 with pandas 2.2.x, current numpy and datasets, and an installed gradio. Its results do not depend on library versions within those pins.
- Why needed: D5 isolates the evaluator in `evalenv/` with pinned versions. pandas 3.x has copy-on-write and string-dtype changes, so it is excluded.
- How to check: The bridge runs `postprocess/example_evaluation.jsonl` without errors, and a second run gives byte-identical output (golden fixture).
- Status: open

### A-009
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The in-context example inside the official `PLANNER_INSTRUCTION` (Ithaca→Charlotte, flight F3633413) was written by the benchmark authors as part of the prompt and is not copied from an `annotated_plan` in the train or validation data.
- Why needed: The brief's non-negotiable forbids showing agents annotated or reference plans. D6 uses the official prompt verbatim.
- How to check: A human searches train `annotated_plan` on the HF dataset viewer for `F3633413`, "Nagaland's Kitchen" and "Bushwick". Code sessions must not download train.csv for this. The check could not be done from here because Hugging Face downloads were blocked by network policy.
- Status: open

### A-010
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: On the M4 Pro, Qwen3-8B Q4_K_M takes about 40–60 s per call (≈10k prefill tokens plus ≈1k generated tokens), so a full 540-call baseline takes about 6–9 h.
- Why needed: Planning. It explains why runs must be resumable, locked and CLI-only.
- How to check: Latency statistics from the smoke run's `metrics.json`.
- Status: open

### A-011
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: Resident memory for D4 is about 11 GB: 5.2 GB weights, 4.8 GB f16 KV cache at 32,768 tokens (147,456 B/token = 2×36×8×128×2), and about 1 GB compute buffers. That leaves at least 10 GB for macOS, dev tools and the Claude apps without swapping.
- Why needed: Choosing Q4_K_M and f16 KV over q8_0 (D4).
- How to check: `ollama ps` and Activity Monitor (memory pressure, swap) during the smoke run with the usual apps open.
- Status: open

### A-012
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: With the official prompt, Qwen3-8B non-thinking follows the `Day N:` / `Field: value` format closely enough that the rule parser (D2) parses at least 95% of non-empty outputs.
- Why needed: D2 rejects an LLM parser for Phase 1. If this fails, delivery rate would measure our parser rather than the model.
- How to check: The parse failure rate among non-empty outputs in the smoke run. If it is above 5%, the model session raises an architecture question and must not add an LLM parser itself.
- Status: open

### A-013
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: The sandbox database zip at the Google Drive link in the upstream README is stable. Its sha256 at first download, trusted on first use, serves as the database pin.
- Why needed: R1 re-scoring and the future record-ID seam (S3) need a fixed database snapshot. There is no official checksum.
- How to check: Re-download before the Phase 1 exit and compare the sha256. A mismatch blocks the exit and raises an architecture question.
- Status: open

### A-014
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: Every commonsense and hard check returns a tuple `(value, message)` with `value ∈ {True, False, None}`, where None means not applicable. This was confirmed by reading `valid_cost` (message None) and eval.py's use of `[0]`. The other checks are assumed to follow the same pattern.
- Why needed: The constraint status mapping (pass/fail/not_applicable/not_evaluated) in D5.
- How to check: A bridge test on the example submission asserts that the shape holds for every key in all 180 results.
- Status: open

### A-015
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: Rendering the pinned HF Qwen3 chat template (jinja2) with `enable_thinking=False` and `add_generation_prompt=True`, then sending it with `raw: true`, disables thinking the same way Ollama's own template does with `think: false`.
- Why needed: D4 uses raw mode so the local token count covers exactly the bytes the runtime sees.
- How to check: On 9 smoke prompts, no output contains a non-empty `<think>` block. Optionally compare with a `think:false` templated call.
- Status: open

### A-016
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: Across full reruns, the 3-seed mean of each official metric varies by less than 2.0 percentage points under D4 sampling (T=0.7), so the R3 tolerance can be met without greedy decoding.
- Why needed: The Phase 1 exit criterion R3 (D1).
- How to check: The seed-to-seed SD from the first full run. If the SD of any metric is above about 2 pp, raise an architecture question before the second run.
- Status: open

### A-017
- Date: 2026-09-22 · Architecture: v0.1
- Assumption: CC BY 4.0 (with attribution in NOTICE) covers committing small evaluator-output fixtures that contain database entity names (tests/fixtures/eval_golden/), and the upstream MIT licence covers vendoring the evaluator code.
- Why needed: D5 golden tests and vendoring.
- How to check: Read the licence statements in the upstream repo and the HF dataset card. Confirm that the Drive database carries the same licence.
- Status: open

### A-018
- Date: 2026-09-22 · Architecture: v0.2
- Supersedes: A-002. Same assumption, new check. The A-002 check ("the first call per query in seed 0 is uncached") is wrong: every planner prompt shares the official instruction prefix, so that call can hit the prompt cache.
- Assumption: The tokenizer inside Ollama's `qwen3:8b-q4_K_M` GGUF produces the same token count as HF `Qwen/Qwen3-8B` `tokenizer.json` at the pinned revision for the raw rendered prompt.
- Why needed: Local counts are the canonical input-token numbers (D7, S4) and the basis of the post-check (D4).
- How to check: ARCHITECTURE v0.2 D4 §Token calibration, step 2. On 9 cold probes (`val-001`…`val-009`), each sent right after unloading the model with `keep_alive: 0` and confirmed cold by `load_duration > 0`, `prompt_eval_count` must equal the local `prompt_tokens` exactly. Re-run by `test_tokenizer_agreement` in `make test-local`.
- Status: open

### A-019
- Date: 2026-09-22 · Architecture: v0.2
- Supersedes: A-003. Its check (compare a warm re-send with the local count) could not tell apart the two cases that matter.
- Assumption: The pinned Ollama version's prompt-token reporting fits exactly one of three modes. `total`: `prompt_eval_count` counts the whole prompt. `split`: `prompt_eval_count + prompt_eval_cached_count` equals the whole prompt. `uncached_only`: `prompt_eval_count` counts only uncached tokens, there is no usable cached field, and the count lies between `prompt_tokens - lcp` and `prompt_tokens`.
- Why needed: The per-call truncation post-check (D4) depends on the mode. If no mode fits, the calibration fails and an architecture question is raised.
- How to check: D4 §Token calibration, step 3. Two warm probes (an identical re-send, and a prompt sharing only the instruction prefix) classify the mode. The result is written to `reports/token_calibration.json`.
- Status: open

### A-020
- Date: 2026-09-22 · Architecture: v0.2
- Assumption: With `OLLAMA_NUM_PARALLEL=1`, Ollama's prompt cache can reuse at most the common token prefix between the current prompt and the prompt sent immediately before it. It keeps no older entries that could supply a longer match.
- Why needed: The `uncached_only` post-check lower bound (`prompt_tokens - lcp`) is correct only if this holds. If the cache kept older prompts, a legitimate call could look truncated.
- How to check: During calibration in `uncached_only` mode, add a probe sequence A, B, A (where B shares only the instruction prefix). The second A must report `prompt_eval_count >= prompt_tokens - lcp(B, A)`. If it reports fewer, the cache keeps older entries and this assumption fails.
- Status: open

### A-021
- Date: 2026-09-22 · Architecture: v0.2
- Assumption: `POST /api/generate {"model": <tag>, "keep_alive": 0}` unloads the model, and the next request loads it fresh with an empty KV and prompt cache. `/api/ps` no longer lists the model, and the next response reports `load_duration > 0`.
- Why needed: The cold probes in D4 calibration are uncached by construction only if unloading clears the cache.
- How to check: During calibration, every cold probe must show the model absent from `/api/ps` before the call and `load_duration > 0` in the response. Otherwise the calibration fails. The fallback (an architecture question, not a Code-session choice) is to restart the dedicated server before each cold probe.
- Status: open

### A-022
- Date: 2026-09-23 · Architecture: v0.4
- Assumption: A dedicated `ollama serve` started with the `runtime.env` block of `configs/stack.yaml` honours those variables, and the running server exposes enough through its HTTP API (`/api/ps`, `/api/show`, `/api/version`) for `tripartite model doctor` to confirm the effective context length and the loaded model's digest, rather than trusting the env it exported.
- Why needed: D4 §configs/stack.yaml makes doctor the gate that stops a run from using a server whose settings differ from the pins, which is what keeps the calibration (A-018, A-019) valid.
- How to check: In Phase 0, start the server through `make serve-model`, then compare doctor's reported context length and digest with the values in `configs/stack.yaml`, and with the ggml init lines in `runs/ollama-server.log`. If the API does not expose the effective context length, doctor falls back to reading the server log and this assumption is retired by a new entry.
- Status: open

### A-023
- Date: 2026-09-23 · Architecture: v0.4
- Assumption: Because the run-log writer appends whole lines and fsyncs each one, a crash or a power loss can corrupt only the final line of `events.jsonl`, never an earlier one.
- Why needed: D7's resume repair (Q10) truncates a bad final line and treats a bad line anywhere else as a hard error. If an earlier line could be corrupted, resume would silently skip completed work or misread it.
- How to check: A foundation test kills a writer mid-line (or truncates a sample log at a random offset) and asserts that `repair_tail` restores a readable log whose event count equals the number of complete lines. Any real occurrence of a corrupt earlier line raises an architecture question.
- Status: open

### A-024
- Date: 2026-09-26 · Architecture: v0.7
- Confirms: A-007. Status of A-007 is now confirmed by this entry; A-007 itself is unchanged.
- Assumption: Line i of `validation_ref_info.jsonl` belongs to row i of `validation.csv` at HF revision 8736504e, and the reference-info file is byte-identical to `database/validation_ref_info.jsonl` in the GitHub repo at e52c87f4.
- Why needed: `PlannerInput` pairs a query with its reference info by position (D3).
- How it was checked (M1, merged in 7d5303f): (1) Identity by git blob id rather than sha256, because GitHub exposes no sha256 for a plain blob: the blob ids of both downloaded files equal the HF oids at 8736504e (`validation.csv` e4bc90de…, `validation_ref_info.jsonl` e1be7115…), and the ref-info blob id also equals GitHub@e52c87f4's. A git blob id is a SHA-1 over the exact content, so equal ids mean byte-identical files; the files' sha256 are pinned separately in `data/MANIFEST.json`. (2) Alignment: `tests/data/test_ref_info_alignment.py` reads `citySet_with_states.txt` in memory from the zip verified against the D5 pin, and passes for 180/180 rows; with the lines shifted by one, 162/180 rows fail, so the test discriminates.
- Status: confirmed

### A-025
- Date: 2026-09-26 · Architecture: v0.7
- Assumption: `datasets.load_dataset('osunlp/TravelPlanner', 'validation')` at revision 8736504e returns `days`, `visiting_city_number`, `people_number` and `budget` as Python `int`, and every other column (`org`, `dest`, `date`, `local_constraint`, `query`, `level`, `reference_information`) as the verbatim `str` from the CSV.
- Why needed: D5 §Bridge records file serializes each row to match what `eval.py` would receive from `load_dataset`. The four integers are implied by the evaluator's own use (`days` as a key of `{3, 5, 7}`, arithmetic and comparisons on the others), and `eval.py` converts `local_constraint` only when it is a string. The dtypes were not re-read from the dataset's feature metadata this session (the lookup hit a rate limit).
- How to check: Read the `features` of the validation config from `https://datasets-server.huggingface.co/info?dataset=osunlp/TravelPlanner` (expect `int64` for the four, `string` for the rest). The data-eval session records the result as a new entry that names A-025 before M2's golden fixtures are generated.
- Status: open

### A-026
- Date: 2026-09-26 · Architecture: v0.7
- Supersedes: A-025, as confirmed. A-025 itself is unchanged.
- Assumption: `datasets.load_dataset('osunlp/TravelPlanner', 'validation')` at revision `8736504ecfc31b7f8b7e40122873c337e83fff7c` returns `days`, `visiting_city_number`, `people_number` and `budget` as integers (feature dtype `int64`, a Python `int` per row), and `org`, `dest`, `date`, `local_constraint`, `query`, `level` and `reference_information` as strings (dtype `string`).
- Why needed: D5 §Bridge records file serializes each row exactly as `load_dataset` would return it, so that `eval.py` and the constraint modules see the same types as upstream. Several checks compare or multiply the integers, and would fail silently rather than crash if given strings.
- How it was checked: The features of the validation config were read from `https://datasets-server.huggingface.co/info?dataset=osunlp/TravelPlanner&config=validation` on 2026-09-26. The response names revision `8736504ecfc31b7f8b7e40122873c337e83fff7c` and 180 examples, and lists exactly those eleven features with those dtypes (all `_type: Value`). The source at `e52c87f4` agrees: `eval.py` converts only `local_constraint` from a string (lines 74–75), and nothing in the evaluator reads `date`, `query` or `reference_information`. FU-15's test that `to_bridge_row` reproduces every CSV cell, and the four integers as `int(cell)`, guards the serialization side.
- Status: confirmed

### A-027
- Date: 2026-09-28 · Architecture: v0.8
- Confirms: A-014. A-014 itself is unchanged.
- Assumption: Every commonsense and hard check of the evaluator at `e52c87f4` returns a pair `(value, message)` with `value ∈ {True, False, None}`, where None means not applicable.
- Why needed: The constraint status mapping in D5 (`pass`, `fail`, `not_applicable`, `not_evaluated`).
- How it was checked: M2 (`5385ea2`, merged in `8378f2a`) ran the real bridge over all 180 plans of the vendored `postprocess/example_evaluation.jsonl` and committed the results as `tests/fixtures/eval_golden/per_plan.jsonl`. Every key in all 180 per-plan results, commonsense and hard, is a `[value, message]` pair with a value of `true`, `false` or `null`.
- Status: confirmed

### A-028
- Date: 2026-09-28 · Architecture: v0.8
- Supersedes: A-017, narrowing it. A-017 itself is unchanged.
- Assumption: (a) The vendored code is MIT, from the upstream `LICENSE` at `e52c87f4`; confirmed. (b) The HF dataset `osunlp/TravelPlanner` is CC BY 4.0, from its dataset card; confirmed. (c) Still open: the sandbox database downloaded from Google Drive has no licence statement of its own. The upstream README only says that extending its database is permitted "provided that you adhere to the licensing terms". We treat it as covered by the dataset's CC BY 4.0, since the same authors publish it as part of the same benchmark, and we keep what we commit from it minimal: entity names inside evaluator messages in `tests/fixtures/eval_golden/per_plan.jsonl`, attributed in `NOTICE`. The file never commits database rows (§8.3).
- Why needed: The M2 golden fixtures are committed to a public repository. (a) and (b) cover the vendored code, upstream's own sample submission and the `queries.jsonl` exception in §8.1; (c) covers the entity names in the per-plan messages.
- How to check: Look for a licence file or statement in the Google Drive folder that hosts the database, or ask the upstream authors (an issue on OSU-NLP-Group/TravelPlanner). If they state a licence other than CC BY 4.0, or forbid redistribution, drop the messages from `per_plan.jsonl` (the golden test needs only the values) and record that in a new entry.
- Status: open

### A-029
- Date: 2026-09-28 · Architecture: v0.8
- Assumption: The pinned Ollama version serves `GET /api/version` (returning a `version` field) and `GET /api/tags` (listing every installed model with `name`/`model` and `digest`) without loading any model, and each normally answers within 1 s on the M4 Pro. The digest in `/api/tags` equals the full sha256 pinned in `configs/stack.yaml`, possibly without the `sha256:` prefix.
- Why needed: D4 §Health checks: `model_reachable` and `model_digest_ok` must be cheap, must never trigger a load, and must not report false while the model is merely unloaded.
- How to check: In M3 or FU-17, against the dedicated server: call both endpoints with no model loaded (`/api/ps` empty), confirm `/api/ps` is still empty afterwards, time them, and compare the `/api/tags` digest with `stack.yaml`. Record the result as a new entry that names A-029.
- Status: open

### A-030
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-009. A-009 itself is unchanged.
- Assumption: The in-context example in the official `PLANNER_INSTRUCTION` (Ithaca→Charlotte, flight F3633413, "Nagaland's Kitchen") is not copied from an `annotated_plan` in the train split. The validation split has no `annotated_plan` column (F7).
- Why needed: The brief's non-negotiable forbids showing agents annotated or reference plans; D6 uses the official prompt verbatim; M4 was gated on this.
- How it was checked: On 2026-09-28 the user ran, in the Hugging Face SQL console for `osunlp/TravelPlanner`, on the train split: `SELECT count(*) FILTER (WHERE annotated_plan ILIKE '%F3633413%'), count(*) FILTER (WHERE annotated_plan ILIKE '%Nagaland%'), count(*) FROM train;`. The result was 0, 0 and 45: no train plan contains the flight number or the restaurant, across all 45 rows. The viewer serves the dataset's current revision. On 2026-09-28 the Hugging Face API still reported that revision as `8736504ecfc31b7f8b7e40122873c337e83fff7c`, last modified 2024-07-14, the revision pinned in F7 and §6, so the check applies to the pinned data.
- Status: confirmed

### A-031
- Date: 2026-09-28 · Architecture: v0.9
- Supersedes: A-005. A-005 itself is unchanged.
- Assumption: On the user's 24 GB M4 Pro, with the macOS default `iogpu.wired_limit_mb = 0`, the GPU (Metal) budget is **17.8 GiB**, not the ~16 GB of the llama.cpp 2/3 heuristic.
- Why needed: The memory ceiling for D4's model, quantization and context choice, and for any later multi-agent phase (Brief issue 4).
- How it was checked: M3 (`88d9555`, merged in `2c2367c`). Ollama 0.33.2 does not log `recommendedMaxWorkingSetSize`. Its server log shows Metal `total="17.8 GiB"` and `18185 MiB free`, and `sysctl iogpu.wired_limit_mb` returned 0.
- Status: confirmed

### A-032
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-018. A-018 itself is unchanged.
- Assumption: Ollama's `qwen3:8b-q4_K_M` tokenizer gives exactly the same token count as HF `Qwen/Qwen3-8B` at the pinned revision for the raw rendered prompt.
- Why needed: Local counts are canonical (D7, S4), and the post-check compares them with the runtime's.
- How it was checked: M3 calibration: on all 9 cold probes (`val-001`…`val-009`, each after an unload), `prompt_eval_count` equalled the local `prompt_tokens` exactly.
- Status: confirmed

### A-033
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-019. A-019 itself is unchanged.
- Assumption: The pinned Ollama version's prompt-token reporting fits exactly one of the three calibration modes. It fits mode `total`: `prompt_eval_count` counts the whole prompt even when part of it is cached.
- Why needed: The D4 post-check. Under `total`, it is plain equality, `prompt_eval_count == prompt_tokens`.
- How it was checked: M3 calibration classified the runtime as `total` from the warm probes (an identical re-send, and a prompt sharing only the instruction prefix). The result is committed in `reports/token_calibration.json`.
- Status: confirmed

### A-034
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-021. A-021 itself is unchanged.
- Assumption: `POST /api/generate {"model": <tag>, "keep_alive": 0}` unloads the model, and the next request loads it fresh with an empty cache.
- Why needed: The cold calibration probes are uncached by construction only if an unload clears the cache.
- How it was checked: M3 calibration: before each of the 9 cold probes the model was absent from `/api/ps`, and each response reported a fresh load (`load_duration` 2.0–2.6 s) with the full prompt evaluated.
- Status: confirmed

### A-035
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-022. A-022 itself is unchanged.
- Assumption: A dedicated `ollama serve` started from `configs/stack.yaml`'s `runtime.env` honours those variables, and its HTTP API exposes enough for `doctor` to confirm the effective context length and the loaded model's digest.
- Why needed: `doctor` is the gate that stops runs on a server whose settings differ from the pins, which keeps the calibration valid.
- How it was checked: M3: with the server started by `make serve-model`, `/api/ps` showed `context_length` 32768 for the loaded model, matching `model.num_ctx`, and the digest matched `configs/stack.yaml`.
- Status: confirmed

### A-036
- Date: 2026-09-28 · Architecture: v0.9
- Supersedes: A-020. A-020 itself is unchanged.
- Assumption: None needed. A-020 (the prompt cache reuses at most the prefix shared with the previous prompt) supported only the lower bound of the post-check in mode `uncached_only`. Calibration found mode `total` (A-033), where the post-check is plain equality and uses no `lcp` bound.
- Why needed: To record that the D4 post-check no longer depends on A-020.
- How to check: If a future Ollama version or re-calibration reports mode `uncached_only`, A-020 becomes relevant again and must be re-tested by the calibration's A, B, A probe (D4 §Token calibration, step 3 (iii)).
- Status: retired

### A-037
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-006, with a correction. A-006 itself is unchanged.
- Assumption: Every validation prompt fits in `num_ctx` 32768 together with `num_predict` 4096 and the 256-token margin.
- Why needed: `num_ctx` is a fixed pin (D4), and truncation is a hard error.
- How it was checked: M3's `make measure-context` (`reports/context_report.json`): `prompt_tokens` min 4,885, median 10,808, p95 17,768, max 20,214. The maximum is slightly above A-006's predicted 15–20k for the reference information alone, because it counts the whole rendered prompt. `fits = true`, with headroom 8,202 of 28,416.
- Status: confirmed

### A-038
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-011 (the resident size; below the estimate). A-011 itself is unchanged.
- Assumption: With D4's settings the model's resident memory stays well within the GPU budget, leaving room for macOS, dev tools and the Claude apps.
- Why needed: The choice of Q4_K_M with an f16 KV cache at 32k (D4).
- How it was checked: M3: loaded model 9.91 GB (9.23 GiB, all in VRAM); runner peak 9.58 GiB during calibration; KV cache logged at 4,608 MiB, exactly D4's arithmetic (147,456 B/token × 32,768). This is below A-011's ~11 GB estimate and inside the 17.8 GiB budget (A-031). Memory pressure and swap over a long run with the usual apps open were not measured; M4's smoke run records them together with A-010.
- Status: confirmed

### A-039
- Date: 2026-09-28 · Architecture: v0.9
- Confirms: A-029. A-029 itself is unchanged.
- Assumption: The pinned Ollama version serves `GET /api/version` and `GET /api/tags` quickly without loading any model, and `/api/tags` reports the pinned digest.
- Why needed: D4 §Health checks: `model_reachable` and `model_digest_ok` must be cheap, must never load the model, and must not report false while the model is merely unloaded.
- How it was checked: The model follow-ups after M3 (`e7043f7`, merged in `28b6a01`): with the model loaded or not, both checks returned true in 3–29 ms; with no server, false in 3–25 ms. `/api/ps` was empty before and after 20 calls, and the server log shows only `/api/version` and `/api/tags` requests.
- Status: confirmed

### A-040
- Date: 2026-09-29 · Architecture: v0.10
- Confirms: A-010, with measured values. A-010 itself is unchanged.
- Assumption: A full 540-call baseline on the M4 Pro takes about 8.1–8.4 h, inside A-010's 6–9 h.
- Why needed: Planning M5a: two full runs, each needing an uninterrupted, awake machine.
- How it was checked: M4's smoke run `20260929T041153Z-batch-9b45ed9e-f6c1` (27 calls): wall 54.3 s mean, 52.2 s median (9.6–97.2 s); prefill 301 tok/s; generation 31.5 tok/s with 517 output tokens on average; load about 7 ms per call. 540 × 54.3 s = 8.14 h. Scaling the measured rates to all 180 prompts in `context_report.json`, whose mean of 11,280 tokens is above the smoke set's 10,867, gives 8.35 h. If the runner cache is disabled (Open question 1, A-044), expect about 6% less.
- Status: confirmed

### A-041
- Date: 2026-09-29 · Architecture: v0.10
- Confirms: A-012 on the smoke set. A-012 itself is unchanged.
- Assumption: The rule parser parses at least 95% of non-empty Qwen3-8B outputs produced with the official prompt.
- Why needed: D2 rejects an LLM parser; delivery rate must measure the model, not the parser.
- How it was checked: M4's smoke run: 27 of 27 non-empty outputs parsed (0% failure), each with the right number of days. Six plans got `missing_field:accommodation` on their last day, where the model omitted the line; the parser fills `-`, which is what the official format expects after returning home. M5a's full runs re-check this on 540 outputs (`metrics.json` → `parse`).
- Status: confirmed

### A-042
- Date: 2026-09-29 · Architecture: v0.10
- Refines: A-020 and A-036. Both are unchanged.
- Assumption: A-020's premise is **false** for Ollama 0.33.2 with its default runner settings. `llama-server`'s host-RAM prompt cache keeps several earlier prompts (up to 8,192 MiB, evicting the oldest), not just the previous one. It also survives across client processes and warm-ups for as long as the server runs.
- Why needed: A-036 retired A-020 because calibration found mode `total`. This entry records that A-020 would also have been wrong: if a future runtime ever calibrated as `uncached_only`, the `lcp` lower bound would be unsafe unless the runner cache were disabled (`LLAMA_ARG_CACHE_RAM=0`).
- How it was checked: `runs/ollama-server.log` in the M4 worktree: "cache state: 5 prompts, 6970.931 MiB (limits: 8192.000 MiB, 32768 tokens …)" and "removing oldest entry". M4 AQ12: the smoke run's first call restored `val-001` from `make test-local` about 2.5 h earlier, across the warm-up.
- Status: confirmed

### A-043
- Date: 2026-09-29 · Architecture: v0.10
- Supersedes: A-011's claim that D4 leaves enough memory "without swapping". A-011 and A-038 are unchanged; A-038's resident-size figures still hold.
- Assumption: Under the user's normal app load the Mac swaps while a run is going; the model's own footprint is flat. Two causes add up: the other apps, and the runner's host prompt cache (up to 8 GiB, outside Ollama's accounting; A-042). With other apps closed, the server restarted, and possibly the cache disabled, a full run should see little or no swap growth.
- Why needed: An 8-hour run under heavy swap can slow down and exaggerate wall-clock latencies (the brief's matched budgets use wall-clock). M5a's operations and Open question 1 depend on it.
- How to check: M5a records swap used before and after each full run (D9 §M5 operations), with the apps and cache setting noted. M4's smoke run: the model stayed at 9.91 GB, all in VRAM, in all 50 `/api/ps` samples; swap was 7.4–8.0 GB before the run and moved between 10 and 18.8 GB during it (13.3 GB at the end), with free memory around 16–30%; Activity Monitor showed `llama-server` at 17.32 GB against 9.91 GB in `/api/ps`.
- Status: open

### A-044
- Date: 2026-09-29 · Architecture: v0.10
- Assumption: The runner's prompt-cache save (2.7–3.6 s per call in the log) runs when the next request arrives and before its prompt is processed. It is therefore inside that call's client wall time (`timing_ms.wall_client`) and Ollama's `total_duration`, but not inside `prompt_eval_duration` (prefill) or `eval_duration` (generation).
- Why needed: D7's latency fields and the brief's wall-clock budgets. It says which recorded latencies include cache bookkeeping.
- How to check: For each call of a run with the cache on, compare `wall_client − (load + prefill + generation)` with the nearest preceding "prompt cache update took … ms" line in the server log. The smoke run's means are consistent with it (wall 54.3 s against prefill plus generation 52.6 s). With the cache disabled (FU-26), the gap should shrink to transport overhead.
- Status: open

### A-045
- Date: 2026-09-29 · Architecture: v0.10
- Assumption: Ollama 0.33.2 passes its own environment through to `llama-server`, and llama.cpp honours `LLAMA_ARG_CACHE_RAM` when no `--cache-ram` flag is given. So `LLAMA_ARG_CACHE_RAM=0` in `configs/stack.yaml`'s `runtime.env` disables the host prompt cache without changing the Ollama version pin.
- Why needed: Open question 1 and FU-26.
- How to check: FU-26. After restarting the dedicated server with the variable set, the runner's startup log reports the prompt cache as disabled (or no `updating prompt cache` / `cache state` lines appear over several calls), and `llama-server`'s memory in Activity Monitor stays near the `/api/ps` size. Sources that suggest it works: ollama/ollama#18264 (reported on 0.31.2: "Ollama passes its environment through to llama-server"), ollama/ollama#17351, and the llama.cpp server README (`-cram, --cache-ram N`, env `LLAMA_ARG_CACHE_RAM`, 0 disables). Older llama.cpp builds logged "prompt cache is enabled" even with 0 (llama.cpp#22127), so judge by behaviour, not only that line.
- Status: open

### A-046
- Date: 2026-09-29 · Architecture: v0.10
- Refines: A-001. A-001 itself is unchanged.
- Assumption: Seeded regeneration usually reproduces raw output byte for byte only when the server state at each call is the same too, and that state includes the runner's host prompt cache (A-042). In seed-major order no call of a run can hit that cache except the run's first call and the first call after a resume. Those calls may restore a cached state left by an earlier process instead of computing the prompt, which is a different computation path. Restarting the dedicated server before each full run (D9 §M5 operations) removes that difference.
- Why needed: R3's plan-identity diagnostic (D1) and the M5a procedure.
- How to check: M5a's `reproduce_check.json` identity rate. With the server restarted before both runs, a non-identical first pair would point to nondeterminism other than the cache.
- Status: open
