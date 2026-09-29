# -*- coding: utf-8 -*-
"""cc-hub memory: append-only daily logs plus search over them and MEMORY.md."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import typer

from cc_hub.encoding import append_text, read_text
from cc_hub.hub import load_config

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


@dataclass
class Hit:
    file: str
    line_no: int
    line: str
    context: str


def memory_dir(hub: Path) -> Path:
    return Path(hub) / "memory"


def day_file(hub: Path, day: date) -> Path:
    return memory_dir(hub) / f"{day.isoformat()}.md"


def log_entry(hub: Path, text: str, *, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    path = day_file(hub, now.date())
    if not path.exists():
        append_text(path, f"# {now.date().isoformat()}\n\n")
    lines = text.strip().splitlines() or [""]
    body = lines[0] + "".join("\n  " + line for line in lines[1:])
    append_text(path, f"- [{now:%H:%M}] {body}\n")
    return path


def _dated_files(hub: Path, *, days: int | None, today: date) -> list[Path]:
    files: list[Path] = []
    for path in sorted(memory_dir(hub).glob("*.md"), reverse=True):
        match = DATE_RE.match(path.name)
        if not match:
            continue
        day = date.fromisoformat(match.group(1))
        if days is not None and day < today - timedelta(days=days - 1):
            continue
        files.append(path)
    return files


def recent(hub: Path, *, days: int, today: date | None = None) -> list[Path]:
    return _dated_files(hub, days=days, today=today or date.today())


_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _without_comments(text: str) -> str:
    """Blank out HTML comments (template notes, observation dates), keeping line numbers."""
    return _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def search(
    hub: Path,
    query: str,
    *,
    days: int | None = None,
    limit: int = 50,
    regex: bool = False,
    today: date | None = None,
) -> list[Hit]:
    hub = Path(hub)
    today = today or date.today()
    pattern = re.compile(query, re.IGNORECASE) if regex else None
    needle = query.casefold()
    files = [hub / "MEMORY.md", *_dated_files(hub, days=days, today=today)]
    hits: list[Hit] = []
    for path in files:
        if not path.is_file():
            continue
        text = read_text(path)
        lines = text.splitlines()
        searchable = _without_comments(text).splitlines()
        for index, line in enumerate(lines):
            visible = searchable[index] if index < len(searchable) else ""
            matched = bool(pattern.search(visible)) if pattern else needle in visible.casefold()
            if not matched:
                continue
            context = lines[index + 1] if index + 1 < len(lines) else ""
            hits.append(Hit(path.relative_to(hub).as_posix(), index + 1, line, context))
            if len(hits) >= limit:
                return hits
    return hits


memory_app = typer.Typer(no_args_is_help=True,
                          help="Daily logs and long-term memory.")


@memory_app.command("log")
def log_cmd(ctx: typer.Context,
            text: str = typer.Argument(..., help="What to remember.")) -> None:
    """Append a timestamped entry to today's log."""
    from cc_hub.console import resolve_hub

    hub = resolve_hub(ctx)
    path = log_entry(hub, text)
    typer.echo(f"logged to {path.relative_to(hub).as_posix()}")


@memory_app.command("search")
def search_cmd(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Words or regex to look for."),
    days: int | None = typer.Option(None, "--days",
                                     help="Only logs from the last N days."),
    limit: int = typer.Option(50, "--limit"),
    regex: bool = typer.Option(False, "--regex"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search MEMORY.md and the daily logs, newest first."""
    from cc_hub.console import echo_json, fail, resolve_hub

    hub = resolve_hub(ctx)
    try:
        hits = search(hub, query, days=days, limit=limit, regex=regex)
    except re.error as exc:
        fail(f"invalid regex: {exc}")
    if as_json:
        echo_json([asdict(h) for h in hits])
        return
    if not hits:
        typer.echo("no matches")
    for hit in hits:
        typer.echo(f"{hit.file}:{hit.line_no}: {hit.line}")
        if hit.context.strip():
            typer.echo(f"    | {hit.context}")


@memory_app.command("recent")
def recent_cmd(
    ctx: typer.Context,
    days: int | None = typer.Option(
        None, "--days",
        help="Default: memory.recent_days from hub.toml."),
) -> None:
    """Print the last few days of logs (what a session should read first)."""
    from cc_hub.console import resolve_hub

    hub = resolve_hub(ctx)
    days = (days if days is not None else
            int(load_config(hub).get("memory", {}).get("recent_days", 2)))
    files = recent(hub, days=days)
    if not files:
        typer.echo("no memory logs yet")
        return
    for path in files:
        typer.echo(f"## {path.name}")
        typer.echo(read_text(path).rstrip())
        typer.echo("")


def register(app: typer.Typer) -> None:
    app.add_typer(memory_app, name="memory")
