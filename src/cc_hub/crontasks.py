# -*- coding: utf-8 -*-
"""Scheduled task definitions: the markdown files under cron/ and apps/<app>/cron/."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cc_hub.applock import LOCK_FILE, load_lock
from cc_hub.encoding import read_text

SESSIONS = ("reuse", "new_per_run")

FRONTMATTER = re.compile(r"\A---[ \t]*\n(?P<head>.*?)^---[ \t]*$", re.S | re.M)
QUOTED = re.compile(r'"(?P<value>.*?)"\s*(?:#.*)?', re.S)
_CRON_ITEM = r"(?:\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)(?:/[0-9]+)?"
CRON_FIELD = re.compile(rf"{_CRON_ITEM}(?:,{_CRON_ITEM})*")
# the rule for app names (apps.NAME): a task name ends up inside quoted command arguments
TASK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NAME_RULE = (
    "lowercase letters, digits and hyphens, starting with a letter or digit, "
    "at most 64 characters"
)


class CronError(Exception):
    pass


@dataclass(frozen=True)
class TaskDef:
    schedule: str
    default: bool
    session: str


def check_schedule(expr: str) -> str:
    """The expression with its fields single-spaced, or CronError if it is not a 5-field cron."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"schedule {expr.strip()!r} needs five fields: "
            "minute hour day-of-month month day-of-week"
        )
    for field in fields:
        if not CRON_FIELD.fullmatch(field):
            raise CronError(f"schedule {expr.strip()!r}: {field!r} is not a valid cron field")
    return " ".join(fields)


def _value(raw: str, *, key: str, where: str) -> str:
    """A double-quoted value is verbatim (so `#` survives); an unquoted one ends at ` #`."""
    raw = raw.strip()
    if raw.startswith('"'):
        m = QUOTED.fullmatch(raw)
        if m is None:
            raise CronError(
                f"{where}: {key}: the quoted value has no closing quote, "
                "or has text after it that is not a # comment"
            )
        return m.group("value")
    return re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()


def _read(text: str, *, where: str) -> dict[str, str]:
    """The frontmatter as key -> value."""
    m = FRONTMATTER.match(text.replace("\r\n", "\n"))
    if m is None:
        raise CronError(f"{where}: needs a frontmatter block between --- lines")
    fields: dict[str, str] = {}
    for line in m.group("head").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, rest = line.partition(":")
        if sep:
            fields[key.strip()] = _value(rest, key=key.strip(), where=where)
    return fields


read_frontmatter = _read  # for the files that share this format, such as reports/*.md


def parse_task(text: str, *, where: str) -> TaskDef:
    """Read one task definition; CronError (starting with `where`) if it is not valid."""
    fields = _read(text, where=where)
    default = fields.get("default", "false")
    if default not in ("true", "false"):
        raise CronError(f"{where}: default must be true or false, not {default!r}")
    session = fields.get("session", "reuse")
    if session not in SESSIONS:
        raise CronError(f"{where}: session must be reuse or new_per_run, not {session!r}")
    if not fields.get("schedule"):
        raise CronError(f"{where}: schedule is required")
    try:
        schedule = check_schedule(fields["schedule"])
    except CronError as exc:
        raise CronError(f"{where}: {exc}") from None
    return TaskDef(schedule, default == "true", session)


@dataclass
class Task:
    name: str  # a file name without .md for the hub's tasks, <app>/<task> for an app's
    source: str  # "hub", or the app's name
    file: str  # the definition file, relative to the hub, with /
    definition: TaskDef | None
    error: str | None


def _load(name: str, source: str, file: str, path: Path) -> Task:
    """One task; a file that cannot be used becomes a Task with `error`, never an exception."""
    stem = name.rpartition("/")[2]
    if not TASK_NAME.fullmatch(stem):
        return Task(name, source, file, None, f"{file}: task name {stem!r}: use {NAME_RULE}")
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        return Task(name, source, file, None, f"{file}: is not UTF-8")
    except OSError as exc:
        return Task(name, source, file, None, f"{file}: cannot be read: {exc}")
    try:
        return Task(name, source, file, parse_task(text, where=file), None)
    except CronError as exc:
        return Task(name, source, file, None, str(exc))


def _definition_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.is_file() and p.name != "README.md")


def discover(hub: Path) -> list[Task]:
    """The tasks of the hub (cron/*.md) and of every installed app, sorted by name."""
    hub = Path(hub)
    tasks = [
        _load(p.stem, "hub", f"cron/{p.name}", p) for p in _definition_files(hub / "cron")
    ]
    for app in sorted(load_lock(hub).apps):
        if not TASK_NAME.fullmatch(app):
            error = f"{LOCK_FILE}: app name {app!r}: use {NAME_RULE}"
            tasks.append(Task(app, app, LOCK_FILE, None, error))
            continue
        for p in _definition_files(hub / "apps" / app / "cron"):
            tasks.append(_load(f"{app}/{p.stem}", app, f"apps/{app}/cron/{p.name}", p))
    return sorted(tasks, key=lambda t: t.name)


def pointer_prompt(name: str, file: str) -> str:
    """What a task is registered with: a pointer to its definition, not a copy of the body."""
    return f"Scheduled task hub:{name}: follow the body of {file} in the hub."


def registration_command(task: Task, schedule: str | None) -> str | None:
    """The cc-connect command that registers `task` to run at `schedule` (default: its file's).

    Every value goes into a double-quoted argument. That is safe because none can hold what a
    shell acts on inside double quotes: task and app names are checked against a narrow
    pattern, the file path is built from them, and schedules against the cron field pattern.
    The command ends with `--silent`: without it cc-connect posts a line in the chat every
    time the task fires, even when the task replies NO_REPLY.
    """
    d = task.definition
    if d is None:
        return None
    return (
        f'cc-connect cron add --cron "{schedule or d.schedule}" '
        f'--prompt "{pointer_prompt(task.name, task.file)}" '
        f'--session-mode {d.session} --desc "hub:{task.name}" --silent'
    )


def _override_error(name: str, values: dict) -> str | None:
    """Why the override of `name` in hub.toml cannot be used, or None."""
    where = f'hub.toml: [cron."{name}"]'
    if "schedule" in values:
        if not isinstance(values["schedule"], str):
            return f"{where}: schedule must be a text cron expression"
        try:
            check_schedule(values["schedule"])
        except CronError as exc:
            return f"{where}: {exc}"
    if "enabled" in values and not isinstance(values["enabled"], bool):
        return f"{where}: enabled must be true or false"
    return None


def _row(task: Task, override: dict) -> dict:
    row = {
        "name": task.name,
        "source": task.source,
        "file": task.file,
        "default": None,
        "file_schedule": None,
        "schedule": None,
        "overridden": False,
        "enabled": False,
        "session": None,
        "desc": f"hub:{task.name}",
        "prompt": None,
        "command": None,
        "error": task.error,
    }
    d = task.definition
    if d is None:
        return row
    row.update(
        default=d.default,
        file_schedule=d.schedule,
        session=d.session,
        prompt=pointer_prompt(task.name, task.file),
    )
    row["error"] = _override_error(task.name, override)
    if row["error"]:
        return row
    row["overridden"] = "schedule" in override
    row["schedule"] = check_schedule(override["schedule"]) if row["overridden"] else d.schedule
    row["enabled"] = override.get("enabled", d.default)
    row["command"] = registration_command(task, row["schedule"])
    return row


def rows(hub: Path) -> list[dict]:
    """One dict per task: its definition, the overrides applied, and how to register it."""
    from cc_hub import cronoverrides  # here, because cronoverrides imports this module

    try:
        overrides = cronoverrides.load(hub)
    except tomllib.TOMLDecodeError as exc:
        raise CronError(f"hub.toml is not valid TOML: {exc}") from None
    return [_row(task, overrides.get(task.name, {})) for task in discover(hub)]
