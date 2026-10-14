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
    # A traceback from a hub command must not print hub contents or secrets.
    pretty_exceptions_show_locals=False,
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
    from cc_hub.hub import HubNotFound, find_hub

    try:
        hub: Path | None = find_hub((ctx.obj or {}).get("hub"))
    except HubNotFound as exc:
        hub = None
        typer.echo(str(exc), err=True)
    typer.echo(f"hub: {hub or 'not found'}")
    typer.echo(f"package: {Path(cc_hub.__file__).parent}")
    if hub is None:
        raise typer.Exit(code=1)


from cc_hub.commands import app as _app_cmd  # noqa: E402
from cc_hub.commands import cron as _cron  # noqa: E402
from cc_hub.commands import doctor as _doctor  # noqa: E402
from cc_hub.commands import feedback as _feedback  # noqa: E402
from cc_hub.commands import init as _init  # noqa: E402
from cc_hub.commands import link as _link  # noqa: E402
from cc_hub.commands import memory as _memory  # noqa: E402
from cc_hub.commands import tap as _tap  # noqa: E402
from cc_hub.commands import update as _update  # noqa: E402

_init.register(app)
_doctor.register(app)
_update.register(app)
_memory.register(app)
_link.register(app)
_tap.register(app)
_app_cmd.register(app)
_feedback.register(app)
_cron.register(app)


def main() -> None:
    configure_stdio()
    app()
