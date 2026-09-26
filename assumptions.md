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
