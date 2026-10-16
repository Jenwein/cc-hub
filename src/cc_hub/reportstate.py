# -*- coding: utf-8 -*-
"""Per-machine report state, kept under `.cc-hub/reports/` (never committed).

- `state.toml`: `[approved.<app>] <period> = "<command>"` is the command text the user approved
  for an app's report section, and `[runs.<period>] last_run, last_sent` are TOML datetimes;
- `notes/<period>.jsonl`: notes waiting for the next report, one JSON object per line;
- `drafts/<period>/<app>.md`: the text an agent wrote for an app's section of one report.

This module only stores; the callers validate periods and app names. It refuses a name that
could point out of its directory.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime
from pathlib import Path

import tomli_w

from cc_hub.encoding import append_text, read_text, write_text
from cc_hub.platform import rmtree

STATE_DIR = ".cc-hub/reports"
STATE_FILE = f"{STATE_DIR}/state.toml"
NOTES_DIR = f"{STATE_DIR}/notes"
DRAFTS_DIR = f"{STATE_DIR}/drafts"


def _name(value: str, what: str) -> str:
    """A single path component: no separators, no `..`, no drive or stream colon."""
    if (
        not isinstance(value, str)
        or value in ("", ".")
        or ".." in value
        or any(c in value for c in "/\\:\0")
    ):
        raise ValueError(f"{what} {value!r} cannot be used as a file name")
    return value


def _table(parent: dict, key: str) -> dict:
    """parent[key] as a table; anything else that stands there is replaced."""
    value = parent.get(key)
    if not isinstance(value, dict):
        value = parent[key] = {}
    return value


# --- state.toml: approvals and runs ---


def load_state(hub: Path) -> dict:
    path = Path(hub) / STATE_FILE
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(read_text(path))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def save_state(hub: Path, state: dict) -> None:
    write_text(Path(hub) / STATE_FILE, tomli_w.dumps(state))


def approve(hub: Path, app: str, commands: dict[str, str]) -> None:
    """Make `commands` (period -> exact command text) the app's approvals, replacing the old."""
    state = load_state(hub)
    approved = _table(state, "approved")
    if commands:
        approved[app] = dict(commands)
    else:
        approved.pop(app, None)
    if not approved:
        del state["approved"]
    save_state(hub, state)


def is_approved(state: dict, app: str, period: str, command: str) -> bool:
    approved = state.get("approved")
    table = approved.get(app) if isinstance(approved, dict) else None
    return isinstance(table, dict) and table.get(period) == command


def forget_app(hub: Path, app: str) -> None:
    """Drop the app's approvals and its drafts, in every period."""
    _name(app, "app")
    state = load_state(hub)
    approved = state.get("approved")
    if isinstance(approved, dict) and app in approved:
        del approved[app]
        if not approved:
            del state["approved"]
        save_state(hub, state)
    drafts = Path(hub) / DRAFTS_DIR
    if not drafts.is_dir():
        return
    for period_dir in drafts.iterdir():
        draft = period_dir / f"{app}.md"
        if draft.is_file():
            draft.unlink()
            try:
                period_dir.rmdir()  # only when no other app has a draft there
            except OSError:
                pass


def record_run(hub: Path, period: str, at: datetime, *, sent: bool) -> None:
    """Note that the `period` report ran at `at`, and that it was sent when `sent`."""
    state = load_state(hub)
    entry = _table(_table(state, "runs"), period)
    entry["last_run"] = at
    if sent:
        entry["last_sent"] = at
    save_state(hub, state)


def _when(state: dict, period: str, key: str) -> datetime | None:
    runs = state.get("runs")
    entry = runs.get(period) if isinstance(runs, dict) else None
    value = entry.get(key) if isinstance(entry, dict) else None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.astimezone()  # a naive one is local


def last_run(state: dict, period: str) -> datetime | None:
    return _when(state, period, "last_run")


def last_sent(state: dict, period: str) -> datetime | None:
    return _when(state, period, "last_sent")


# --- notes ---


def _notes_path(hub: Path, period: str) -> Path:
    return Path(hub) / NOTES_DIR / f"{_name(period, 'period')}.jsonl"


def _note_lines(path: Path) -> list[str]:
    """The non-blank lines of a notes file. A line torn mid-character reads as a bad line."""
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    # split on "\n" only: a note may hold U+2028, U+0085 and the like, which splitlines() cuts at
    return [line for line in text.split("\n") if line.strip()]


def _parse_note(line: str) -> dict | None:
    """The note on a line, or None when the line is not one (also: no text or sender as strings)."""
    try:
        note = json.loads(line)
    except ValueError:
        return None
    if not isinstance(note, dict):
        return None
    if not isinstance(note.get("text"), str) or not isinstance(note.get("from"), str):
        return None
    return note


def add_note(hub: Path, period: str, source: str, text: str, at: datetime) -> None:
    """Append a note, waiting for the next `period` report."""
    path = _notes_path(hub, period)
    line = json.dumps({"at": at.isoformat(), "from": source, "text": text}, ensure_ascii=False)
    append_text(path, ("\n" if _torn(path) else "") + line + "\n")


def _torn(path: Path) -> bool:
    """True when the file does not end in a newline, e.g. a write cut off by a crash."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            if fh.tell() == 0:
                return False
            fh.seek(-1, 2)
            return fh.read(1) != b"\n"
    except OSError:
        return False


def read_notes(hub: Path, period: str) -> list[dict]:
    """The notes waiting for the `period` report, oldest first; bad lines are skipped."""
    notes = (_parse_note(line) for line in _note_lines(_notes_path(hub, period)))
    return [note for note in notes if note is not None]


def drop_notes(hub: Path, period: str, count: int) -> None:
    """Remove the first `count` notes (as read_notes counts them); later ones stay."""
    path = _notes_path(hub, period)
    if count <= 0 or not path.is_file():
        return
    kept: list[str] = []
    dropped = 0
    for line in _note_lines(path):
        if dropped >= count:
            kept.append(line)
        elif _parse_note(line) is not None:
            dropped += 1
        # else: a bad line among the dropped ones goes with them
    if kept:
        write_text(path, "\n".join(kept) + "\n")
    else:
        path.unlink()


# --- drafts ---


def _draft_path(hub: Path, period: str, app: str) -> Path:
    return Path(hub) / DRAFTS_DIR / _name(period, "period") / f"{_name(app, 'app')}.md"


def put_draft(hub: Path, period: str, app: str, text: str) -> None:
    write_text(_draft_path(hub, period, app), text)


def read_draft(hub: Path, period: str, app: str) -> str:
    try:
        return read_text(_draft_path(hub, period, app))
    except (OSError, UnicodeDecodeError):
        return ""


def clear_drafts(hub: Path, period: str) -> None:
    folder = Path(hub) / DRAFTS_DIR / _name(period, "period")
    if folder.is_dir():
        rmtree(folder)
