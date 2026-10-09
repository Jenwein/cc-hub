# -*- coding: utf-8 -*-
"""cc-hub tap: register git repositories that hold apps."""

from __future__ import annotations

import typer

from cc_hub import apps, taps
from cc_hub.console import echo_json, fail, resolve_hub, warn

tap_app = typer.Typer(no_args_is_help=True, help="Register git repositories of apps (taps).")


@tap_app.command("add")
def add_cmd(
    ctx: typer.Context,
    source: str = typer.Argument(
        ..., help="Git URL, owner/repo on GitHub, or a local git repository."
    ),
    name: str | None = typer.Option(None, "--name", help="Tap name (default: repository name)."),
) -> None:
    """Register a tap; a remote one is cloned into .cc-hub/taps/."""
    hub = resolve_hub(ctx)
    try:
        name, entry, count, warning = apps.add_tap(hub, source, name=name)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    plural = "" if count == 1 else "s"
    typer.echo(f"added tap {name}: {taps.describe(entry)} ({count} app{plural})")
    typer.echo("next: cc-hub app search")
    warn(warning)


@tap_app.command("list")
def list_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List registered taps."""
    hub = resolve_hub(ctx)
    try:
        rows = apps.tap_infos(hub)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    if as_json:
        echo_json(rows)
        return
    if not rows:
        typer.echo("no taps; add one with `cc-hub tap add <owner>/<repo>`")
    for row in rows:
        typer.echo(f"{row['name']}  {row['source']}  {row['apps']} apps")


@tap_app.command("remove")
def remove_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="Tap name.")) -> None:
    """Forget a tap that no installed app comes from."""
    hub = resolve_hub(ctx)
    try:
        warning = apps.remove_tap(hub, name)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    typer.echo(f"removed tap {name}")
    warn(warning)


def register(app: typer.Typer) -> None:
    app.add_typer(tap_app, name="tap")
