"""D3 boundary test 5 (local): no test-split file exists under data/ or vendor/."""

import fnmatch

import pytest

from tripartite.data import manifest

pytestmark = pytest.mark.local


def _is_test_split_file(name: str) -> bool:
    lower = name.lower()
    return lower in {"test.csv", "test_ref_info.jsonl"} or fnmatch.fnmatchcase(
        lower, "*test*ref_info*"
    )


def test_no_test_split_files_on_disk() -> None:
    roots = [manifest.REPO_ROOT / "data", manifest.REPO_ROOT / "vendor"]
    found = [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if _is_test_split_file(path.name)
    ]

    assert found == []
