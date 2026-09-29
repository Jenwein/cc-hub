# -*- coding: utf-8 -*-
"""cc-hub update: refresh framework-owned files, never user-owned ones."""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.table import Table

from cc_hub import __version__, manifest
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import load_config, save_config


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
        if dst.is_file() and read_text(dst) == new_text:
            result.skipped.append(rel)
            continue
        plan.append((rel, new_text, dst.is_file()))
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
        save_config(hub, merged)
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
