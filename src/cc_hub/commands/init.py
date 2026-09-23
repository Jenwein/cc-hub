# -*- coding: utf-8 -*-
"""cc-hub init: seed a hub directory with templates (only missing files are written)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from cc_hub import manifest
from cc_hub.encoding import write_text
from cc_hub.hub import default_hub_dir


@dataclass
class InitResult:
    target: Path
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    git_initialized: bool = False


class NestedGitError(Exception):
    pass


def enclosing_git_repo(path: Path) -> Path | None:
    path = Path(path).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def init_hub(target: Path, *, name: str | None = None, git: bool = True) -> InitResult:
    target = Path(target).expanduser().resolve()
    repo = enclosing_git_repo(target.parent)
    if repo is not None:
        raise NestedGitError(
            f"{target} is inside the git repository {repo}. "
            "A hub must live outside every code repository."
        )
    if (target / ".git").exists() and not (target / "hub.toml").is_file():
        raise NestedGitError(
            f"{target} is the root of the git repository {target}. "
            "A hub must live outside every code repository; "
            "pass an empty directory instead."
        )
    result = InitResult(target=target)
    target.mkdir(parents=True, exist_ok=True)
    for rel in manifest.all_templates():
        dst = target / rel
        if dst.exists():
            result.skipped.append(rel)
            continue
        write_text(dst, manifest.render(rel, name=name or target.name))
        result.created.append(rel)
    for d in manifest.USER_DIRS + manifest.DERIVED_DIRS:
        (target / d).mkdir(exist_ok=True)
    if git and shutil.which("git") and not (target / ".git").exists():
        subprocess.run(["git", "init", "-q", str(target)], check=False, capture_output=True)
        result.git_initialized = (target / ".git").exists()
    return result


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init_cmd(
        directory: Path | None = typer.Argument(
            None, help="Target directory (default: ~/.cc-hub)."
        ),
        name: str | None = typer.Option(None, "--name", help="Hub name written to hub.toml."),
        git: bool = typer.Option(
            True, "--git/--no-git", help="Run `git init` in the new hub."
        ),
    ) -> None:
        """Create a hub directory. Existing files are never overwritten."""
        from cc_hub.console import console, fail

        target = directory or default_hub_dir()
        try:
            result = init_hub(target, name=name, git=git)
        except NestedGitError as exc:
            fail(exc)
        table = Table(title=f"cc-hub init: {result.target}")
        table.add_column("file")
        table.add_column("status")
        for rel in result.created:
            table.add_row(rel, "created")
        for rel in result.skipped:
            table.add_row(rel, "kept")
        console.print(table)
        if result.git_initialized:
            console.print("Initialized a git repository in the hub.")
        console.print(
            "Next: set cc-connect's work_dir to this directory and send the first message; "
            "the agent will follow BOOTSTRAP.md."
        )
        if result.target != default_hub_dir().expanduser().resolve():
            console.print(
                escape(
                    f'This hub is not ~/.cc-hub, so set CC_HUB_DIR = "{result.target}" in '
                    "cc-connect's [projects.agent.options.env] (see docs/cc-connect.md)."
                )
            )
