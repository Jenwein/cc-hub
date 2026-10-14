# -*- coding: utf-8 -*-
"""cc-hub cron: list the scheduled tasks of the hub and its apps."""

from __future__ import annotations

import typer

from cc_hub import crontasks
from cc_hub.applock import LockError
from cc_hub.console import echo_json, fail, resolve_hub

cron_app = typer.Typer(
    no_args_is_help=True,
    help="Scheduled tasks: list, change times, wake on-demand tasks, the restricted-task guard.",
)


def _line(row: dict) -> str:
    if row["error"]:
        return f"{row['name']}  error: {row['error']}"
    when = row["schedule"] or "on demand"
    if row["overridden"]:
        when += f" (overridden, file: {row['file_schedule']})"
    return f"{row['name']}  {row['kind']}  {when}  {'on' if row['enabled'] else 'off'}"


@cron_app.command("list")
def list_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List the scheduled tasks of the hub and its apps, with the times in force."""
    hub = resolve_hub(ctx)
    try:
        rows = crontasks.rows(hub)
    except (crontasks.CronError, LockError, OSError, UnicodeDecodeError) as exc:
        fail(exc)
    if as_json:
        echo_json(rows)
        return
    if not rows:
        typer.echo("no scheduled tasks")
    for row in rows:
        typer.echo(_line(row))


def register(app: typer.Typer) -> None:
    app.add_typer(cron_app, name="cron")
