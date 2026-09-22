# -*- coding: utf-8 -*-
"""Command-line entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from cc_hub import __version__

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Hub directory tool for agents launched by cc-connect.",
)


@app.callback()
def _root(
    ctx: typer.Context,
    hub: Path | None = typer.Option(
        None,
        "--hub",
        envvar="CC_HUB_DIR",
        help="Hub directory (default: search upward from cwd, then ~/.cc-hub).",
    ),
) -> None:
    ctx.obj = {"hub": hub}


@app.command()
def version() -> None:
    """Print the cc-hub version."""
    typer.echo(__version__)


def main() -> None:
    app()
