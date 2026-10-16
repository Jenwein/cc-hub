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

from cc_hub.crontasks import CronError, check_schedule
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import HUB_FILE
from cc_hub.tomltables import TableEditError, edit_table

# the keys an override may hold, in the order they are written
KEYS = ("schedule", "enabled")

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

    try:
        # an override holds no tables, so one that has child tables is not ours to rewrite
        return edit_table(text, ("cron", name), clean, allow_children=False)
    except TableEditError:
        raise _refused(name) from None


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
