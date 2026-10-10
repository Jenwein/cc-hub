# -*- coding: utf-8 -*-
"""Locate the hub directory and read/write hub.toml."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

import tomli_w

from cc_hub.encoding import read_text, write_text

HUB_FILE = "hub.toml"
ENV_VAR = "CC_HUB_DIR"


class HubNotFound(Exception):
    def __init__(self) -> None:
        super().__init__(
            "No hub found. Tried: --hub, $CC_HUB_DIR, hub.toml in the current directory "
            "or any parent, and ~/.cc-hub. Run `cc-hub init` to create one."
        )


def default_hub_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".cc-hub"


def is_hub(path: Path) -> bool:
    return (Path(path) / HUB_FILE).is_file()


def find_hub(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if env is None else env
    given: Path | None = None
    if explicit is not None:
        given = Path(explicit).expanduser()
    elif env.get(ENV_VAR):
        given = Path(env[ENV_VAR]).expanduser()
    if given is not None:
        if is_hub(given):
            return given.resolve()
        raise HubNotFound()
    start = (cwd or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if is_hub(candidate):
            return candidate
    default = default_hub_dir(home)
    if is_hub(default):
        return default.resolve()
    raise HubNotFound()


def load_config(hub: Path) -> dict:
    return tomllib.loads(read_text(Path(hub) / HUB_FILE))


def hub_name(hub: Path) -> str:
    """hub.toml's [hub] name; the directory name when hub.toml says nothing usable."""
    hub = Path(hub)
    try:
        name = load_config(hub).get("hub", {}).get("name")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        name = None
    return str(name) if name else hub.name


def save_config(hub: Path, data: Mapping) -> None:
    write_text(Path(hub) / HUB_FILE, tomli_w.dumps(dict(data)))
