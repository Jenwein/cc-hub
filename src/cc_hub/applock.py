# -*- coding: utf-8 -*-
"""apps.lock: the taps a hub has registered and the apps it has installed."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from cc_hub.encoding import read_text, write_text

LOCK_FILE = "apps.lock"
_HEADER = "# Written by `cc-hub tap` and `cc-hub app`; change it with those commands.\n"


class LockError(Exception):
    pass


@dataclass
class Lock:
    taps: dict[str, dict] = field(default_factory=dict)
    apps: dict[str, dict] = field(default_factory=dict)


def load_lock(hub: Path) -> Lock:
    path = Path(hub) / LOCK_FILE
    if not path.is_file():
        return Lock()
    try:
        data = tomllib.loads(read_text(path))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LockError(f"{LOCK_FILE} unreadable: {exc}") from exc
    return Lock(taps=dict(data.get("taps", {})), apps=dict(data.get("apps", {})))


def save_lock(hub: Path, lock: Lock) -> None:
    text = tomli_w.dumps({"taps": lock.taps, "apps": lock.apps})
    write_text(Path(hub) / LOCK_FILE, _HEADER + text)


def to_tilde(path: Path, *, home: Path | None = None) -> str:
    """`~/...` for a path under the home directory, so the lock works on another machine."""
    path = Path(path).expanduser().absolute()
    home = (home or Path.home()).absolute()
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return path.as_posix()


def from_tilde(text: str, *, home: Path | None = None) -> Path:
    if text == "~" or text.startswith("~/"):
        return (home or Path.home()) / text[2:]
    return Path(text)
