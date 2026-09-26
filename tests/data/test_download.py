"""The downloader (ARCHITECTURE.md D3, §6). ``hf_hub_download`` is faked: CI has no Hub access."""

import ast
from pathlib import Path
from typing import Any

import pytest

from tests.data import synthetic
from tripartite.data import download, manifest

PINNED_CALL = {
    "repo_id": "osunlp/TravelPlanner",
    "repo_type": "dataset",
    "revision": "8736504ecfc31b7f8b7e40122873c337e83fff7c",
}


class FakeHub:
    """Stands in for ``hf_hub_download``: writes synthetic bytes where the real one would."""

    def __init__(self, contents: dict[str, bytes]) -> None:
        self.contents = contents
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        path = Path(kwargs["local_dir"]) / kwargs["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.contents[kwargs["filename"]])
        return str(path)


def _contents(tag: bytes = b"") -> dict[str, bytes]:
    return {
        "validation.csv": b"query\n" + b"synthetic question\n" * 3 + tag,
        "validation_ref_info.jsonl": b'{"synthetic": 1}\n' * 3 + tag,
    }


@pytest.fixture
def hub(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FakeHub:
    fake = FakeHub(_contents())
    monkeypatch.setattr(download, "hf_hub_download", fake)
    return fake


def test_fetch_downloads_exactly_the_allowlist_at_the_pinned_revision(
    hub: FakeHub, data_dir: Path
) -> None:
    download.fetch()

    assert hub.calls == [
        {**PINNED_CALL, "filename": name, "local_dir": data_dir / "raw"}
        for name in ("validation.csv", "validation_ref_info.jsonl")
    ]


def test_the_first_fetch_records_the_files_in_a_new_manifest(hub: FakeHub, data_dir: Path) -> None:
    result = download.fetch()

    assert result.recorded
    written = manifest.load_manifest(data_dir / "MANIFEST.json")
    assert written.database_zip == manifest.DATABASE_ZIP
    assert manifest.manifest_pin_problems(written) == []
    for name, content in _contents().items():
        entry = written.dataset.files[name]
        assert entry.bytes == len(content)
        assert entry.sha256 == manifest.sha256_file(data_dir / "raw" / name)
        assert result.files[name] == entry


def test_a_fetch_that_reproduces_the_manifest_leaves_it_unchanged(
    hub: FakeHub, data_dir: Path
) -> None:
    download.fetch()
    before = (data_dir / "MANIFEST.json").read_bytes()

    result = download.fetch()

    assert not result.recorded
    assert (data_dir / "MANIFEST.json").read_bytes() == before
    assert len(hub.calls) == 4


def test_a_fetch_with_different_bytes_is_refused(hub: FakeHub, data_dir: Path) -> None:
    download.fetch()
    before = (data_dir / "MANIFEST.json").read_bytes()
    recorded = manifest.load_manifest(data_dir / "MANIFEST.json").dataset.files["validation.csv"]
    hub.contents = _contents(tag=b"changed upstream\n")

    with pytest.raises(manifest.DataError) as info:
        download.fetch()

    message = str(info.value)
    new_sha = manifest.sha256_file(data_dir / "raw" / "validation.csv")
    assert (
        f"downloaded {len(hub.contents['validation.csv'])} bytes with sha256 {new_sha}" in message
    )
    assert f"has {recorded.bytes} bytes with sha256 {recorded.sha256}" in message
    assert (data_dir / "MANIFEST.json").read_bytes() == before


def test_a_manifest_for_another_revision_is_refused(hub: FakeHub, data_dir: Path) -> None:
    download.fetch()
    path = data_dir / "MANIFEST.json"
    old = manifest.load_manifest(path)
    manifest.write_manifest(
        old.model_copy(update={"dataset": old.dataset.model_copy(update={"revision": "main"})}),
        path,
    )

    with pytest.raises(manifest.DataError, match=r"dataset\.revision is 'main'"):
        download.fetch()


def test_a_download_landing_elsewhere_is_refused(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere.csv"
    elsewhere.write_bytes(b"x")
    monkeypatch.setattr(download, "hf_hub_download", lambda **kwargs: str(elsewhere))

    with pytest.raises(manifest.DataError, match="hf_hub_download wrote"):
        download.fetch_dataset_file("validation.csv")


def test_the_downloader_uses_hf_hub_download_only() -> None:
    """D3: never snapshot_download and never datasets.load_dataset, anywhere in tripartite.data."""
    package = Path(download.__file__).parent
    for source in sorted(package.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {
            alias.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for alias in n.names
        }
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not names & {"snapshot_download", "load_dataset", "datasets"}, source.name
        assert not {m.split(".")[0] for m in modules} & {"datasets"}, source.name


@pytest.mark.usefixtures("synthetic_raw")
def test_fetch_works_with_the_synthetic_layout(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch over files already in data/raw records exactly those files."""
    raw = data_dir / "raw"
    fake = FakeHub({name: (raw / name).read_bytes() for name in manifest.HF_FILES})
    monkeypatch.setattr(download, "hf_hub_download", fake)

    download.fetch()

    assert manifest.load_manifest(data_dir / "MANIFEST.json") == synthetic.matching_manifest(raw)
