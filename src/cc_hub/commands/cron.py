# -*- coding: utf-8 -*-
"""cc-hub cron: list the scheduled tasks of the hub and its apps, change their times."""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer

from cc_hub import apps, cronoverrides, crontasks, gitops
from cc_hub.applock import LockError
from cc_hub.cli import ignore_hook_event
from cc_hub.console import echo_json, fail, resolve_hub, warn

cron_app = typer.Typer(
    no_args_is_help=True,
    help="Scheduled tasks: list them, change their times, turn them off or on.",
)


def _line(row: dict) -> str:
    if row["error"]:
        return f"{row['name']}  error: {row['error']}"
    when = row["schedule"]
    if row["overridden"]:
        when += f" (overridden, file: {row['file_schedule']})"
    return f"{row['name']}  {when}  {'on' if row['enabled'] else 'off'}"


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


def reregister_steps(row: dict | None, name: str) -> list[str]:
    """What the agent does next, in a direct chat, to register `name` as the hub now has it.

    `row` is the task's row after the change, or None when the task no longer exists. A task
    that is off, or gone, is only deleted from cc-connect; an enabled one is added again.
    """
    steps = [
        "next, in a direct chat with the user:",
        f"  cc-connect cron list            # find <old id>, the id of hub:{name}, if registered",
        "  cc-connect cron del <old id>",
    ]
    if row is not None and row["enabled"]:
        steps.append(f"  {row['command']}")
    return steps


def _overrides(hub: Path) -> dict[str, dict]:
    try:
        return cronoverrides.load(hub)
    except tomllib.TOMLDecodeError as exc:
        raise crontasks.CronError(f"hub.toml is not valid TOML: {exc}") from None


def _row(hub: Path, name: str) -> dict | None:
    return next((row for row in crontasks.rows(hub) if row["name"] == name), None)


def _finish(hub: Path, name: str, verb: str) -> tuple[str | None, dict | None]:
    """Commit hub.toml (`cc-hub: cron <verb> <name>`), then read the task's row back."""
    warning = gitops.commit_paths(hub, ["hub.toml"], f"cc-hub: cron {verb} {name}")
    return warning, _row(hub, name)


@cron_app.command("set")
def set_cmd(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task name, as `cc-hub cron list` shows it."),
    expr: str | None = typer.Argument(
        None, help='Five-field cron expression, quoted, e.g. "30 2 * * *".'
    ),
    off: bool = typer.Option(False, "--off", help="Turn the task off."),
    on: bool = typer.Option(False, "--on", help="Turn the task on."),
) -> None:
    """Change when a task runs, or turn it on or off; prints the steps to re-register it."""
    hub = resolve_hub(ctx)
    try:
        if (expr is not None) + off + on != 1:
            raise crontasks.CronError("give one of: a cron expression, --off, --on")
        with apps.hub_lock(hub):
            found = next((t for t in crontasks.discover(hub) if t.name == task), None)
            if found is None:
                raise crontasks.CronError(f"no task named {task}; see cc-hub cron list")
            if found.error:
                raise crontasks.CronError(f"cannot change {task}: {found.error}")
            if expr is not None:
                change = {"schedule": crontasks.check_schedule(expr)}
            else:
                change = {"enabled": on}
            values = {**_overrides(hub).get(task, {}), **change}
            cronoverrides.save(hub, task, values)
            warning, row = _finish(hub, task, "set")
    except (crontasks.CronError, apps.AppError, LockError, OSError, UnicodeDecodeError) as exc:
        fail(exc)
    warn(warning)
    for line in reregister_steps(row, task):
        typer.echo(line)


@cron_app.command("reset")
def reset_cmd(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task name, as `cc-hub cron list` shows it."),
) -> None:
    """Drop the override of a task: back to the time its definition file gives."""
    hub = resolve_hub(ctx)
    try:
        with apps.hub_lock(hub):
            if task not in _overrides(hub):
                typer.echo(f"no override for {task}")
                return
            cronoverrides.save(hub, task, None)
            warning, row = _finish(hub, task, "reset")
    except (crontasks.CronError, apps.AppError, LockError, OSError, UnicodeDecodeError) as exc:
        fail(exc)
    warn(warning)
    for line in reregister_steps(row, task):
        typer.echo(line)


@cron_app.command(
    "guard",
    hidden=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def guard_cmd() -> None:
    """PreToolUse hook entry point that never decides anything; settings files may still call it.

    It reads the hook event on stdin, prints nothing and exits 0. A plain `cc-hub cron guard`
    is answered by `cli.main` without loading the command line.
    """
    ignore_hook_event()


def register(app: typer.Typer) -> None:
    app.add_typer(cron_app, name="cron")
