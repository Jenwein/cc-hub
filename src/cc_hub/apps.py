# -*- coding: utf-8 -*-
"""Apps: app.toml, installing from taps, setup state, update, remove and sync."""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from cc_hub import manifest
from cc_hub.applock import LOCK_FILE

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION = re.compile(r"^\d+(?:\.\d+){0,2}$")
CRON = re.compile(r"^---\n(?P<head>.*?)\n---\n(?P<body>.*)$", re.S)
NAME_RULE = (
    "lowercase letters, digits and hyphens, starting with a letter or digit, "
    "at most 64 characters"
)


class AppError(Exception):
    pass


def check_name(name: str, what: str, *, skill: bool = False) -> str:
    if not NAME.match(name) or (skill and name.startswith("hub-")):
        rule = NAME_RULE + (", not starting with 'hub-'" if skill else "")
        raise AppError(f"{what} {name!r}: use {rule}")
    return name


def version_tuple(text: str) -> tuple[int, int, int]:
    if not VERSION.match(text):
        raise AppError(f"{text!r} is not a version like 0.4.0")
    parts = [int(p) for p in text.split(".")] + [0, 0]
    return (parts[0], parts[1], parts[2])


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


@dataclass
class Requirement:
    name: str
    bin: str
    install: str | dict[str, str] | None = None

    def install_line(self, platform: str | None = None) -> str | None:
        if isinstance(self.install, dict):
            return self.install.get(platform or platform_key())
        return self.install


@dataclass
class AppManifest:
    name: str
    version: str
    description: str
    min_hub: str | None = None
    issues: str | None = None
    data_dirs: list[str] = field(default_factory=list)
    requires: list[Requirement] = field(default_factory=list)


def reserved_names() -> set[str]:
    firsts = {rel.split("/")[0] for rel in manifest.all_templates()}
    extra = {*manifest.USER_DIRS, "apps", LOCK_FILE, "secrets", "CLAUDE.md"}
    return {name.casefold() for name in firsts | extra}


_WINDOWS_DEVICE = re.compile(
    r"\s*(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\s*(?:\.|\Z)", re.IGNORECASE
)


def _windows_unsafe(part: str) -> bool:
    """True for a path part Windows would strip, refuse, or read as a device."""
    return (
        part.endswith((".", " "))
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in part)
        or _WINDOWS_DEVICE.match(part) is not None
    )


def normalize_data_dir(raw: str) -> str:
    path = PurePosixPath(raw)
    parts = raw.split("/")
    if (
        not raw
        or "\\" in raw
        or re.search(r'[:*?"<>|]', raw)
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise AppError(f"data dir {raw!r}: use a relative path inside the hub, with / separators")
    if any(_windows_unsafe(part) for part in parts):
        raise AppError(
            f"data dir {raw!r}: no part may end with a dot or space, hold a control "
            "character, or be a Windows device name"
        )
    first = path.parts[0]
    if first.startswith(".") or first.casefold() in reserved_names():
        raise AppError(f"data dir {raw!r}: {first!r} belongs to the hub itself")
    return path.as_posix()


def _parts(rel: str) -> tuple[str, ...]:
    return PurePosixPath(rel.casefold()).parts


def overlaps(a: str, b: str) -> bool:
    pa, pb = _parts(a), _parts(b)
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]


def inside(rel: str, directory: str) -> bool:
    pr, pd = _parts(rel), _parts(directory)
    return len(pr) > len(pd) and pr[: len(pd)] == pd


def check_entry_path(rel: str) -> None:
    parts = rel.split("/")
    if (
        "\\" in rel
        or ":" in rel
        or any(p in ("", ".", "..") or p.casefold() == ".git" for p in parts)
        or any(_windows_unsafe(p) for p in parts)
    ):
        raise AppError(f"unsafe path in the app: {rel!r}")


PLATFORMS = ("linux", "macos", "windows")


def _install(value: object, *, label: str, where: str) -> str | dict[str, str] | None:
    if value is None:
        return None
    shape = f"{where}: {label}: install must be a non-empty string or a table"
    if isinstance(value, str):
        if not value.strip():
            raise AppError(shape)
        return value.strip()
    if not isinstance(value, dict):
        raise AppError(shape)
    unknown = sorted(set(value) - set(PLATFORMS))
    if unknown:
        raise AppError(
            f"{where}: {label}: install keys must be linux, macos or windows, not {unknown}"
        )
    for key, line in value.items():
        if not isinstance(line, str) or not line.strip():
            raise AppError(f"{where}: {label}: install.{key} must be a non-empty string")
    return {key: line.strip() for key, line in value.items()}


def _requirement(item: object, *, where: str, number: int) -> Requirement:
    if not (
        isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("bin"), str)
    ):
        raise AppError(f"{where}: every [[requires]] needs name and bin")
    name, bin_ = item["name"].strip(), item["bin"].strip()
    label = f"requirement {name!r}" if name else f"requirement #{number}"
    for field_name, value in (("name", name), ("bin", bin_)):
        if not value:
            raise AppError(f"{where}: {label}: {field_name} must not be empty")
    return Requirement(name, bin_, _install(item.get("install"), label=label, where=where))


def parse_manifest(text: str, *, dirname: str) -> AppManifest:
    where = f"{dirname}/app.toml"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AppError(f"{where}: {exc}") from exc
    app = data.get("app")
    if not isinstance(app, dict):
        raise AppError(f"{where}: missing [app] table")
    for key in ("name", "version", "description"):
        if not isinstance(app.get(key), str) or not app[key].strip():
            raise AppError(f"{where}: [app] {key} is required")
    if app["name"] != dirname:
        raise AppError(f"{where}: name {app['name']!r} must equal the directory name {dirname!r}")
    check_name(app["name"], "app name")
    min_hub = app.get("min_hub")
    if min_hub is not None:
        version_tuple(str(min_hub))
    data_table = data.get("data", {})
    if not isinstance(data_table, dict):
        raise AppError(f"{where}: [data] must be a table")
    dirs = data_table.get("dirs", [])
    if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
        raise AppError(f"{where}: [data] dirs must be a list of paths")
    raw_requires = data.get("requires", [])
    if not isinstance(raw_requires, list):
        raise AppError(f"{where}: [[requires]] must be a list of tables")
    requires = [
        _requirement(item, where=where, number=i) for i, item in enumerate(raw_requires, 1)
    ]
    data_dirs = [normalize_data_dir(d) for d in dirs]
    for i, a in enumerate(data_dirs):
        for b in data_dirs[i + 1 :]:
            if overlaps(a, b):
                raise AppError(f"{where}: data dirs {a!r} and {b!r} overlap")
    issues = app.get("issues")
    return AppManifest(
        name=app["name"],
        version=app["version"],
        description=app["description"].strip(),
        min_hub=str(min_hub) if min_hub is not None else None,
        issues=issues if isinstance(issues, str) else None,
        data_dirs=data_dirs,
        requires=requires,
    )


def parse_cron(text: str, *, where: str) -> dict:
    m = CRON.match(text.replace("\r\n", "\n"))
    if not m:
        raise AppError(f"{where}: needs a frontmatter block between --- lines")
    fields: dict[str, str] = {}
    for line in m.group("head").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.split("#", 1)[0].strip().strip('"')
    if not fields.get("schedule"):
        raise AppError(f"{where}: schedule is required")
    return {
        "schedule": fields["schedule"],
        "default": fields.get("default", "false") == "true",
        "session": fields.get("session", "reuse"),
    }
