# -*- coding: utf-8 -*-
"""Command-line entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from cc_hub import __version__
from cc_hub.encoding import configure_stdio

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


@app.command()
def where(ctx: typer.Context) -> None:
    """Print the hub directory and the package location."""
    import cc_hub
    from cc_hub.console import resolve_hub

    typer.echo(f"hub: {resolve_hub(ctx)}")
    typer.echo(f"package: {Path(cc_hub.__file__).parent}")


from cc_hub.commands import doctor as _doctor  # noqa: E402
from cc_hub.commands import init as _init  # noqa: E402

_init.register(app)
_doctor.register(app)


def main() -> None:
    configure_stdio()
    app()
