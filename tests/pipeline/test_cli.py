"""``tripartite run start|rescore`` (ARCHITECTURE.md D1, D7, D9 Makefile table).

``default_deps`` is replaced so every run lands under ``tmp_path``; ``signal.signal`` is replaced
so the SIGTERM handler ``start`` installs never outlives the test.
"""

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.fixtures.model.run_deps import fake_deps, fixed_env, write_config
from tripartite import cli as root_cli
from tripartite.config import SMOKE_CONFIG_PATH
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult
from tripartite.pipeline import cli
from tripartite.pipeline.run import RunDeps

runner = CliRunner()


@pytest.fixture
def deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., RunDeps]:
    """Point the CLI at ``tmp_path``; call it with overrides to change the next run's deps."""
    changes: dict[str, Any] = {}
    monkeypatch.setattr(cli, "default_deps", lambda: fake_deps(tmp_path, **changes))
    monkeypatch.setattr(cli.signal, "signal", lambda *_args: None)

    def configure(**more: Any) -> RunDeps:
        changes.clear()
        changes.update(more)
        return fake_deps(tmp_path, **changes)

    return configure


def run_id_of(output: str) -> str:
    first = output.splitlines()[0]
    assert first.startswith("run start: "), output
    return first.split()[3]


def test_start_a_run_from_a_config(deps: Callable[..., RunDeps]) -> None:
    deps()

    result = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("run start: started 2026")
    assert sum(line.startswith("run: [") for line in lines) == 27
    assert "run start: Delivery Rate: 100.0% ± 0.0 (seed 0: 100.0%" in result.output
    assert lines[-1].startswith("run start: succeeded: ")


def test_the_root_cli_reaches_run(deps: Callable[..., RunDeps]) -> None:
    deps()

    result = runner.invoke(root_cli.app, ["run", "start", "--config", str(SMOKE_CONFIG_PATH)])

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "args", [[], ["--config", "configs/smoke.yaml", "--resume", "x"]], ids=["neither", "both"]
)
def test_start_takes_exactly_one_of_config_or_resume(
    args: list[str], deps: Callable[..., RunDeps]
) -> None:
    result = runner.invoke(cli.app, ["start", *args])

    assert result.exit_code == 1
    assert "pass exactly one of --config <path> or --resume <run_id>" in result.output


def test_a_config_that_does_not_load_stops_start(
    tmp_path: Path, deps: Callable[..., RunDeps]
) -> None:
    result = runner.invoke(cli.app, ["start", "--config", str(tmp_path / "none.yaml")])

    assert result.exit_code == 1
    assert "ConfigError" in result.output
    assert result.output.splitlines()[-1] == "run start: FAILED"


class Interrupting:
    def __init__(self) -> None:
        self.inner = FakeClient(FakeTokenizer())
        self.calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResult:
        self.calls += 1
        if self.calls == 3:
            raise KeyboardInterrupt
        return self.inner.generate(request)


def test_interrupt_then_resume(deps: Callable[..., RunDeps]) -> None:
    deps(client=Interrupting())
    first = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])
    run_id = run_id_of(first.output)

    assert first.exit_code == 130
    assert f"make resume RUN={run_id}" in first.output

    deps()
    resumed = runner.invoke(cli.app, ["start", "--resume", run_id])

    assert resumed.exit_code == 0, resumed.output
    assert resumed.output.splitlines()[0].startswith(f"run start: resuming {run_id}")
    assert sum(line.startswith("run: [") for line in resumed.output.splitlines()) == 26


def test_a_failed_run_exits_1(deps: Callable[..., RunDeps], tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text(
        SMOKE_CONFIG_PATH.read_text(encoding="utf-8").replace(
            "num_predict: 4096", "num_predict: 32000"
        ),
        encoding="utf-8",
    )
    deps()

    result = runner.invoke(cli.app, ["start", "--config", str(config)])

    assert result.exit_code == 1
    assert "run start: failed: ContextOverflowError" in result.output


def test_rescore(deps: Callable[..., RunDeps]) -> None:
    deps()
    started = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])
    run_id = run_id_of(started.output)

    result = runner.invoke(cli.app, ["rescore", "--run", run_id])

    assert result.exit_code == 0, result.output
    oks = [line for line in result.output.splitlines() if line.startswith("run rescore: OK ")]
    assert len(oks) == 7
    assert result.output.splitlines()[-1] == "run rescore: 7 files byte-identical"


def test_a_rescore_mismatch_exits_1(deps: Callable[..., RunDeps], tmp_path: Path) -> None:
    deps()
    started = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])
    run_id = run_id_of(started.output)
    metrics = tmp_path / "runs" / run_id / "metrics.json"
    metrics.write_text(metrics.read_text(encoding="utf-8") + " ", encoding="utf-8")

    result = runner.invoke(cli.app, ["rescore", "--run", run_id])

    assert result.exit_code == 1
    assert "run rescore: MISMATCH metrics.json: " in result.output
    assert result.output.splitlines()[-1] == "run rescore: FAILED"


@pytest.mark.parametrize("run_id", ["20260928T120000Z-batch-00000000-0000", "not-a-run-id"])
def test_rescore_of_an_unknown_run_exits_1(run_id: str, deps: Callable[..., RunDeps]) -> None:
    result = runner.invoke(cli.app, ["rescore", "--run", run_id])

    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "run rescore: FAILED"


def test_fake_mode_on_the_real_data_stops_start(
    deps: Callable[..., RunDeps], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FU-27: the message names the variable to set."""
    deps()
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")

    result = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])

    assert result.exit_code == 1
    assert "FakeModeRealDataError" in result.output
    assert "TRIPARTITE_DATA_DIR" in result.output


def test_a_full_run_needs_allow_dirty_on_a_dirty_tree(
    deps: Callable[..., RunDeps], tmp_path: Path
) -> None:
    """FU-29: refused without the flag; with it the run starts and records it."""
    config = write_config(tmp_path / "full.yaml", queries="all", seeds=[0])
    deps(env_probe=partial(fixed_env, git_dirty=True))

    refused = runner.invoke(cli.app, ["start", "--config", str(config)])

    assert refused.exit_code == 1
    assert "DirtyTreeError" in refused.output
    assert "--allow-dirty" in refused.output

    allowed = runner.invoke(cli.app, ["start", "--config", str(config), "--allow-dirty"])

    assert allowed.exit_code == 0, allowed.output
    manifest = (tmp_path / "runs" / run_id_of(allowed.output) / "manifest.json").read_text()
    assert '"allow_dirty": true' in manifest
