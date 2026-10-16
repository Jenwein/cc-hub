# -*- coding: utf-8 -*-
"""cc-hub report: the reports apps add sections to, and the settings and state around them."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import typer

from cc_hub import apps, crontasks, gitops, reportbuild, reports, reportstate
from cc_hub.applock import LockError, load_lock
from cc_hub.console import echo_json, fail, resolve_hub, warn
from cc_hub.reports import PERIODS, ReportError, Section

report_app = typer.Typer(
    no_args_is_help=True,
    help="Reports: daily to yearly digests that apps add sections to.",
)

# OSError includes TimeoutError: a reports state that stays busy is an error like any other
ERRORS = (
    ReportError,
    crontasks.CronError,
    apps.AppError,
    LockError,
    OSError,
    UnicodeDecodeError,
)

UNKNOWN_PERIOD = "unknown period {}; use " + ", ".join(PERIODS[:-1]) + " or " + PERIODS[-1]
SOURCE_HELP = (
    "--from must be a short name made of lowercase letters, digits, - and /, "
    "such as an app or a task (plans/morning); at most 100 characters"
)


def _period(value: str) -> str:
    if value not in PERIODS:
        raise ReportError(UNKNOWN_PERIOD.format(value))
    return value


def _now() -> datetime:
    return datetime.now().astimezone()


def _state_word(on: bool) -> str:
    return "on" if on else "off"


# --- list ---


def _section_row(section: Section, config: reports.ReportConfig, state: dict) -> dict:
    """One section for `report list`; a section whose file cannot be used has only its error."""
    row = {
        "app": section.app,
        "period": section.period,
        "kind": None,
        "title": None,
        "command": None,
        "file": section.file,
        "on": None,
        "approved": None,
        "error": section.error,
    }
    if section.error is not None:
        return row
    row.update(
        kind=section.kind,
        title=section.title,
        command=section.command,
        on=section.key not in config.off,
        approved=(
            reportstate.is_approved(state, section.app, section.period, section.command)
            if section.command is not None
            else None
        ),
    )
    return row


def _overview(hub: Path) -> dict:
    config = reports.load_config(hub)
    on = reports.periods_on(hub)  # also says whether the cron overrides can be read
    tasks = {row["name"]: row for row in crontasks.rows(hub)}
    state = reportstate.load_state(hub)
    periods = []
    for period in PERIODS:
        name = f"report-{period}"
        row = tasks.get(name)
        periods.append(
            {
                "period": period,
                "task": name,
                "schedule": row["schedule"] if row else None,
                "on": on[period],
            }
        )
    sections = [_section_row(s, config, state) for s in reports.discover_sections(hub)]
    return {"language": config.language or "en", "periods": periods, "sections": sections}


def _period_line(row: dict) -> str:
    return f"{row['period']}  {row['task']}  {row['schedule'] or '-'}  {_state_word(row['on'])}"


def _section_line(row: dict) -> str:
    name = f"{row['app']}/{row['period']}" if row["period"] else row["app"]
    if row["error"]:
        return f"{name}  error: {row['error']}"
    line = f"{name}  {row['kind']}  {_state_word(row['on'])}"
    if row["approved"] is not None:
        line += "  approved" if row["approved"] else "  not approved"
    return line


@report_app.command("list")
def list_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List the report of each period (task, time, on or off) and the sections apps add."""
    hub = resolve_hub(ctx)
    try:
        data = _overview(hub)
    except ERRORS as exc:
        fail(exc)
    if as_json:
        echo_json(data)
        return
    for row in data["periods"]:
        typer.echo(_period_line(row))
    for row in data["sections"]:
        typer.echo(_section_line(row))


# --- plan ---


@report_app.command("plan")
def plan_cmd(
    ctx: typer.Context,
    period: str = typer.Argument(..., help="daily, weekly, monthly, quarterly or yearly."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show what the report of a period will hold: its sections, notes and time window."""
    hub = resolve_hub(ctx)
    try:
        plan = reportbuild.plan(hub, _period(period), _now())
    except ERRORS as exc:
        fail(exc)
    if as_json:
        echo_json(plan)
        return
    sections = plan["sections"]
    typer.echo(f"{plan['period']}: {len(sections)} section(s), {plan['notes']} note(s)")
    typer.echo(f"since {plan['since']} until {plan['until']}, language {plan['language']}")
    for section in sections:
        line = f"  {section['app']}  {section['kind']}"
        if section["approved"] is not None:
            line += "  approved" if section["approved"] else "  not approved"
        typer.echo(line)
    if plan["empty"]:
        typer.echo("nothing to send")


# --- put ---


def _check_draft_target(hub: Path, app_name: str, period: str) -> None:
    """ReportError unless `app_name/period` is a section that is on and written by the agent."""
    key = f"{app_name}/{period}"
    config = reports.load_config(hub)
    found = next(
        (s for s in reports.discover_sections(hub) if s.app == app_name and s.period == period),
        None,
    )
    if found is None:
        raise ReportError(f"{app_name} has no {period} report section; see cc-hub report list")
    if found.error is not None:
        raise ReportError(found.error)
    if key in config.off:
        raise ReportError(f"{key} is switched off; see cc-hub report section")
    if found.kind != "instruction":
        raise ReportError(f"{key} is a command section; only instruction sections take a draft")


def _stdin_text() -> str:
    stream = sys.stdin
    if stream is None or stream.isatty():
        raise ReportError("give the text with --text, or pipe it in on stdin")
    data = getattr(stream, "buffer", stream).read()
    return data.decode("utf-8-sig") if isinstance(data, bytes) else data


@report_app.command("put")
def put_cmd(
    ctx: typer.Context,
    period: str = typer.Argument(..., help="daily, weekly, monthly, quarterly or yearly."),
    app_name: str = typer.Argument(..., metavar="APP", help="App whose section the text is for."),
    text: str | None = typer.Option(
        None, "--text", help="The section text (default: read from stdin)."
    ),
) -> None:
    """Store the text an agent wrote for an app's section of the next report of a period."""
    hub = resolve_hub(ctx)
    try:
        period = _period(period)
        _check_draft_target(hub, app_name, period)
        body = text if text is not None else _stdin_text()
        with reportstate.state_lock(hub):
            reportstate.put_draft(hub, period, app_name, body)
    except ERRORS as exc:
        fail(exc)
    typer.echo(f"draft saved for {app_name}/{period}")


# --- send ---


@report_app.command("send")
def send_cmd(
    ctx: typer.Context,
    period: str = typer.Argument(..., help="daily, weekly, monthly, quarterly or yearly."),
    again: bool = typer.Option(
        False, "--again", help="Send even though this report was already sent today."
    ),
) -> None:
    """Build the report of a period and send it to the chat; once a day unless --again."""
    hub = resolve_hub(ctx)
    try:
        period = _period(period)
        result = reportbuild.send(hub, period, _now(), again=again)
        if result.status == "already":
            with reportstate.state_lock(hub):
                reportstate.clear_drafts(hub, period)  # written for a report that is not coming
    except ERRORS as exc:
        fail(exc)  # the library keeps the report out of its errors
    if result.status == "sent":
        typer.echo(f"sent: {result.sections} section(s), {result.notes} note(s)")
        warn(result.warning)
    elif result.status == "empty":
        typer.echo("nothing to send")
    else:
        typer.echo("already sent today; --again sends it once more")


# --- note ---


@report_app.command("note")
def note_cmd(
    ctx: typer.Context,
    period: str = typer.Argument(..., help="daily, weekly, monthly, quarterly or yearly."),
    text: str = typer.Argument(..., help="The note."),
    source: str = typer.Option(
        ..., "--from", help="Who the note is from: an app or task name, e.g. plans/morning."
    ),
) -> None:
    """Keep a note for the next report of a period, or of the next longer one that is on.

    Exit 3 when no report is on: the note is not kept, and the caller replies with it itself.
    """
    hub = resolve_hub(ctx)
    try:
        period = _period(period)
        if not reportbuild.SOURCE_RULE.fullmatch(source):
            raise ReportError(SOURCE_HELP)
        if not text.strip():
            raise ReportError("the note is empty")
        target = reportbuild.add_routed_note(hub, period, source, text, _now())
    except ERRORS as exc:
        fail(exc)  # a busy state is exit 1 too: the note is not kept, the caller replies itself
    if target is None:
        typer.echo("not kept: no report is on; reply with it yourself", err=True)
        raise typer.Exit(code=3)
    typer.echo(f"kept for the {target} report")


# --- section ---


@report_app.command("section")
def section_cmd(
    ctx: typer.Context,
    app_name: str = typer.Argument(..., metavar="APP", help="App that adds the section."),
    period: str = typer.Argument(..., help="daily, weekly, monthly, quarterly or yearly."),
    on: bool = typer.Option(False, "--on", help="Put the section in the report."),
    off: bool = typer.Option(False, "--off", help="Leave the section out of the report."),
) -> None:
    """Switch an app's section of a period's report off or on; saved in hub.toml."""
    hub = resolve_hub(ctx)
    try:
        if on == off:
            raise ReportError("give one of: --on, --off")
        period = _period(period)
        key = f"{app_name}/{period}"
        with apps.hub_lock(hub):
            if off and not any(s.key == key for s in reports.discover_sections(hub)):
                raise ReportError(f"no section {key}; see cc-hub report list")
            reports.save_section(hub, key, on)  # on also clears the table of a removed app
            warning = gitops.commit_paths(hub, ["hub.toml"], f"cc-hub: report section {key}")
    except ERRORS as exc:
        fail(exc)
    warn(warning)
    typer.echo(f"{key}: {_state_word(on)}")


# --- language ---


@report_app.command("language")
def language_cmd(
    ctx: typer.Context,
    tag: str = typer.Argument(..., help='Language tag, such as "en" or "zh-CN".'),
) -> None:
    """Set the language the reports are written in; saved in hub.toml."""
    hub = resolve_hub(ctx)
    try:
        if not reports.LANGUAGE_RULE.fullmatch(tag):
            raise ReportError(f'{tag!r} is not a language tag, such as "en" or "zh-CN"')
        with apps.hub_lock(hub):
            reports.save_language(hub, tag)
            warning = gitops.commit_paths(hub, ["hub.toml"], "cc-hub: report language")
    except ERRORS as exc:
        fail(exc)
    warn(warning)
    typer.echo(f"language: {tag}")


# --- approve ---


@report_app.command("approve")
def approve_cmd(
    ctx: typer.Context,
    app_name: str = typer.Argument(..., metavar="APP", help="Installed app to approve."),
) -> None:
    """Approve the commands in an app's report sections, as they are now, on this machine.

    A section command runs only while it is approved. An approval is for the exact command
    text, so an app that changes a command needs approving again.
    """
    hub = resolve_hub(ctx)
    try:
        if app_name not in load_lock(hub).apps:
            raise ReportError(f"{app_name} is not an installed app; see cc-hub app list")
        commands = {
            s.period: s.command
            for s in reports.discover_sections(hub)
            if s.app == app_name and s.command is not None
        }
        if commands:
            with reportstate.state_lock(hub):
                reportstate.approve(hub, app_name, commands)
    except ERRORS as exc:
        fail(exc)
    if not commands:
        typer.echo("nothing to approve")
        return
    for period in PERIODS:
        if period in commands:
            typer.echo(f"approved: {period}: {commands[period]}")


def register(app: typer.Typer) -> None:
    app.add_typer(report_app, name="report")
