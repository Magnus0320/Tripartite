"""Fixtures for the MLflow sync tests (M6): throwaway stores and repositories, and no network."""

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.runlog import samples
from tripartite.runlog.mlflow_sync import SyncResult, sync_run


@dataclass(frozen=True)
class Workspace:
    """A runs directory, an MLflow file store and a git repository, all under ``tmp_path``."""

    runs_dir: Path
    mlruns_dir: Path
    repo: Path
    commit: str
    """The repository's one commit, whose ``ARCHITECTURE.md`` says v0.12."""

    def write_run(self, **overrides: Any) -> Path:
        return samples.write_run_dir(self.runs_dir, **({"git_commit": self.commit} | overrides))

    def sync(self, run_id: str = samples.RUN_ID) -> SyncResult:
        return sync_run(
            run_id, runs_dir=self.runs_dir, mlruns_dir=self.mlruns_dir, repo_root=self.repo
        )


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git away from the user's and the system's configuration."""
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if anything opens a socket connection."""

    def refuse(_self: socket.socket, address: object) -> None:
        raise AssertionError(f"a network connection was attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture
def workspace(tmp_path: Path, isolated_git: None, no_network: None) -> Workspace:
    repo = tmp_path / "repo"
    return Workspace(
        runs_dir=tmp_path / "runs",
        mlruns_dir=tmp_path / "mlruns",
        repo=repo,
        commit=samples.write_git_repo(repo),
    )
