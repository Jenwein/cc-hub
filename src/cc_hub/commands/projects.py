# -*- coding: utf-8 -*-
"""cc-hub projects: registry of local project directories (projects.toml)."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

import tomli_w
import typer

from cc_hub.console import fail
from cc_hub.encoding import read_text, write_text

HEADER = "# Registered local projects. Managed by `cc-hub projects add|remove`.\n\n"


class ProjectError(Exception):
    pass


def load_projects(hub: Path) -> list[dict]:
    path = Path(hub) / "projects.toml"
    if not path.is_file():
        return []
    return list(tomllib.loads(read_text(path)).get("project", []))


def save_projects(hub: Path, projects: list[dict]) -> None:
    write_text(
        Path(hub) / "projects.toml",
        HEADER + tomli_w.dumps({"project": projects}),
    )


def portable_path(path: Path, home: Path | None = None) -> str:
    resolved = Path(path).resolve()
    home = (home or Path.home()).resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return str(resolved)


def get_project(hub: Path, name: str) -> dict:
    for proj in load_projects(hub):
        if proj.get("name") == name:
            return proj
    raise ProjectError(f"no project named '{name}'")


def add_project(
    hub: Path,
    path: str | Path,
    *,
    name: str | None = None,
    description: str = "",
    notes: str = "",
    today: date | None = None,
    home: Path | None = None,
) -> dict:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ProjectError(f"{target} is not a directory")
    projects = load_projects(hub)
    for proj in projects:
        if (
            Path(str(proj.get("path", ""))).expanduser().resolve()
            == target
        ):
            raise ProjectError(
                f"{target} is already registered as '{proj.get('name')}'"
            )
    name = name or target.name
    if any(p.get("name") == name for p in projects):
        raise ProjectError(f"name '{name}' is already used; pass --name")
    entry = {
        "name": name,
        "path": portable_path(target, home),
        "description": description,
        "notes": notes,
        "added": today or date.today(),
    }
    projects.append(entry)
    save_projects(hub, projects)
    return entry


def remove_project(hub: Path, name: str) -> dict:
    projects = load_projects(hub)
    keep = [p for p in projects if p.get("name") != name]
    if len(keep) == len(projects):
        raise ProjectError(f"no project named '{name}'")
    save_projects(hub, keep)
    return next(p for p in projects if p.get("name") == name)


projects_app = typer.Typer(
    no_args_is_help=True,
    help="Registry of local project directories.",
)


@projects_app.command("list")
def list_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List registered projects."""
    from cc_hub.console import echo_json, resolve_hub

    projects = load_projects(resolve_hub(ctx))
    if as_json:
        echo_json(projects)
        return
    if not projects:
        typer.echo(
            "no projects registered; use `cc-hub projects add <path>`"
        )
        return
    for p in projects:
        desc = f"  {p.get('description')}" if p.get("description") else ""
        typer.echo(f"{p.get('name')}\t{p.get('path')}{desc}")


@projects_app.command("show")
def show_cmd(
    ctx: typer.Context,
    name: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show one project."""
    from cc_hub.console import echo_json, resolve_hub

    try:
        proj = get_project(resolve_hub(ctx), name)
    except ProjectError as exc:
        fail(exc)
    if as_json:
        echo_json(proj)
        return
    for key, value in proj.items():
        typer.echo(f"{key}: {value}")


@projects_app.command("add")
def add_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Project directory."),
    name: str | None = typer.Option(None, "--name"),
    description: str = typer.Option("", "--description"),
    notes: str = typer.Option("", "--notes", help="How to run/test it, quirks."),
) -> None:
    """Register a project directory."""
    from cc_hub.console import resolve_hub

    try:
        entry = add_project(
            resolve_hub(ctx),
            path,
            name=name,
            description=description,
            notes=notes,
        )
    except ProjectError as exc:
        fail(exc)
    typer.echo(f"registered {entry['name']} -> {entry['path']}")


@projects_app.command("remove")
def remove_cmd(ctx: typer.Context, name: str) -> None:
    """Remove a project from the registry (the directory is untouched)."""
    from cc_hub.console import resolve_hub

    try:
        remove_project(resolve_hub(ctx), name)
    except ProjectError as exc:
        fail(exc)
    typer.echo(f"removed {name}")


def register(app: typer.Typer) -> None:
    app.add_typer(projects_app, name="projects")
