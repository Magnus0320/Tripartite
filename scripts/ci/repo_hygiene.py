"""Repository hygiene check (ARCHITECTURE.md §8). Runs on every CI run, unguarded.

The repository is public. This fails if any file that is tracked, or that could be committed
(untracked and not ignored), is something §8 says is never committed:

1. dataset files: anything under the repository-root data/ directory except
   data/MANIFEST.json (a root-level file named data is not under it);
2. test-split artefacts, matched on the file name only: test.csv, test_ref_info.jsonl, or a
   name matching *test*ref_info* with a data extension (.csv .jsonl .json .parquet .zip .gz
   .txt), so source and test files such as tests/data/test_ref_info_alignment.py are fine;
3. the sandbox database: anything under vendor/travelplanner/database/ except its README.md;
4. run output: anything under the repository-root runs/ or mlruns/ directories (a directory
   called runs elsewhere, such as web/src/runs/, is unaffected);
5. secrets and local agent state: .env and .env.* files, .claude/settings.local.json,
   .claude/worktrees/, and key-shaped strings (sk-, hf_, ghp_, AKIA).

It also fails on a tracked file that .gitignore ignores (force-added), and on any file larger
than 2 MB except lockfiles. Standard library only. Run from anywhere inside the repository:

    uv run python scripts/ci/repo_hygiene.py
"""

import fnmatch
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_BYTES = 2_000_000
DATA_EXTENSIONS = frozenset({".csv", ".jsonl", ".json", ".parquet", ".zip", ".gz", ".txt"})
LOCKFILES = frozenset({"uv.lock", "package-lock.json"})
KEY_PATTERNS = {
    "sk-": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "hf_": re.compile(rb"\bhf_[A-Za-z0-9]{30,}"),
    "ghp_": re.compile(rb"\bghp_[A-Za-z0-9]{36}"),
    "AKIA": re.compile(rb"\bAKIA[0-9A-Z]{16}"),
}


def _git(root: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout.decode()
    return [p for p in out.split("\0") if p]


def path_violations(path: str) -> list[str]:
    """Reasons why §8 forbids committing ``path`` (repository-relative, POSIX)."""
    parts = PurePosixPath(path).parts
    name = parts[-1]
    reasons = []
    if len(parts) > 1 and parts[0] == "data" and path != "data/MANIFEST.json":
        reasons.append("dataset file under data/ (§8.1)")
    lower = name.lower()
    if lower in {"test.csv", "test_ref_info.jsonl"} or (
        fnmatch.fnmatchcase(lower, "*test*ref_info*")
        and PurePosixPath(lower).suffix in DATA_EXTENSIONS
    ):
        reasons.append("test-split artefact (§8.2)")
    if (
        path.startswith("vendor/travelplanner/database/")
        and path != "vendor/travelplanner/database/README.md"
    ):
        reasons.append("sandbox database (§8.3)")
    if len(parts) > 1 and parts[0] in {"runs", "mlruns"}:
        reasons.append("run output under the root runs/ or mlruns/ (§8.4)")
    if name == ".env" or name.startswith(".env."):
        reasons.append(".env file (§8.5)")
    if path == ".claude/settings.local.json" or path.startswith(".claude/worktrees/"):
        reasons.append("local Claude Code state (§8.5)")
    return reasons


def content_violations(file: Path, name: str) -> list[str]:
    """Reasons why the file's size or content must not be committed."""
    reasons = []
    size = file.stat().st_size
    if size > MAX_BYTES and name not in LOCKFILES:
        reasons.append(f"larger than 2 MB ({size} bytes)")
    data = file.read_bytes()
    reasons.extend(
        f"key-shaped string ({prefix}...) (§8.5)"
        for prefix, pattern in KEY_PATTERNS.items()
        if pattern.search(data)
    )
    return reasons


def main() -> int:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    candidates = sorted(
        set(_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    )
    force_added = set(_git(root, "ls-files", "-z", "--cached", "--ignored", "--exclude-standard"))

    violations: list[str] = []
    for path in candidates:
        reasons = path_violations(path)
        if path in force_added:
            reasons.append("tracked although .gitignore ignores it")
        file = root / path
        if file.is_file() and not file.is_symlink():
            reasons.extend(content_violations(file, PurePosixPath(path).name))
        violations.extend(f"{path}: {reason}" for reason in reasons)

    if violations:
        print("repo hygiene: FAILED (ARCHITECTURE.md §8)")
        for line in violations:
            print(f"  {line}")
        return 1
    print(f"repo hygiene: OK ({len(candidates)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
