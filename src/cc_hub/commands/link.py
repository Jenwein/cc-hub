# -*- coding: utf-8 -*-
"""cc-hub link: link every hub skill into an agent's skills directory."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import typer

from cc_hub.platform import LinkError, is_link, link_dir, link_target, remove_link


def hub_skills(hub: Path) -> dict[str, Path]:
    """Skill name -> resolved directory, for every `skills/<name>/SKILL.md` in the hub."""
    root = Path(hub) / "skills"
    if not root.is_dir():
        return {}
    return {p.name: p.resolve() for p in sorted(root.iterdir()) if (p / "SKILL.md").is_file()}


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


@dataclass
class SkillLinks:
    ok: list[str] = field(default_factory=list)  # entry reaches the hub skill
    missing: list[str] = field(default_factory=list)  # no entry yet
    blocked: list[str] = field(default_factory=list)  # something else has the name
    dangling: list[str] = field(default_factory=list)  # links to skills no longer in the hub


def inspect_skill_links(hub: Path, target: Path) -> SkillLinks:
    """Compare an agent's skills directory with the hub's skills, changing nothing."""
    skills = hub_skills(hub)
    root = (Path(hub) / "skills").resolve()
    state = SkillLinks()
    for name, src in skills.items():
        entry = Path(target) / name
        if not os.path.lexists(entry):
            state.missing.append(name)
        elif _same(entry.resolve(), src):
            state.ok.append(name)
        else:
            state.blocked.append(name)
    if Path(target).is_dir():
        for entry in sorted(Path(target).iterdir()):
            if entry.name in skills or entry.exists() or not is_link(entry):
                continue
            if _same(link_target(entry).parent, root):
                state.dangling.append(entry.name)
    return state


def sync_skill_links(
    hub: Path, target: Path, *, windows: bool | None = None, run=subprocess.run
) -> list[tuple[str, str]]:
    """Link each hub skill into `target` and remove links to skills that are gone.

    Returns (name, status) pairs sorted by name; status is linked, existing,
    removed or blocked. Entries that are not links to hub skills are left alone.
    """
    skills = hub_skills(hub)
    state = inspect_skill_links(hub, target)
    results = [(name, "existing") for name in state.ok]
    results += [(name, "blocked") for name in state.blocked]
    for name in state.missing:
        link_dir(skills[name], Path(target) / name, windows=windows, run=run)
        results.append((name, "linked"))
    for name in state.dangling:
        remove_link(Path(target) / name)
        results.append((name, "removed"))
    return sorted(results)


def register(app: typer.Typer) -> None:
    @app.command("link")
    def link_cmd(
        ctx: typer.Context,
        target: Path = typer.Argument(
            ...,
            help="An agent's skills directory, relative to the hub or absolute "
            "(for example .claude/skills).",
        ),
    ) -> None:
        """Link every skill in skills/ into TARGET, one directory link per skill."""
        from cc_hub.console import fail, resolve_hub

        hub = resolve_hub(ctx)
        target_path = target if target.is_absolute() else hub / target
        try:
            results = sync_skill_links(hub, target_path)
        except LinkError as exc:
            fail(exc)
        for name, status in results:
            typer.echo(f"{status}\t{name}")
        blocked = [name for name, status in results if status == "blocked"]
        if blocked:
            fail(
                f"{', '.join(blocked)}: something else already uses the name in "
                f"{target_path}; remove it and run `cc-hub link` again"
            )
