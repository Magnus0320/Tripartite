# Vendored: TravelPlanner evaluator

Everything in this directory except `VENDOR.md` and `VENDOR.lock` was copied **unmodified**
from the upstream repository (ARCHITECTURE.md D5):

- Upstream: <https://github.com/OSU-NLP-Group/TravelPlanner>
- Commit: `e52c87f4ac348a3410c46dc3553c519db5ec5e23` (the §6 pin)
- Vendored on 2026-09-26 by the data-eval session (milestone M2)

`VENDOR.lock` lists every vendored file with its size, sha256 and git blob id. The blob id is
the one upstream's git tree records at that commit, so a copy can be compared with GitHub's
tree API without downloading anything. `scripts/vendor_check.py` checks that every git-tracked
file here matches the lock, and CI runs it (D1, D9 §Shared files, item 4).

## What is vendored

These are D5's paths, kept in their upstream layout:

- `evaluation/`: all 3 files (`eval.py`, `commonsense_constraint.py`, `hard_constraint.py`)
- `tools/`: the whole directory, including subpackages, except one compiled file (below)
- `utils/`
- `agents/prompts.py`
- `postprocess/example_evaluation.jsonl`: a 180-line validation submission, 161 lines delivered (F6)
- `database/README.md`
- `LICENSE`, `README.md`

That is 27 files.

## What is not vendored

- **`database/*_ref_info.jsonl`**, including `test_ref_info.jsonl`: never downloaded, not
  even into the scratch clone (below). The test split stays off the machine (D3).
- **`images/`, `finetuning_data/`, and every other upstream path** not listed above.
- **`tools/restaurants/__pycache__/__init__.cpython-39.pyc`**, a compiled file that upstream
  tracks. This repository's `.gitignore` ignores `__pycache__/` and `*.py[cod]`, so the file
  could only be committed by force-adding it. `scripts/ci/repo_hygiene.py` fails on a
  force-added file, and `vendor_check.py` fails on a lock entry that is not tracked. Python
  3.12 never loads a CPython 3.9 bytecode file, so leaving it out changes nothing at run time.
  This is recorded as a deviation from D5's "entire directory".
- **The sandbox database.** `tripartite data fetch` unpacks it here from the pinned zip
  (D5 §Database — unpacking). Those files are gitignored, never committed (§8.3), and
  checked by `tripartite data verify` against `data/MANIFEST.json`. `vendor_check.py`
  does not check them.

## Licences

- **Code:** MIT, Copyright (c) 2024 OSU Natural Language Processing. See `LICENSE` in this
  directory (the upstream file, unmodified) and the repository `NOTICE`.
- **Data:** the TravelPlanner dataset and the sandbox database are CC BY 4.0. This
  repository redistributes neither. Only `postprocess/example_evaluation.jsonl` (upstream's
  sample submission) and `database/README.md` (the schema description) are included here,
  as upstream ships them (A-017).

## How it was fetched

The copy came from a partial, sparse clone in a scratch folder outside the repository. Blobs
are fetched only for checked-out paths, so no `*_ref_info.jsonl` blob was ever downloaded:

```sh
git clone --filter=blob:none --no-checkout https://github.com/OSU-NLP-Group/TravelPlanner.git tp
git -C tp sparse-checkout set --no-cone '/evaluation/' '/tools/' '!/tools/restaurants/__pycache__/' \
    '/utils/' '/agents/prompts.py' '/postprocess/example_evaluation.jsonl' '/database/README.md' \
    '/LICENSE' '/README.md'
git -C tp checkout e52c87f4ac348a3410c46dc3553c519db5ec5e23
# Proof that the reference-information blobs were never fetched (each line starts with "?"):
git -C tp rev-list --objects --missing=print e52c87f4ac348a3410c46dc3553c519db5ec5e23 \
    | grep -E '^\?(0c1f11b8|587ca947|e1be7115)'
```

The checked-out files (those `git -C tp ls-files -t` marks `H`) were copied here. Each copy's
`git hash-object` equals the blob id in upstream's tree.

## Verifying

```sh
uv run python scripts/vendor_check.py
```

To re-vendor at a new commit, do it the same way, rebuild `VENDOR.lock` (27 entries, each
with `bytes`, `sha256` and `git_blob`; `upstream.commit` set to the new pin), and update the
pin in ARCHITECTURE.md §6 and `scripts/vendor_check.py`. Changing the pin is an
architecture decision.
