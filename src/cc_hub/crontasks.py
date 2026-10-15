# -*- coding: utf-8 -*-
"""Scheduled task definitions: the markdown files under cron/ and apps/<app>/cron/."""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cc_hub.applock import LOCK_FILE, load_lock
from cc_hub.encoding import read_text

DEFAULT_TIMEOUT_MINS = 10
# cc-connect wants a time even for a task that only runs when woken
PLACEHOLDER_SCHEDULE = "0 0 1 1 *"
SESSIONS = ("reuse", "new_per_run")

FRONTMATTER = re.compile(r"\A---[ \t]*\n(?P<head>.*?)^---[ \t]*$", re.S | re.M)
QUOTED = re.compile(r'"(?P<value>.*?)"\s*(?:#.*)?', re.S)
ITEM = re.compile(r"\s*-(?:\s+(?P<value>.*))?")
_CRON_ITEM = r"(?:\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)(?:/[0-9]+)?"
CRON_FIELD = re.compile(rf"{_CRON_ITEM}(?:,{_CRON_ITEM})*")
POSITIVE_INT = re.compile(r"[0-9]+")
# what a shell reads inside double quotes: `exec` goes into one, so none of these may occur;
# PowerShell, which runs a script task on Windows, also reads typographic double quotes as `"`
UNSAFE_EXEC_CHARS = ('"', "\u201c", "\u201d", "\u201e", "$", "`", "\\")
# the rule for app names (apps.NAME): a task name ends up inside quoted command arguments
TASK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NAME_RULE = (
    "lowercase letters, digits and hyphens, starting with a letter or digit, "
    "at most 64 characters"
)
# a job line of `cc-connect cron list`: enabled mark, id, cron expression, description,
# separated by two spaces (the expression itself holds single spaces)
JOB_LINE = re.compile(r"^\s*\S+\s+(?P<id>\S+)\s{2}(?P<expr>.+?)\s{2}(?P<desc>\S.*?)\s*$")


class CronError(Exception):
    pass


@dataclass(frozen=True)
class TaskDef:
    kind: str  # "prompt" | "exec" | "on_demand"
    schedule: str | None
    default: bool
    session: str | None  # None for exec
    silent: bool
    exec: str | None
    timeout_mins: int | None  # None unless exec
    allow: tuple[str, ...]


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


def _read(text: str, *, where: str) -> tuple[dict[str, str], list[str] | None]:
    """The frontmatter as key -> value, plus the `allow` list (None when there is no allow)."""
    m = FRONTMATTER.match(text.replace("\r\n", "\n"))
    if m is None:
        raise CronError(f"{where}: needs a frontmatter block between --- lines")
    fields: dict[str, str] = {}
    allow: list[str] | None = None
    current: list[str] | None = None  # the allow list while its items are being read
    for line in m.group("head").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        item = ITEM.fullmatch(line) if current is not None else None
        if item is not None:
            current.append(_value(item.group("value") or "", key="allow", where=where))
            continue
        current = None
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        fields[key] = _value(rest, key=key, where=where)
        if key == "allow":
            if fields[key]:
                raise CronError(
                    f"{where}: allow must be a list: one command per line, each starting with '- '"
                )
            allow = current = []
    return fields, allow


def _flag(fields: dict[str, str], key: str, *, where: str) -> bool:
    value = fields.get(key)
    if value is None:
        return False
    if value not in ("true", "false"):
        raise CronError(f"{where}: {key} must be true or false, not {value!r}")
    return value == "true"


def _schedule(expr: str, *, where: str) -> str:
    try:
        return check_schedule(expr)
    except CronError as exc:
        raise CronError(f"{where}: {exc}") from None


def parse_task(text: str, *, where: str) -> TaskDef:
    """Read one task definition; CronError (starting with `where`) if it is not valid."""
    fields, allow = _read(text, where=where)
    default = _flag(fields, "default", where=where)
    silent = _flag(fields, "silent", where=where)
    on_demand = _flag(fields, "on_demand", where=where)
    has_exec = "exec" in fields
    if has_exec and on_demand:
        raise CronError(f"{where}: a task is either a script (exec) or on demand, not both")
    if on_demand and "schedule" in fields:
        raise CronError(f"{where}: an on-demand task has no schedule; remove schedule")

    if has_exec:
        command = fields["exec"]
        if not command.strip():
            raise CronError(f"{where}: exec must not be empty")
        if any(char in command for char in UNSAFE_EXEC_CHARS):
            raise CronError(
                f"{where}: exec must not contain a double quote (also \u201c \u201d \u201e), "
                "$, a backtick or a backslash (a shell would expand them); write a plain "
                "program and arguments, with single quotes for spaces and / in paths"
            )
        if "session" in fields:
            raise CronError(f"{where}: a script task has no session; remove session")
        if allow is not None:
            raise CronError(f"{where}: a script task never goes through an agent; remove allow")
        if not fields.get("schedule"):
            raise CronError(f"{where}: schedule is required")
        timeout = fields.get("timeout_mins", str(DEFAULT_TIMEOUT_MINS))
        if not POSITIVE_INT.fullmatch(timeout) or int(timeout) < 1:
            raise CronError(f"{where}: timeout_mins must be a positive whole number")
        schedule = _schedule(fields["schedule"], where=where)
        return TaskDef("exec", schedule, default, None, silent, command, int(timeout), ())

    if "timeout_mins" in fields:
        raise CronError(f"{where}: timeout_mins only applies to script tasks (those with exec)")
    session = fields.get("session", "reuse")
    if session not in SESSIONS:
        raise CronError(f"{where}: session must be reuse or new_per_run, not {session!r}")
    if allow is not None and (not allow or not all(allow)):
        raise CronError(f"{where}: allow needs at least one command, none of them empty")
    if allow is not None and session != "new_per_run":
        raise CronError(f"{where}: a task with allow needs session: new_per_run")
    restricted = tuple(allow or ())
    if on_demand:
        return TaskDef("on_demand", None, default, session, silent, None, None, restricted)
    if not fields.get("schedule"):
        raise CronError(f"{where}: schedule is required")
    schedule = _schedule(fields["schedule"], where=where)
    return TaskDef("prompt", schedule, default, session, silent, None, None, restricted)


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


def registration_commands(task: Task, schedule: str | None) -> list[str]:
    """The cc-connect commands that register `task` to run at `schedule`.

    Every value goes into a double-quoted argument. That is safe because none can hold what a
    shell acts on inside double quotes: names and schedules are checked against a narrow
    pattern, and `parse_task` rejects a double quote, `$`, a backtick and a backslash in exec.
    `<id>` is the id that `cron add` prints.
    """
    d = task.definition
    if d is None:
        return []
    desc = f'--desc "hub:{task.name}"'
    if d.kind == "exec":
        return [
            f'cc-connect cron add --cron "{schedule or d.schedule}" --exec "{d.exec}" '
            f"--timeout-mins {d.timeout_mins} {desc}",
            "cc-connect cron edit <id> mute true",
        ]
    prompt = pointer_prompt(task.name, task.file)
    on_demand = d.kind == "on_demand"
    cron = PLACEHOLDER_SCHEDULE if on_demand else (schedule or d.schedule)
    silent = " --silent" if on_demand or d.silent else ""
    add = (
        f'cc-connect cron add --cron "{cron}" --prompt "{prompt}" '
        f"--session-mode {d.session}{silent} {desc}"
    )
    return [add, "cc-connect cron edit <id> enabled false"] if on_demand else [add]


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
        "kind": None,
        "default": None,
        "file_schedule": None,
        "schedule": None,
        "overridden": False,
        "enabled": False,
        "session": None,
        "silent": None,
        "exec": None,
        "timeout_mins": None,
        "allow": [],
        "desc": f"hub:{task.name}",
        "prompt": None,
        "commands": [],
        "error": task.error,
    }
    d = task.definition
    if d is None:
        return row
    row.update(
        kind=d.kind,
        default=d.default,
        file_schedule=d.schedule,
        session=d.session,
        # whether it is registered with --silent: always for on demand, and a script is muted
        silent=d.kind == "on_demand" or (d.kind == "prompt" and d.silent),
        exec=d.exec,
        timeout_mins=d.timeout_mins,
        allow=list(d.allow),
        prompt=None if d.kind == "exec" else pointer_prompt(task.name, task.file),
    )
    row["error"] = _override_error(task.name, override)
    if row["error"]:
        return row
    # an on-demand task has no time, so a schedule in its override means nothing
    if d.kind != "on_demand":
        row["overridden"] = "schedule" in override
        row["schedule"] = check_schedule(override["schedule"]) if row["overridden"] else d.schedule
    row["enabled"] = override.get("enabled", d.default)
    row["commands"] = registration_commands(task, row["schedule"])
    return row


def rows(hub: Path) -> list[dict]:
    """One dict per task: its definition, the overrides applied, and how to register it."""
    from cc_hub import cronoverrides  # here, because cronoverrides imports this module

    try:
        overrides = cronoverrides.load(hub)
    except tomllib.TOMLDecodeError as exc:
        raise CronError(f"hub.toml is not valid TOML: {exc}") from None
    return [_row(task, overrides.get(task.name, {})) for task in discover(hub)]


def find_job_id(listing: str, name: str) -> str:
    """The id cc-connect gave `hub:<name>`, read from the output of `cc-connect cron list`."""
    ids = []
    for line in listing.splitlines():
        m = JOB_LINE.match(line)
        if m is not None and m.group("desc") == f"hub:{name}":
            ids.append(m.group("id"))
    if not ids:
        raise CronError(
            f"hub:{name} is not registered in cc-connect; "
            "have the agent register it (hub-adapt, or hub-apps for an app's task)"
        )
    if len(ids) > 1:
        raise CronError(
            f"hub:{name} is registered more than once in cc-connect (ids {', '.join(ids)}); "
            "delete the extras with cc-connect cron del <id>"
        )
    return ids[0]


WAKE_TIMEOUT_SECS = 60


def _cc_connect(run, cc: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return run(
            [cc, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=WAKE_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        raise CronError(
            f"cc-connect {' '.join(args)} did not answer within {WAKE_TIMEOUT_SECS} seconds; "
            "check that cc-connect is running and responsive"
        ) from None
    except OSError as exc:
        raise CronError(f"cannot run cc-connect: {exc}") from None


def _detail(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or proc.stdout or "").strip()
    return f": {text}" if text else ""


def wake(hub: Path, name: str, *, which=shutil.which, run=subprocess.run) -> str:
    """Trigger the on-demand task `name` in cc-connect; returns the job id it was run by.

    Success means cc-connect took the job, not that the agent has finished it.
    """
    row = next((r for r in rows(hub) if r["name"] == name), None)
    if row is None:
        raise CronError(f"no task named {name}; see cc-hub cron list")
    if row["error"]:
        raise CronError(f"cannot wake {name}: {row['error']}")
    if row["kind"] != "on_demand":
        raise CronError(f"{name} is not an on-demand task, so it cannot be woken")
    if not row["enabled"]:
        raise CronError(f"hub:{name} is turned off; cc-hub cron set {name} --on")
    cc = which("cc-connect")
    if cc is None:
        raise CronError("cc-connect not found on PATH")
    listed = _cc_connect(run, cc, "cron", "list")
    if listed.returncode != 0:
        raise CronError(
            f"cc-connect cron list failed (exit {listed.returncode}); "
            f"cc-connect is probably not running{_detail(listed)}"
        )
    job = find_job_id(listed.stdout or "", name)
    woken = _cc_connect(run, cc, "cron", "exec", job)
    if woken.returncode != 0:
        raise CronError(
            f"cc-connect cron exec {job} failed (exit {woken.returncode}){_detail(woken)}"
        )
    return job
