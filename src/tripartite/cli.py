"""Tripartite command line (ARCHITECTURE.md D9).

Sub-apps are registered lazily by module path. Each name below is a thin proxy command that
imports its module only when invoked and hands it the remaining arguments, so the root
imports and runs even while a later milestone's module does not exist yet. Invoking a sub-app
whose module is missing exits 1 with a message that names the module.
"""

import importlib
from typing import Final

import typer

SUBCOMMANDS: Final[dict[str, str]] = {
    "data": "tripartite.data.cli:app",
    "eval": "tripartite.evaluation.cli:app",
    "model": "tripartite.llm.cli:app",
    "run": "tripartite.pipeline.cli:app",
    "log": "tripartite.runlog.cli:app",
    "api": "tripartite.api.cli:app",
}

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Tripartite: TravelPlanner sole-planning baseline (see ARCHITECTURE.md)."""


def _load(name: str, target: str) -> typer.Typer:
    module_name, _, attr = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        # Only the sub-app's own module (or a parent package) counts as "not built yet";
        # any other missing import inside an existing module is a real error.
        missing = exc.name
        if missing is None or not (module_name == missing or module_name.startswith(missing + ".")):
            raise
        typer.echo(
            f"Error: 'tripartite {name}' is not available yet: {module_name} does not exist",
            err=True,
        )
        raise typer.Exit(1) from None
    sub_app = getattr(module, attr)
    if not isinstance(sub_app, typer.Typer):
        raise TypeError(f"{target} is not a typer.Typer")
    return sub_app


def _register(name: str, target: str) -> None:
    @app.command(
        name,
        help=f"Commands from {target.partition(':')[0]} (loaded on first use).",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        add_help_option=False,
    )
    def proxy(ctx: typer.Context) -> None:
        prog = f"{ctx.find_root().info_name or 'tripartite'} {name}"
        _load(name, target)(args=ctx.args, prog_name=prog)


for _name, _target in SUBCOMMANDS.items():
    _register(_name, _target)
