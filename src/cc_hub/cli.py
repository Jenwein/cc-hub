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
    from cc_hub.console import resolve_hub

    typer.echo(f"hub: {resolve_hub(ctx)}")
    typer.echo(f"package: {Path(cc_hub.__file__).parent}")


from cc_hub.commands import doctor as _doctor  # noqa: E402
from cc_hub.commands import env as _env  # noqa: E402
from cc_hub.commands import hook as _hook  # noqa: E402
from cc_hub.commands import hosts as _hosts  # noqa: E402
from cc_hub.commands import init as _init  # noqa: E402
from cc_hub.commands import jobs as _jobs  # noqa: E402
from cc_hub.commands import link as _link  # noqa: E402
from cc_hub.commands import memory as _memory  # noqa: E402
from cc_hub.commands import projects as _projects  # noqa: E402
from cc_hub.commands import update as _update  # noqa: E402

_init.register(app)
_doctor.register(app)
_update.register(app)
_env.register(app)
_memory.register(app)
_projects.register(app)
_jobs.register(app)
_link.register(app)
_hook.register(app)
_hosts.register(app)


def main() -> None:
    configure_stdio()
    app()
