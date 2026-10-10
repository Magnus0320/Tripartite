"""``tripartite data fetch`` and ``tripartite data verify`` (ARCHITECTURE.md D9 ``make data``),
and ``tripartite data synthetic`` (D4 §Fake mode and data, FU-28, FU-32, FU-33)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.data import synthetic
from tripartite import cli as root_cli
from tripartite.data import download, manifest
from tripartite.data.cli import app
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.records import load_eval_records

runner = CliRunner()


@pytest.fixture
def hub(synthetic_raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake hf_hub_download that leaves the synthetic files where they are."""

    def fake(**kwargs: Any) -> str:
        return str(Path(kwargs["local_dir"]) / kwargs["filename"])

    monkeypatch.setattr(download, "hf_hub_download", fake)


@pytest.mark.usefixtures("hub", "synthetic_zip_pin")
def test_fetch_then_verify_succeeds(data_dir: Path) -> None:
    fetched = runner.invoke(app, ["fetch"])
    assert fetched.exit_code == 0, fetched.output
    assert f"dataset files recorded in {data_dir / 'MANIFEST.json'}" in fetched.output
    assert "sandbox_database.zip: OK" in fetched.output
    assert fetched.output.splitlines()[-1].endswith(
        f"database: unpacked 8 files; sha256 recorded in {data_dir / 'MANIFEST.json'}"
    )

    again = runner.invoke(app, ["fetch"])
    assert again.exit_code == 0, again.output
    assert "dataset files match" in again.output
    assert again.output.splitlines()[-1].endswith(
        f"database: 8 files match {data_dir / 'MANIFEST.json'}; nothing to unpack"
    )

    verified = runner.invoke(app, ["verify"])
    assert verified.exit_code == 0, verified.output
    lines = verified.output.splitlines()
    assert lines[-1] == "data verify: OK"
    assert sum(": OK (" in line for line in lines) == 12


@pytest.mark.usefixtures("hub", "synthetic_zip_pin")
def test_fetch_fails_on_a_database_zip_it_refuses(data_dir: Path) -> None:
    synthetic.write_database_zip(
        data_dir / "downloads" / "sandbox_database.zip", extra={"database/extra.csv": b"x"}
    )

    result = runner.invoke(app, ["fetch"])

    assert result.exit_code == 1
    assert "sandbox_database.zip: expected" in result.output  # no longer the pinned zip
    assert result.output.splitlines()[-1] == "data fetch: FAILED"


@pytest.mark.usefixtures("hub")
def test_fetch_fails_without_the_zip() -> None:
    result = runner.invoke(app, ["fetch"])

    assert result.exit_code == 1
    assert "sandbox_database.zip: missing: download it by hand" in result.output
    assert result.output.splitlines()[-1] == "data fetch: FAILED"


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_fails_and_lists_every_problem(synthetic_raw: Path) -> None:
    manifest.write_manifest(synthetic.matching_manifest(synthetic_raw), manifest.manifest_path())
    (synthetic_raw / "validation.csv").write_bytes(b"truncated")
    (synthetic_raw / "validation_ref_info.jsonl").unlink()

    result = runner.invoke(app, ["verify"])

    assert result.exit_code == 1
    assert "validation.csv: expected" in result.output
    assert "validation_ref_info.jsonl: missing" in result.output
    assert result.output.splitlines()[-1] == "data verify: FAILED"


@pytest.mark.parametrize("command", ["fetch", "verify"])
def test_an_invalid_data_dir_variable_fails_with_its_name(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", "data")

    result = runner.invoke(app, [command])

    assert result.exit_code == 1
    assert f"data {command}: TRIPARTITE_DATA_DIR must be an absolute path" in result.output
    assert result.output.splitlines()[-1] == f"data {command}: FAILED"


@pytest.mark.usefixtures("hub", "synthetic_zip_pin")
def test_the_root_cli_reaches_the_data_commands() -> None:
    assert runner.invoke(root_cli.app, ["data", "fetch"]).exit_code == 0
    result = runner.invoke(root_cli.app, ["data", "verify"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "data verify: OK"


# --- FU-28: ``data synthetic`` -------------------------------------------------------------------


@pytest.fixture
def repo_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the repository (``tmp_path / "repo"``) and its ``data/``, so a broken guard
    cannot write into the real ones."""
    root = tmp_path / "repo" / "data"
    root.mkdir(parents=True)
    monkeypatch.setattr(manifest, "REPO_ROOT", root.parent)
    monkeypatch.setattr(manifest, "DATA_DIR", root)
    return root


@pytest.fixture
def repo(repo_data: Path) -> Path:
    """The stand-in repository root."""
    return repo_data.parent


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


@pytest.mark.usefixtures("repo_data")
def test_synthetic_writes_the_set_and_prints_the_absolute_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(root_cli.app, ["data", "synthetic", "--out", "new/syn"])

    assert result.exit_code == 0, result.output
    root = (tmp_path / "new" / "syn").resolve()
    assert result.stdout == f"{root}\n"  # the path alone, so $(...) can capture it
    assert f"use the path below as {manifest.DATA_DIR_ENV}" in result.stderr
    assert tree(root) == ["raw", "raw/validation.csv", "raw/validation_ref_info.jsonl"]
    expected = synthetic.write_synthetic_data_dir(tmp_path / "expected") / "raw"
    for name in manifest.HF_FILES:
        assert (root / "raw" / name).read_bytes() == (expected / name).read_bytes()

    monkeypatch.setenv(manifest.DATA_DIR_ENV, result.stdout.strip())
    inputs = load_planner_inputs()
    assert [inp.query for inp in inputs] == [synthetic.query(i) for i in range(1, 181)]


@pytest.mark.parametrize("inside", ["", "x", "raw", "deep/er/syn"])
def test_synthetic_refuses_an_out_inside_the_repo_data_dir(inside: str, repo_data: Path) -> None:
    out = repo_data / inside

    result = runner.invoke(app, ["synthetic", "--out", str(out)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert f"data synthetic: --out {out} resolves to" in result.stderr
    assert f"which is inside the repository {repo_data.parent.resolve()}" in result.stderr
    assert result.stderr.splitlines()[-1] == "data synthetic: FAILED"
    assert tree(repo_data) == []


def test_synthetic_refuses_an_out_that_reaches_the_repo_data_dir_through_a_symlink(
    tmp_path: Path, repo_data: Path
) -> None:
    link = tmp_path / "elsewhere"
    link.symlink_to(repo_data, target_is_directory=True)

    for out in (link, link / "syn"):
        result = runner.invoke(app, ["synthetic", "--out", str(out)])

        assert result.exit_code == 1, out
        assert f"which is inside the repository {repo_data.parent.resolve()}" in result.stderr
    assert tree(repo_data) == []


def test_synthetic_refuses_a_relative_out_inside_the_repo_data_dir(
    repo_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_data.parent)

    result = runner.invoke(app, ["synthetic", "--out", "data/x"])

    assert result.exit_code == 1
    assert "data synthetic: --out data/x resolves to" in result.stderr
    assert tree(repo_data) == []


def test_synthetic_accepts_a_sibling_whose_name_starts_with_the_repositorys(
    tmp_path: Path, repo: Path
) -> None:
    out = repo.parent / "repo-synthetic"

    result = runner.invoke(app, ["synthetic", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{out.resolve()}\n"


def test_the_default_guarded_directory_is_the_repo_data_dir() -> None:
    assert manifest.DATA_DIR == manifest.REPO_ROOT / "data"
    result = runner.invoke(app, ["synthetic", "--out", str(manifest.DATA_DIR / "x")])

    assert result.exit_code == 1
    assert not (manifest.DATA_DIR / "x").exists()


def test_synthetic_fails_cleanly_when_out_cannot_be_written(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    result = runner.invoke(app, ["synthetic", "--out", str(blocker / "syn")])

    assert result.exit_code == 1
    assert "data synthetic: cannot write the set under" in result.stderr
    assert result.stderr.splitlines()[-1] == "data synthetic: FAILED"


# --- FU-33: no ``--out`` anywhere inside the repository ------------------------------------------


def assert_refused(result: Any, out: object, resolved: Path, repo: Path) -> None:
    assert result.exit_code == 1
    assert result.stdout == ""
    assert (
        f"data synthetic: --out {out} resolves to {resolved}, which is inside the repository "
        f"{repo.resolve()}: "
    ) in result.stderr
    assert (
        "choose a directory outside the repository, such as ~/.cache/tripartite/synthetic-scoreable"
    ) in result.stderr
    assert result.stderr.splitlines()[-1] == "data synthetic: FAILED"


@pytest.mark.parametrize("inside", ["", "syn", "deep/er/syn", "data/x", "src/tripartite"])
@pytest.mark.parametrize("flags", [[], ["--scoreable"]])
def test_synthetic_refuses_an_out_inside_the_repository(
    inside: str, flags: list[str], repo: Path
) -> None:
    out = repo / inside

    result = runner.invoke(app, ["synthetic", "--out", str(out), *flags])

    assert_refused(result, out, out.resolve(), repo)
    assert tree(repo) == ["data"]


@pytest.mark.parametrize("relative", [".", "syn", "data/x", "nested/syn", "../repo/syn"])
def test_synthetic_refuses_a_relative_out_inside_the_repository(
    relative: str, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["synthetic", "--out", relative])

    assert_refused(result, relative, (repo / relative).resolve(), repo)
    assert tree(repo) == ["data"]


def test_synthetic_refuses_an_out_that_reaches_the_repository_through_a_symlink(
    tmp_path: Path, repo: Path
) -> None:
    link = tmp_path / "elsewhere"
    link.symlink_to(repo, target_is_directory=True)

    for out in (link, link / "syn"):
        result = runner.invoke(app, ["synthetic", "--out", str(out)])

        assert_refused(result, out, out.resolve(), repo)
    assert tree(repo) == ["data"]


def test_synthetic_accepts_a_directory_outside_the_repository(tmp_path: Path, repo: Path) -> None:
    out = tmp_path / "outside" / "syn"

    result = runner.invoke(app, ["synthetic", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{out.resolve()}\n"
    assert tree(out) == ["raw", "raw/validation.csv", "raw/validation_ref_info.jsonl"]
    assert tree(repo) == ["data"]


def test_the_default_guarded_directory_is_the_repository_root() -> None:
    assert (manifest.REPO_ROOT / "pyproject.toml").is_file()
    out = manifest.REPO_ROOT / "fu33-must-not-exist"

    result = runner.invoke(app, ["synthetic", "--scoreable", "--out", str(out)])

    assert_refused(result, out, out.resolve(), manifest.REPO_ROOT)
    assert not out.exists()


# --- FU-32: ``--scoreable`` ----------------------------------------------------------------------


@pytest.mark.usefixtures("repo_data")
def test_synthetic_scoreable_writes_the_scoreable_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "syn"

    result = runner.invoke(root_cli.app, ["data", "synthetic", "--scoreable", "--out", str(out)])

    assert result.exit_code == 0, result.output
    root = out.resolve()
    assert result.stdout == f"{root}\n"  # still the path alone
    assert "wrote 180 scoreable synthetic rows" in result.stderr
    assert tree(root) == ["raw", "raw/validation.csv", "raw/validation_ref_info.jsonl"]
    expected = synthetic.write_synthetic_data_dir(tmp_path / "expected", scoreable=True) / "raw"
    canary = synthetic.write_synthetic_data_dir(tmp_path / "canary") / "raw"
    for name in manifest.HF_FILES:
        assert (root / "raw" / name).read_bytes() == (expected / name).read_bytes()
    assert (root / "raw" / "validation.csv").read_bytes() != (
        canary / "validation.csv"
    ).read_bytes()

    monkeypatch.setenv(manifest.DATA_DIR_ENV, result.stdout.strip())
    assert {r.level for r in load_eval_records()} == {"easy", "medium", "hard"}


@pytest.mark.usefixtures("repo_data")
def test_synthetic_without_the_flag_overwrites_a_scoreable_copy_with_the_canary_set(
    tmp_path: Path,
) -> None:
    out = tmp_path / "syn"
    assert runner.invoke(app, ["synthetic", "--scoreable", "--out", str(out)]).exit_code == 0

    result = runner.invoke(app, ["synthetic", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "wrote 180 synthetic rows" in result.stderr
    canary = synthetic.write_synthetic_data_dir(tmp_path / "canary") / "raw"
    for name in manifest.HF_FILES:
        assert (out / "raw" / name).read_bytes() == (canary / name).read_bytes()
