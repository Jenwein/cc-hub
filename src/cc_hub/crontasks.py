# -*- coding: utf-8 -*-
"""Scheduled task definitions: the markdown files under cron/ and apps/<app>/cron/."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
        if '"' in command:
            raise CronError(f"{where}: exec must not contain a double quote; use single quotes")
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
