## Summary

<!-- What this PR does, in a few lines. -->

## Session and milestone

- Session: <!-- foundation | data-eval | model | api | web -->
- Milestone: <!-- M0–M5, F1–F3, W1–W5 (ARCHITECTURE.md D9 build order) -->
- ARCHITECTURE.md version built against: <!-- first line of ARCHITECTURE.md -->

## Checklist

- [ ] Every path this PR touches belongs to my session (D9 tree). Any exception is listed under Architecture questions.
- [ ] CI is green: ruff check, ruff format --check, mypy src, lint-imports, repo hygiene, `pytest -m "not local"`, and every guarded step that now applies.
- [ ] `make lint` and `make test` pass locally.
- [ ] Nothing from §8 is committed: no dataset files, test-split artefacts, sandbox database, `runs/` or `mlruns/` output, `.env` files or keys. `uv run python scripts/ci/repo_hygiene.py` passes.
- [ ] Assumptions: new ones are appended to `assumptions.md` by the architecture session only; any I relied on are cited here as A-xxx.

## Local gate (D1)

Required when this PR touches `src/tripartite/{llm,planner,parse,pipeline,evaluation}`, `evalenv/`, `vendor/` or `configs/`.

- [ ] Not applicable: this PR touches none of those paths.
- [ ] Output of `make test-local` pasted below.
- [ ] Smoke-run `metrics.json` pasted below.

<details><summary><code>make test-local</code> output</summary>

```text

```

</details>

<details><summary>Smoke-run <code>metrics.json</code></summary>

```json

```

</details>

## Deviations from ARCHITECTURE.md

<!-- Every SHOULD you broke, with its reason. "None" if none. -->

## Architecture questions

<!-- Anything ambiguous, wrong or missing that you did not implement (§0),
     and any change you need in another session's paths. "None" if none. -->
