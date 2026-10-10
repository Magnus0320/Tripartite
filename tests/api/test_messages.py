"""``public_message``: no absolute path in a message for a response body (D8, FU-35)."""

import logging
from pathlib import Path

import pytest

from tripartite.api.messages import public_message
from tripartite.config import REPO_ROOT
from tripartite.data.manifest import DATA_DIR


def test_a_path_under_the_data_root_becomes_data_root_relative(synthetic_data: Path) -> None:
    path = synthetic_data / "raw" / "validation.csv"

    assert (
        public_message(f"[Errno 2] No such file or directory: '{path}'")
        == "[Errno 2] No such file or directory: 'raw/validation.csv'"
    )
    assert public_message(f"{path} has 100 lines") == "raw/validation.csv has 100 lines"


def test_the_default_data_root_is_used_when_the_variable_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")

    assert public_message(f"cannot read {DATA_DIR / 'raw' / 'validation.csv'}") == (
        "cannot read raw/validation.csv"
    )


def test_a_relative_data_root_variable_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", "relative/data")

    assert public_message(f"cannot read {DATA_DIR / 'MANIFEST.json'}") == (
        "cannot read MANIFEST.json"
    )


def test_a_path_under_the_repository_becomes_repository_relative() -> None:
    path = REPO_ROOT / "configs" / "single.yaml"

    assert public_message(f"{path}: not a mapping") == "configs/single.yaml: not a mapping"
    assert public_message(f"see {REPO_ROOT / 'data' / 'MANIFEST.json'}") == (
        "see data/MANIFEST.json"
    )


def test_any_other_absolute_path_becomes_its_file_name() -> None:
    assert public_message("cannot open /etc/tripartite/stack.yaml") == "cannot open stack.yaml"
    assert public_message("/var/tmp/runs/r1/events.jsonl:7: truncated line") == (
        "events.jsonl:7: truncated line"
    )
    assert public_message("path=/opt/x/y.json, and (/opt/x/z.json) [/opt/w/]") == (
        "path=y.json, and (z.json) [w]"
    )


def test_a_quoted_path_is_taken_whole_spaces_included() -> None:
    assert public_message("no such file: '/Users/some one/My Files/plan v2.txt'") == (
        "no such file: 'plan v2.txt'"
    )
    assert public_message('got "/Users/some one/dir/"') == 'got "dir"'


def test_a_root_with_spaces_is_removed_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "my data"
    root.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))

    assert public_message(f"{root}/raw/validation.csv: bad header") == (
        "raw/validation.csv: bad header"
    )


def test_a_root_itself_becomes_its_last_component(synthetic_data: Path) -> None:
    assert public_message(f"got '{synthetic_data}'") == "got 'data'"
    assert public_message(f"which means {REPO_ROOT})") == f"which means {REPO_ROOT.name})"


def test_the_resolved_form_of_a_root_is_removed_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    (real / "raw").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(link))

    assert public_message(f"{link}/raw/a.csv and {real.resolve()}/raw/b.csv") == (
        "raw/a.csv and raw/b.csv"
    )


@pytest.mark.parametrize(
    "text",
    [
        "TransportError: GET http://127.0.0.1:11435/api/tags failed: connection refused",
        "1 validation error, see https://errors.pydantic.dev/2.11/v/missing for details",
        "the model server at http://localhost:11435/ did not answer",
    ],
)
def test_a_url_inside_an_error_message_is_left_untouched(
    text: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="tripartite.api"):
        assert public_message(text) == text
    assert caplog.records == []


def test_a_url_stays_while_a_path_beside_it_is_rewritten() -> None:
    text = "GET http://127.0.0.1:11435/api/tags failed; see /var/log/tripartite/server.log"

    assert public_message(text) == "GET http://127.0.0.1:11435/api/tags failed; see server.log"


@pytest.mark.parametrize(
    "text",
    ["", "the evaluator crashed", "3/5 pairs done", "and/or", "a / b", "ratio 1/2:3"],
)
def test_text_without_an_absolute_path_is_unchanged_and_not_logged(
    text: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="tripartite.api"):
        assert public_message(text) == text
    assert caplog.records == []


def test_it_is_idempotent(synthetic_data: Path) -> None:
    text = f"{synthetic_data}/raw/x.csv, {REPO_ROOT}/configs/a.yaml, '/o ther/b.txt', /c/d.e:3"
    once = public_message(text)

    assert once == "raw/x.csv, configs/a.yaml, 'b.txt', d.e:3"
    assert public_message(once) == once


def test_the_full_text_is_logged_when_it_was_changed(
    synthetic_data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    text = f"cannot read {synthetic_data}/raw/validation.csv"

    with caplog.at_level(logging.WARNING, logger="tripartite.api"):
        public_message(text)

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert text in caplog.records[0].getMessage()


def test_log_false_logs_nothing(synthetic_data: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="tripartite.api"):
        assert public_message(f"x {synthetic_data}/raw/a.csv", log=False) == "x raw/a.csv"
    assert caplog.records == []
