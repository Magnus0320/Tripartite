"""``tripartite api``: serve the API and export its OpenAPI contract (ARCHITECTURE.md D8, D9).

``make api`` runs ``serve``: uvicorn on 127.0.0.1:8000, D8's process model. ``make openapi``
runs ``export-openapi > api-contract/openapi.json``, and CI diffs the same output against the
committed file. The export is deterministic: sorted keys, two-space indent, ASCII with escapes,
and one trailing newline.
"""

import json
from typing import Final

import typer
import uvicorn

from tripartite.api.app import app as api_app

APP_PATH: Final = "tripartite.api.app:app"
HOST: Final = "127.0.0.1"
PORT: Final = 8000

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Serve the API and export its OpenAPI contract."""


def openapi_json() -> str:
    """The OpenAPI document of the API, exactly as ``api-contract/openapi.json`` holds it."""
    return json.dumps(api_app.openapi(), indent=2, sort_keys=True) + "\n"


@app.command()
def serve() -> None:
    """Run the API with uvicorn on 127.0.0.1:8000 (D8)."""
    uvicorn.run(APP_PATH, host=HOST, port=PORT)


@app.command("export-openapi")
def export_openapi() -> None:
    """Print the OpenAPI document to stdout (make openapi writes it to api-contract/)."""
    typer.echo(openapi_json(), nl=False)
