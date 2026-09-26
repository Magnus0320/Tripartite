"""Test-split refusal (ARCHITECTURE.md D3, boundary test 4, ``test_test_split_forbidden``).

CI's guarded M1 step exists because of this file. Both loaders and the downloader must refuse
the test split, and any split or file other than the allowed ones, **before** any file or
network access. Every refusal runs inside ``no_io()``, which replaces the file-opening
functions and ``hf_hub_download`` with ones that fail the test if they are called.
"""

import builtins
import contextlib
import inspect
import io
import os
import pathlib
from collections.abc import Callable, Iterator
from typing import Any, NoReturn

import huggingface_hub
import pytest

from tripartite.data import download, planner_inputs
from tripartite.evaluation import records

LOADERS: list[Callable[[str], Any]] = [
    planner_inputs.load_planner_inputs,
    records.load_eval_records,
]
LOADER_IDS = ["load_planner_inputs", "load_eval_records"]


class ForbiddenAccessError(AssertionError):
    pass


@contextlib.contextmanager
def no_io() -> Iterator[None]:
    """Fail the test if anything inside opens, stats or lists a file, or calls the Hub."""

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise ForbiddenAccessError("file or network access before the split check")

    targets: list[tuple[object, str]] = [
        (builtins, "open"),
        (io, "open"),
        (os, "open"),
        (os, "stat"),
        (os, "listdir"),
        (os, "scandir"),
        (pathlib.Path, "open"),
        (pathlib.Path, "stat"),
        (pathlib.Path, "exists"),
        (pathlib.Path, "is_file"),
        (pathlib.Path, "read_bytes"),
        (pathlib.Path, "read_text"),
        (huggingface_hub, "hf_hub_download"),
        (download, "hf_hub_download"),
    ]
    with pytest.MonkeyPatch.context() as mp:
        for target, name in targets:
            mp.setattr(target, name, forbidden)
        yield


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
@pytest.mark.parametrize("split", ["test", "TEST", " Test "])
def test_test_split_is_refused_before_any_io(loader: Callable[[str], Any], split: str) -> None:
    with no_io(), pytest.raises(planner_inputs.TestSplitForbiddenError):
        loader(split)


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
@pytest.mark.parametrize("split", ["train", "valid", "Validation", "validation ", ""])
def test_any_other_split_is_refused_before_any_io(loader: Callable[[str], Any], split: str) -> None:
    with no_io(), pytest.raises(ValueError, match="only 'validation'"):
        loader(split)


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
def test_the_default_split_is_validation(loader: Callable[[str], Any]) -> None:
    assert inspect.signature(loader).parameters["split"].default == "validation"


@pytest.mark.parametrize("filename", ["test.csv", "test_ref_info.jsonl", "Test.CSV"])
def test_the_downloader_refuses_test_split_files_before_any_io(filename: str) -> None:
    with no_io(), pytest.raises(planner_inputs.TestSplitForbiddenError):
        download.fetch_dataset_file(filename)


@pytest.mark.parametrize(
    "filename",
    [
        "train.csv",
        "train_ref_info.jsonl",
        "example_submission.jsonl",
        "README.md",
        "../validation.csv",
        "raw/validation.csv",
    ],
)
def test_the_downloader_refuses_files_outside_the_allowlist_before_any_io(filename: str) -> None:
    with no_io(), pytest.raises(ValueError, match="allowlist"):
        download.fetch_dataset_file(filename)


def test_the_allowlist_is_exactly_the_two_validation_files() -> None:
    assert set(download.HF_FILES) == {"validation.csv", "validation_ref_info.jsonl"}


def test_test_split_forbidden_error_is_a_runtime_error() -> None:
    assert issubclass(planner_inputs.TestSplitForbiddenError, RuntimeError)


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
def test_no_io_catches_the_file_access_of_a_real_load(loader: Callable[[str], Any]) -> None:
    """The guard is not vacuous: an allowed split does reach the file system and trips it."""
    with no_io(), pytest.raises(ForbiddenAccessError):
        loader("validation")


def test_no_io_catches_a_real_download() -> None:
    with no_io(), pytest.raises(ForbiddenAccessError):
        download.fetch_dataset_file("validation.csv")
