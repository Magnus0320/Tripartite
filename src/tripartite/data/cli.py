"""``tripartite data``: fetch and verify the pinned data (ARCHITECTURE.md D3, D5, §6), and write
the synthetic set (D4 §Fake mode and data, FU-28).

``make data`` runs ``fetch`` then ``verify``; ``make doctor`` runs ``verify``. Both exit 1 on
any mismatch with the pins, printing the expected and actual values. ``fetch`` also unpacks the
verified database zip into ``vendor/travelplanner/database/`` (D5 §Database — unpacking).

``synthetic --out DIR`` writes the shared synthetic set under ``DIR`` and prints the absolute data
root on stdout, for ``TRIPARTITE_DATA_DIR``. Fake mode is synthetic-data-only (D4), so this is
what web development and ``make api`` in fake mode run on. It refuses a ``DIR`` that resolves to
``<repo>/data`` or to a path inside it, where the real data lives.
"""

import zipfile
from pathlib import Path
from typing import Annotated

import typer

from tripartite.data import download, manifest
from tripartite.data import synthetic as synthetic_set

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Fetch and verify the pinned dataset files and the sandbox database zip; write the
    synthetic set for fake mode."""


def _fail(command: str, problems: list[str]) -> typer.Exit:
    for problem in problems:
        typer.echo(f"data {command}: {problem}", err=True)
    typer.echo(f"data {command}: FAILED", err=True)
    return typer.Exit(1)


@app.command()
def fetch() -> None:
    """Download validation.csv and validation_ref_info.jsonl at the pinned revision, record or
    check them in data/MANIFEST.json, check the database zip against the D5 pin, and unpack it
    into vendor/travelplanner/database/."""
    try:
        result = download.fetch()
    except manifest.DataError as exc:
        raise _fail("fetch", [str(exc)]) from None
    for name, entry in result.files.items():
        typer.echo(
            f"data fetch: {manifest.display(manifest.raw_dir() / name)} from "
            f"{manifest.HF_REPO_ID}@{manifest.HF_REVISION} "
            f"({entry.bytes} bytes, sha256 {entry.sha256})"
        )
    action = "recorded in" if result.recorded else "match"
    typer.echo(f"data fetch: dataset files {action} {manifest.display(manifest.manifest_path())}")
    zip_label = manifest.display(manifest.database_zip_path())
    if problems := manifest.check_database_zip():
        raise _fail("fetch", [f"{zip_label}: {p}" for p in problems])
    typer.echo(f"data fetch: {zip_label}: OK ({manifest.DATABASE_ZIP.bytes} bytes, the D5 pin)")
    try:
        unpacked = download.unpack_database()
    except (manifest.DataError, OSError, zipfile.BadZipFile) as exc:
        raise _fail("fetch", [str(exc)]) from None
    tree = manifest.display(manifest.vendor_database_dir())
    mlabel = manifest.display(manifest.manifest_path())
    n = len(unpacked.files)
    if not unpacked.unpacked:
        typer.echo(f"data fetch: {tree}: {n} files match {mlabel}; nothing to unpack")
    elif unpacked.recorded:
        typer.echo(f"data fetch: {tree}: unpacked {n} files; sha256 recorded in {mlabel}")
    else:
        typer.echo(f"data fetch: {tree}: unpacked {n} files; they match {mlabel}")


@app.command()
def verify() -> None:
    """Check data/MANIFEST.json, the dataset files and the database zip against the pins."""
    try:
        checks = manifest.verify()
    except manifest.DataError as exc:
        raise _fail("verify", [str(exc)]) from None
    problems: list[str] = []
    for check in checks:
        if check.ok:
            typer.echo(f"data verify: {check.label}: OK ({check.detail})")
        else:
            problems.extend(f"{check.label}: {p}" for p in check.problems)
    if problems:
        raise _fail("verify", problems)
    typer.echo("data verify: OK")


@app.command()
def synthetic(
    out: Annotated[
        Path,
        typer.Option("--out", help="The directory to write the set under; never inside data/."),
    ],
) -> None:
    """Write the shared synthetic set (never real data) under --out and print the absolute data
    root to use as TRIPARTITE_DATA_DIR."""
    root = out.resolve()
    real = manifest.DATA_DIR.resolve()
    if root.is_relative_to(real):
        raise _fail(
            "synthetic",
            [
                f"--out {out} resolves to {root}, which is inside {real}: that tree holds the "
                "real data, and the synthetic set must never be written there; choose a "
                "directory outside it"
            ],
        )
    try:
        synthetic_set.write_synthetic_data_dir(root)
    except OSError as exc:
        raise _fail("synthetic", [f"cannot write the set under {root}: {exc}"]) from None
    typer.echo(
        f"data synthetic: wrote {synthetic_set.N} synthetic rows to {root / 'raw'}; "
        f"use the path below as {manifest.DATA_DIR_ENV}",
        err=True,
    )
    typer.echo(root)
