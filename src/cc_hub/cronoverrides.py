# -*- coding: utf-8 -*-
"""Time overrides for scheduled tasks: the [cron."<task>"] tables in hub.toml.

hub.toml belongs to the user, so a change is a text edit of one table that leaves every other
byte alone, line endings included. An edit that would not parse back to exactly the intended
data is refused instead of guessed at.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import tomli_w

from cc_hub.crontasks import CronError, check_schedule
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import HUB_FILE

# the keys an override may hold, in the order they are written
KEYS = ("schedule", "enabled")

HEADER = re.compile(
    r'^\s*\[\s*cron\s*\.\s*(?:"(?P<q>[^"]+)"|(?P<b>[A-Za-z0-9_-]+))\s*\](?:\s*#.*)?$'
)
# a line with its own ending, so that rejoining the lines gives the text back unchanged
LINE = re.compile(r"[^\n]*\n|[^\n]+")
UNUSABLE_NAME = re.compile(r'[\x00-\x1f\x7f"\\]')


def _refused(name: str) -> CronError:
    return CronError(f'hub.toml: cannot edit [cron."{name}"] in place; edit it by hand')


def _clean(name: str, values: dict) -> dict:
    """The values to store: a known key each, the schedule checked and single-spaced."""
    for key in values:
        if key not in KEYS:
            raise CronError(f'[cron."{name}"]: {key!r} is not an override key (schedule, enabled)')
    clean = {}
    if "schedule" in values:
        if not isinstance(values["schedule"], str):
            raise CronError(f'[cron."{name}"]: schedule must be a text cron expression')
        clean["schedule"] = check_schedule(values["schedule"])
    if "enabled" in values:
        if not isinstance(values["enabled"], bool):
            raise CronError(f'[cron."{name}"]: enabled must be true or false')
        clean["enabled"] = values["enabled"]
    return clean


def _find(lines: list[str], name: str) -> tuple[int, int] | None:
    """Line range [start, end) of the table headed `[cron."<name>"]`, or None."""
    for start, line in enumerate(lines):
        m = HEADER.match(line.rstrip("\r\n"))
        if m is not None and (m.group("q") or m.group("b")) == name:
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
                len(lines),
            )
            return start, end
    return None


def apply(text: str, name: str, values: dict | None) -> str:
    """`text` with the override of task `name` set to `values`, or removed when None.

    Only that table changes. CronError when `values` is not a valid override, or when the
    result would not parse to the same data apart from this one override.
    """
    if not name or UNUSABLE_NAME.search(name):
        raise CronError(f"{name!r} is not a usable task name")
    clean = None if values is None else _clean(name, values)
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CronError(f"hub.toml is not valid TOML: {exc}") from None
    old_cron = before.get("cron", {})
    if not isinstance(old_cron, dict):
        raise _refused(name)

    lines = LINE.findall(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    body = [
        tomli_w.dumps({key: clean[key]}).rstrip("\n") + eol
        for key in KEYS
        if clean is not None and key in clean
    ]
    span = _find(lines, name)
    if span is None:
        if clean is not None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += eol
            if lines and lines[-1].strip():
                lines.append(eol)
            lines += [f'[cron."{name}"]{eol}', *body]
    else:
        start, end = span
        last = end  # one past the table's last line that is not blank
        while last > start + 1 and not lines[last - 1].strip():
            last -= 1
        if clean is None:
            # a table at the end of the file takes its trailing blank lines with it
            stop = len(lines) if end == len(lines) else last
            first = start - 1 if start > 0 and not lines[start - 1].strip() else start
            del lines[first:stop]
        else:
            if not lines[start].endswith("\n"):
                lines[start] += eol
            lines[start + 1 : last] = body

    new_text = "".join(lines)
    cron = dict(old_cron)
    if clean is None:
        cron.pop(name, None)
    else:
        cron[name] = clean
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        raise _refused(name) from None
    others = {k: v for k, v in before.items() if k != "cron"}
    if {k: v for k, v in after.items() if k != "cron"} != others or after.get("cron", {}) != cron:
        raise _refused(name)
    return new_text


def load(hub: Path) -> dict[str, dict]:
    """Every override in hub.toml, by task name; {} when there is no [cron] table."""
    cron = tomllib.loads(read_text(Path(hub) / HUB_FILE)).get("cron", {})
    if not isinstance(cron, dict) or not all(isinstance(v, dict) for v in cron.values()):
        raise CronError('hub.toml: [cron] holds one [cron."<task>"] table per task, nothing else')
    return {name: dict(values) for name, values in cron.items()}


def save(hub: Path, name: str, values: dict | None) -> None:
    """Set (or, with None, remove) one override in hub.toml."""
    path = Path(hub) / HUB_FILE
    # read_text would turn CRLF into LF; write_text writes the text it is given as it is
    old = path.read_bytes().decode("utf-8")
    new = apply(old, name, values)
    if new != old:
        write_text(path, new)
