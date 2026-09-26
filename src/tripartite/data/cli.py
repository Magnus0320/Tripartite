"""``tripartite data``: fetch and verify the pinned data (ARCHITECTURE.md D3, D5, §6).

``make data`` runs ``fetch`` then ``verify``; ``make doctor`` runs ``verify``. Both exit 1 on
any mismatch with the pins, printing the expected and actual values.
"""

import typer

from tripartite.data import download, manifest

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Fetch and verify the pinned dataset files and the sandbox database zip."""


def _fail(command: str, problems: list[str]) -> typer.Exit:
    for problem in problems:
        typer.echo(f"data {command}: {problem}", err=True)
    typer.echo(f"data {command}: FAILED", err=True)
    return typer.Exit(1)


@app.command()
def fetch() -> None:
    """Download validation.csv and validation_ref_info.jsonl at the pinned revision, record or
    check them in data/MANIFEST.json, and check the database zip against the D5 pin."""
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


@app.command()
def verify() -> None:
    """Check data/MANIFEST.json, the dataset files and the database zip against the pins."""
    problems: list[str] = []
    for check in manifest.verify():
        if check.ok:
            typer.echo(f"data verify: {check.label}: OK ({check.detail})")
        else:
            problems.extend(f"{check.label}: {p}" for p in check.problems)
    if problems:
        raise _fail("verify", problems)
    typer.echo("data verify: OK")
