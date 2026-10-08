# -*- coding: utf-8 -*-
"""cc-hub update: refresh framework-owned files, never user-owned ones."""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
import typer
from rich.table import Table

from cc_hub import __version__, manifest
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import HUB_FILE, load_config


@dataclass
class UpdateResult:
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    backup_dir: Path | None = None
    config_changed: bool = False


class UpdateError(Exception):
    pass


CC_CONNECT_MARKER = "<!-- cc-connect-instructions -->"


def merge_tail(new_text: str, current: str) -> str:
    """Append to `new_text` the part of `current` that belongs to the user and cc-connect.

    That part is everything after manifest.TAIL_MARKER. A file without the marker
    keeps cc-connect's instructions block, from CC_CONNECT_MARKER to the end.
    """
    if manifest.TAIL_MARKER in current:
        tail = current.split(manifest.TAIL_MARKER, 1)[1]
        return new_text + tail.removeprefix("\n")
    if CC_CONNECT_MARKER in current:
        return new_text + "\n" + current[current.index(CC_CONNECT_MARKER):]
    return new_text


def merge_defaults(current: dict, defaults: dict) -> dict:
    """Return a copy of `current` with keys missing from `defaults` added,
    recursively."""
    out = dict(current)
    for key, value in defaults.items():
        if key not in out:
            out[key] = value
        elif isinstance(value, dict) and isinstance(out[key], dict):
            out[key] = merge_defaults(out[key], value)
    return out


_HEADER = re.compile(r"^\s*\[([A-Za-z0-9_.-]+)\]\s*(?:#.*)?$")


def _render_value(value: object) -> str:
    return tomli_w.dumps({"k": value}).split("=", 1)[1].strip()


def _set_value(line: str, key: str, value: object) -> str:
    """Replace a single-line value, keeping indentation and a trailing comment."""
    m = re.match(
        rf'^(\s*{re.escape(key)}\s*=\s*)("(?:[^"\\]|\\.)*"|[^#\s]+)(.*)$', line
    )
    if not m:
        return f"{key} = {_render_value(value)}"
    return m.group(1) + _render_value(value) + m.group(3)


def edit_config_text(text: str, current: dict, merged: dict) -> str:
    """Apply `merged` to hub.toml's text, leaving the user's comments and layout.

    Handles what `update` changes: values of existing keys, keys missing from
    an existing table, and missing tables. Anything that does not round-trip
    to `merged` falls back to a full rewrite.
    """
    lines = text.splitlines()
    headers = {m.group(1): i for i, line in enumerate(lines) if (m := _HEADER.match(line))}
    starts = sorted(headers.values())

    def section_end(start: int) -> int:
        return next((s for s in starts if s > start), len(lines))

    appended: list[str] = []
    inserts: dict[int, list[str]] = {}
    for table, values in merged.items():
        if not isinstance(values, dict) or table not in headers:
            if isinstance(values, dict):
                appended += ["", f"[{table}]"]
                appended += [f"{k} = {_render_value(v)}" for k, v in values.items()]
            continue
        old = current.get(table, {})
        start = headers[table]
        for key, value in values.items():
            if key not in old:
                inserts.setdefault(start, []).append(f"{key} = {_render_value(value)}")
            elif old[key] != value:
                for i in range(start + 1, section_end(start)):
                    if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
                        lines[i] = _set_value(lines[i], key, value)
                        break
    for start in sorted(inserts, reverse=True):
        lines[start + 1 : start + 1] = inserts[start]
    new_text = "\n".join(lines + appended) + "\n"
    try:
        if tomllib.loads(new_text) == merged:
            return new_text
    except tomllib.TOMLDecodeError:
        pass
    return tomli_w.dumps(merged)


def update_hub(
    hub: Path, *, dry_run: bool = False, version: str = __version__
) -> UpdateResult:
    hub = Path(hub)
    cfg = load_config(hub)
    name = str(cfg.get("hub", {}).get("name", hub.name))
    old_version = str(cfg.get("hub", {}).get("template_version", "0"))
    result = UpdateResult()

    plan: list[tuple[str, str, bool]] = []  # (rel, new text, exists)
    for rel in manifest.FRAMEWORK_OWNED:
        dst = hub / rel
        if rel in manifest.ONE_TIME and not dst.exists():
            result.absent.append(rel)
            continue
        new_text = manifest.render(rel, name=name, version=version)
        current = read_text(dst) if dst.is_file() else None
        if current is not None and rel in manifest.KEEPS_TAIL:
            new_text = merge_tail(new_text, current)
        if current == new_text:
            result.skipped.append(rel)
            continue
        plan.append((rel, new_text, current is not None))
    result.retired = [rel for rel in manifest.RETIRED if (hub / rel).is_file()]

    defaults = tomllib.loads(
        manifest.render(manifest.HUB_TOML, name=name, version=version)
    )
    merged = merge_defaults(cfg, defaults)
    merged["hub"]["template_version"] = version
    result.config_changed = merged != cfg
    result.updated = [rel for rel, _, _ in plan]
    if dry_run:
        return result

    backup_dir = hub / ".cc-hub" / "backups" / old_version
    to_back_up = [rel for rel, _, exists in plan if exists] + result.retired
    try:
        for rel in to_back_up:
            bak = backup_dir / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hub / rel, bak)
    except OSError as exc:
        raise UpdateError(
            f"backup failed, nothing was changed: {exc}"
        ) from exc
    for rel, text, _ in plan:
        write_text(hub / rel, text)
    for rel in result.retired:
        (hub / rel).unlink()
        try:
            (hub / rel).parent.rmdir()  # only succeeds once the directory is empty
        except OSError:
            pass
    if result.config_changed:
        config_path = hub / HUB_FILE
        write_text(config_path, edit_config_text(read_text(config_path), cfg, merged))
    if to_back_up:
        result.backup_dir = backup_dir
    return result


def register(app: typer.Typer) -> None:
    @app.command("update")
    def update_cmd(
        ctx: typer.Context,
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Show what would change."
        ),
    ) -> None:
        """Update framework-owned files to this package's templates."""
        from cc_hub.console import console, fail, resolve_hub

        hub = resolve_hub(ctx)
        try:
            result = update_hub(hub, dry_run=dry_run)
        except UpdateError as exc:
            fail(exc)
        table = Table(
            title=f"cc-hub update{' (dry run)' if dry_run else ''}: {hub}"
        )
        table.add_column("file")
        table.add_column("status")
        for rel in result.updated:
            table.add_row(rel, "updated")
        for rel in result.skipped:
            table.add_row(rel, "unchanged")
        for rel in result.absent:
            table.add_row(rel, "not present (one-time)")
        for rel in result.retired:
            table.add_row(rel, "removed (retired)")
        console.print(table)
        if result.backup_dir:
            console.print(
                f"Previous versions backed up to {result.backup_dir}"
            )
        if result.config_changed:
            console.print(
                "hub.toml: new keys merged, template_version updated"
            )
