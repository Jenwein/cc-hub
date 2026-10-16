# -*- coding: utf-8 -*-
"""cc-hub app: install, set up, update and remove apps from taps."""

from __future__ import annotations

from dataclasses import asdict

import typer

from cc_hub import apps
from cc_hub.console import echo_json, fail, resolve_hub, warn
from cc_hub.crontasks import TaskDef

app_app = typer.Typer(no_args_is_help=True, help="Install and manage apps from taps.")


def _software(reqs: list[apps.Requirement]) -> list[str]:
    return [
        f"  {r.name} ({r.bin}): {r.install_line() or 'no install steps for this platform'}"
        for r in reqs
    ]


def _task_line(name: str, task: TaskDef) -> str:
    choice = "default" if task.default else "optional"
    return f"  {name}: {task.schedule} ({choice}, {task.session})"


def overview(plan: apps.AppPlan) -> list[str]:
    m = plan.manifest
    lines = [f"{m.name} {m.version} from {plan.source.describe()}", m.description]
    lines.append("data dirs: " + (", ".join(m.data_dirs) or "none"))
    lines.append("software:" if m.requires else "software: none")
    lines += _software(m.requires)
    lines.append("scripts: " + (", ".join(plan.scripts) or "none"))
    if plan.crons:
        lines.append("scheduled tasks:")
        for task, cron in sorted(plan.crons.items()):
            lines.append(_task_line(f"hub:{m.name}/{task}", cron))
    else:
        lines.append("scheduled tasks: none")
    lines.append("setup steps: " + ("SETUP.md" if plan.has_setup else "none"))
    lines.append("removal steps: " + ("REMOVE.md" if plan.has_remove else "none"))
    return lines


def _confirm_install(plan: apps.AppPlan, target: str) -> str:
    if isinstance(plan.source, apps.DirSource):
        return f'cc-hub app install "{plan.source.root}" --link --yes'
    return f"cc-hub app install {target} --ref {plan.source.commit} --yes"


def _report(result: apps.InstallResult, hub, verb: str) -> None:
    typer.echo(f"{verb} {result.name} {result.version} ({result.source})")
    if result.seeded:
        typer.echo("seeded: " + ", ".join(result.seeded))
    if result.missing:
        typer.echo("missing software:")
        for line in _software(result.missing):
            typer.echo(line)
    if apps.setup_status(hub, result.name)[0] == "pending":
        typer.echo(f"setup pending: set {result.name} up with the hub-apps skill")
    warn(*result.warnings)


@app_app.command("search")
def search_cmd(
    ctx: typer.Context,
    words: str = typer.Argument("", help="Words to look for in names and descriptions."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List apps in the registered taps (no network)."""
    hub = resolve_hub(ctx)
    try:
        rows = apps.search_apps(hub, words)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    if as_json:
        echo_json(rows)
        return
    if not rows:
        typer.echo("no apps found; register a tap with `cc-hub tap add`")
    for row in rows:
        mark = "  (installed)" if row["installed"] else ""
        typer.echo(f"{row['app']}  {row['version']}  {row['description']}{mark}")


@app_app.command("install")
def install_cmd(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="<tap>/<app>, or a directory with --link."),
    ref: str | None = typer.Option(None, "--ref", help="Commit, tag or branch of the tap."),
    link: bool = typer.Option(False, "--link", help="Link a local app directory."),
    yes: bool = typer.Option(False, "--yes", help="Install; without it only print the overview."),
) -> None:
    """Show what an app brings; with --yes, install it."""
    hub = resolve_hub(ctx)
    try:
        plan = apps.plan_install(hub, target, ref=ref, link=link, fetch=not yes)
        if not yes:
            for line in overview(plan):
                typer.echo(line)
            typer.echo("nothing changed yet; to install run:")
            typer.echo(f"  {_confirm_install(plan, target)}")
            return
        result = apps.install(hub, plan)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    _report(result, hub, "installed")


@app_app.command("list")
def list_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Installed apps: version, source, setup on this machine, missing software."""
    hub = resolve_hub(ctx)
    try:
        rows = apps.app_statuses(hub)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    if as_json:
        echo_json([asdict(row) for row in rows])
        return
    if not rows:
        typer.echo("no apps installed")
    for row in rows:
        setup = row.setup + (f" ({row.note})" if row.note else "")
        typer.echo(f"{row.name}  {row.version}  {row.source}  setup: {setup}")
        if not row.present:
            typer.echo("  missing from apps/: run `cc-hub app sync`")
        for m in row.missing:
            install = m["install"] or "no install steps for this platform"
            typer.echo(f"  needs {m['name']} ({m['bin']}): {install}")
        if row.update:
            typer.echo(f"  update available: cc-hub app update {row.name}")
        if not row.min_hub_ok:
            typer.echo("  needs a newer cc-hub: uv tool upgrade cc-hub")


def _print_preview(p: apps.UpdatePreview) -> None:
    typer.echo(f"{p.name}: {p.old[:7]} -> {p.new[:7]}")
    if p.history_missing:
        typer.echo(f"  installed commit {p.old[:7]} is no longer in the tap; new files listed")
    typer.echo("changed files:")
    for status, path in p.changed:
        typer.echo(f"  {status} {path}")
    if p.new_requires:
        typer.echo("new software: " + ", ".join(p.new_requires))
    if p.local_changes:
        typer.echo("local changes (kept in the backup): " + ", ".join(p.local_changes))
    if p.diff:
        typer.echo("--- app.toml, SETUP.md, REMOVE.md, skills/, scripts/, cron/ ---")
        typer.echo(p.diff.rstrip())
    typer.echo("nothing changed yet; to update run:")
    typer.echo(f"  cc-hub app update {p.name} --ref {p.new} --yes")


def _update_one(hub, name: str, ref: str | None, yes: bool) -> None:
    preview = apps.preview_update(hub, name, ref=ref, fetch=not yes)
    if preview is None:
        typer.echo(f"{name}: linked from a local directory; nothing to update")
    elif preview.old == preview.new or not (preview.changed or preview.history_missing):
        # a tap holds many apps: a commit that leaves this app's files alone is no update
        typer.echo(f"{name} is up to date ({preview.old[:7]})")
    elif not yes:
        _print_preview(preview)
    else:
        _report(apps.apply_update(hub, preview), hub, "updated")


@app_app.command("update")
def update_cmd(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="App to update."),
    every: bool = typer.Option(False, "--all", help="Every app installed from a tap."),
    ref: str | None = typer.Option(None, "--ref", help="Commit, tag or branch of the tap."),
    yes: bool = typer.Option(False, "--yes", help="Update; without it only print the changes."),
) -> None:
    """Show what changed in an app's tap; with --yes, update it."""
    hub = resolve_hub(ctx)
    if bool(name) == every:
        fail("name one app, or pass --all")
    if every and ref:
        fail("--ref needs a single app")
    try:
        names = [name] if name else sorted(apps.load_lock(hub).apps)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    failed = False
    for one in names:
        try:
            _update_one(hub, one, ref, yes)
        except apps.HUB_ERRORS as exc:
            if not every:
                fail(exc)
            typer.echo(f"{one}: {exc}", err=True)
            failed = True
    if failed:
        raise typer.Exit(code=1)


@app_app.command("remove")
def remove_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="App to remove."),
    yes: bool = typer.Option(False, "--yes", help="Remove; without it only print the plan."),
) -> None:
    """Show what removing an app involves; with --yes, remove it. Its data stays."""
    hub = resolve_hub(ctx)
    try:
        plan = apps.plan_remove(hub, name)
        if not yes:
            linked = " (a link; the linked directory stays)" if plan.linked else ""
            typer.echo(f"remove apps/{name}{linked}")
            typer.echo("data kept: " + (", ".join(plan.data_dirs) or "none"))
            typer.echo("scheduled tasks to unregister: " + (", ".join(plan.cron_tasks) or "none"))
            overrides = ", ".join(plan.overrides) + " (removed from hub.toml)"
            typer.echo("overrides: " + (overrides if plan.overrides else "none"))
            typer.echo("software it used: " + (", ".join(r.name for r in plan.software) or "none"))
            if plan.remove_md:
                typer.echo("REMOVE.md:")
                typer.echo(plan.remove_md.rstrip())
            typer.echo("nothing changed yet; to remove run:")
            typer.echo(f"  cc-hub app remove {name} --yes")
            return
        warnings = apps.apply_remove(hub, name)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    typer.echo(f"removed {name}")
    typer.echo("data kept: " + (", ".join(plan.data_dirs) or "none"))
    if plan.cron_tasks:
        typer.echo("unregister if still registered: " + ", ".join(plan.cron_tasks))
    warn(*warnings)


@app_app.command("sync")
def sync_cmd(ctx: typer.Context) -> None:
    """Restore apps/ from apps.lock, for example after cloning the hub."""
    hub = resolve_hub(ctx)
    try:
        report = apps.sync(hub)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    for name in report.restored:
        typer.echo(f"restored\t{name}")
    for name in report.present:
        typer.echo(f"present\t{name}")
    for name in report.strays:
        typer.echo(f"not in apps.lock\t{name}")
    for name, why in report.failed:
        typer.echo(f"failed\t{name}: {why}")
    if report.restored:
        typer.echo("setup pending for restored apps: set them up with the hub-apps skill")
    warn(*report.warnings)
    if report.failed:
        raise typer.Exit(code=1)


@app_app.command("setup-state")
def setup_state_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Installed app."),
    state: str = typer.Argument(..., help="done or waiting"),
    note: str = typer.Option("", "--note", help="What is still left, for waiting."),
) -> None:
    """Record this machine's setup state of an app."""
    hub = resolve_hub(ctx)
    try:
        apps.set_setup_state(hub, name, state, note)
    except apps.HUB_ERRORS as exc:
        fail(exc)
    typer.echo(f"{name}: {state}" + (f" ({note})" if note else ""))


def register(app: typer.Typer) -> None:
    app.add_typer(app_app, name="app")
