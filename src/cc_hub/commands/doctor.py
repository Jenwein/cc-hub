# -*- coding: utf-8 -*-
"""cc-hub doctor: health checks for a hub directory."""

from __future__ import annotations

import os
import re
import shutil
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from cc_hub import __version__, gitops, manifest
from cc_hub.applock import LockError, from_tilde, load_lock
from cc_hub.apps import app_statuses
from cc_hub.commands.init import enclosing_git_repo
from cc_hub.commands.link import POINTERS, inspect_skill_links
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import load_config

Which = Callable[[str], "str | None"]


@dataclass
class Check:
    id: str
    status: str  # ok | warn | fail
    message: str
    fix: str = ""


DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
AGENT_MARKERS = {"claude": ("claude", ".claude"), "codex": ("codex", ".codex")}
IMPORT_LINE = "@AGENTS.md"
_READ_ERRORS = (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError)


def detect_agents(*, home: Path, which: Which) -> list[str]:
    return [a for a, (exe, dot) in AGENT_MARKERS.items() if which(exe) or (home / dot).exists()]


def _ok(id_: str, message: str) -> Check:
    return Check(id_, "ok", message)


def git_check(hub: Path) -> Check:
    if not gitops.git_available() or not (hub / ".git").exists():
        return Check(
            "git",
            "warn",
            "the hub is not a git repository: no history and no backup",
            f'install git, then run `cc-hub init "{hub}"`',
        )
    problems = []
    if not gitops.has_identity(hub):
        problems.append("no git identity (user.name, user.email)")
    n = gitops.uncommitted(hub)
    if n:
        problems.append(f"{n} uncommitted change(s)")
    names = gitops.remotes(hub)
    if not names:
        problems.append("no remote: the hub is not backed up")
    if problems:
        return Check(
            "git",
            "warn",
            "; ".join(problems),
            "the agent commits after each task; docs/backup.md sets up a private remote",
        )
    return _ok("git", "committed; remote: " + ", ".join(names))


def apps_check(hub: Path, which: Which) -> Check:
    try:
        rows = app_statuses(hub, which=which)
        entries = load_lock(hub).apps
    except LockError as exc:
        return Check("apps", "fail", str(exc), "fix apps.lock, or restore it with git")
    if not rows:
        return _ok("apps", "no apps installed")
    problems: list[str] = []
    fixes: list[str] = []
    for row in rows:
        if not row.present:
            entry = entries.get(row.name, {})
            if "link" in entry and not from_tilde(entry["link"]).is_dir():
                problems.append(f"{row.name}: link source {entry['link']} does not exist")
                fixes.append(f"restore that directory, or run `cc-hub app remove {row.name} --yes`")
            elif not os.path.lexists(hub / "apps" / row.name):
                problems.append(f"{row.name}: missing from apps/")
                fixes.append("run `cc-hub app sync`")
            else:
                problems.append(f"{row.name}: app.toml in apps/{row.name} is unreadable")
                fixes.append(f"run `cc-hub app remove {row.name} --yes`, then install it again")
            continue
        if not row.min_hub_ok:
            problems.append(f"{row.name}: needs a newer cc-hub")
            fixes.append("run `uv tool upgrade cc-hub`")
        for m in row.missing:
            install = m["install"] or "no install steps for this platform"
            problems.append(f"{row.name}: needs {m['bin']} ({install})")
        if row.setup == "pending":
            problems.append(f"{row.name}: setup pending")
        elif row.setup == "waiting":
            problems.append(f"{row.name}: setup waiting ({row.note})")
        if row.missing or row.setup != "done":
            fixes.append("ask the agent to set the app up (hub-apps skill)")
    if problems:
        return Check("apps", "warn", "; ".join(problems), "; ".join(dict.fromkeys(fixes)))
    return _ok("apps", f"{len(rows)} app(s) set up")


def run_checks(
    hub: Path,
    *,
    fix: bool = False,
    home: Path | None = None,
    which: Which = shutil.which,
    package_version: str = __version__,
) -> list[Check]:
    hub = Path(hub)
    home = home or Path.home()
    checks: list[Check] = []

    # hub-toml
    cfg: dict = {}
    try:
        cfg = load_config(hub)
        tv = str(cfg.get("hub", {}).get("template_version", "0"))
        if tv == package_version:
            checks.append(_ok("hub-toml", f"template_version {tv}"))
        else:
            checks.append(
                Check(
                    "hub-toml",
                    "warn",
                    f"template_version {tv}, package is {package_version}",
                    "run `cc-hub update` (read the migration notes in CHANGELOG.md first)",
                )
            )
    except _READ_ERRORS as exc:
        checks.append(
            Check("hub-toml", "fail", f"hub.toml unreadable: {exc}", "fix the TOML syntax")
        )
    name = str(cfg.get("hub", {}).get("name", hub.name))

    # required-files (fix: user files and .gitignore only)
    if fix:
        restored = [".gitignore"]
        write_text(
            hub / ".gitignore", manifest.render(".gitignore", name=name, version=package_version)
        )
        for d in manifest.USER_DIRS:
            (hub / d).mkdir(exist_ok=True)
        for rel in manifest.USER_OWNED:
            if not (hub / rel).is_file():
                write_text(hub / rel, manifest.render(rel, name=name, version=package_version))
                restored.append(rel)
        gitops.commit_paths(hub, restored, "cc-hub: doctor --fix")
    missing = [
        rel
        for rel in manifest.FRAMEWORK_OWNED + manifest.USER_OWNED
        if rel not in manifest.ONE_TIME and not (hub / rel).is_file()
    ]
    if missing:
        checks.append(
            Check(
                "required-files",
                "fail",
                "missing: " + ", ".join(missing),
                "`cc-hub doctor --fix` restores user files; "
                "`cc-hub update` restores framework files",
            )
        )
    else:
        checks.append(_ok("required-files", "all present"))

    # bootstrap-pending
    if (hub / "BOOTSTRAP.md").exists():
        checks.append(
            Check(
                "bootstrap-pending",
                "warn",
                "BOOTSTRAP.md still present: first-run ritual not completed",
                "send the agent its first message",
            )
        )
    else:
        checks.append(_ok("bootstrap-pending", "bootstrap completed"))

    # memory-budget
    max_lines = int(cfg.get("memory", {}).get("max_lines", 200))
    for rel, limit in (("MEMORY.md", max_lines), ("USER.md", 100)):
        p = hub / rel
        if not p.is_file():
            continue
        try:
            n = len(read_text(p).splitlines())
        except _READ_ERRORS as exc:
            checks.append(
                Check(
                    f"memory-budget:{rel}",
                    "fail",
                    f"unreadable: {exc}",
                    "fix the file's permissions or re-save it as UTF-8",
                )
            )
            continue
        if n <= limit:
            checks.append(_ok(f"memory-budget:{rel}", f"{n}/{limit} lines"))
        else:
            checks.append(
                Check(
                    f"memory-budget:{rel}",
                    "fail",
                    f"{n}/{limit} lines",
                    "run the consolidation procedure from the hub-memory skill",
                )
            )

    # memory-files
    mem = hub / "memory"
    bad = [p.name for p in mem.glob("*.md") if not DATE_NAME.match(p.name)] if mem.is_dir() else []
    if bad:
        checks.append(
            Check(
                "memory-files",
                "warn",
                "unexpected names: " + ", ".join(bad),
                "rename to YYYY-MM-DD.md",
            )
        )
    else:
        checks.append(_ok("memory-files", "names ok"))

    # pointers
    agents = detect_agents(home=home, which=which)
    if not agents:
        checks.append(_ok("pointers", "no agent runtimes detected on this machine"))
    for agent in agents:
        instructions, skills_dir = POINTERS[agent]
        if not any((hub / rel).exists() for rel in (instructions, skills_dir) if rel):
            checks.append(_ok(
                f"pointers:{agent}",
                "not set up here; the hub-adapt skill does it when this runtime runs here",
            ))
            continue
        problems = []
        if instructions:
            p = hub / instructions
            try:
                if not p.is_file():
                    problems.append(f"{instructions} missing")
                elif IMPORT_LINE not in read_text(p):
                    problems.append(f"{instructions} lacks '{IMPORT_LINE}' and hides AGENTS.md")
            except _READ_ERRORS as exc:
                problems.append(f"{instructions} unreadable: {exc}")
        links = inspect_skill_links(hub, hub / skills_dir)
        if links.missing or links.blocked:
            problems.append(
                f"{skills_dir} not linked: " + ", ".join(sorted(links.missing + links.blocked))
            )
        if links.dangling:
            problems.append(f"{skills_dir} dangling: " + ", ".join(links.dangling))
        if problems:
            checks.append(
                Check(
                    f"pointers:{agent}",
                    "warn",
                    "; ".join(problems),
                    "run the hub-adapt skill from the agent",
                )
            )
        else:
            checks.append(_ok(f"pointers:{agent}", "pointers present"))

    # apps
    checks.append(apps_check(hub, which))

    # git
    checks.append(git_check(hub))

    # nested-git
    repo = enclosing_git_repo(hub.parent)
    if repo is None:
        checks.append(_ok("nested-git", "hub is outside other repositories"))
    else:
        checks.append(
            Check(
                "nested-git",
                "fail",
                f"hub is inside {repo}",
                "move the hub outside that repository",
            )
        )

    return checks


def register(app: typer.Typer) -> None:
    @app.command("doctor")
    def doctor_cmd(
        ctx: typer.Context,
        fix: bool = typer.Option(False, "--fix", help="Apply safe fixes."),
        as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    ) -> None:
        """Check the hub's health."""
        from cc_hub.console import console, echo_json, resolve_hub

        hub = resolve_hub(ctx)
        checks = run_checks(hub, fix=fix)
        if as_json:
            echo_json([asdict(c) for c in checks])
        else:
            table = Table(title=f"cc-hub doctor: {hub}")
            for col in ("check", "status", "message", "fix"):
                table.add_column(col)
            for c in checks:
                table.add_row(escape(c.id), escape(c.status), escape(c.message), escape(c.fix))
            console.print(table)
        if any(c.status == "fail" for c in checks):
            raise typer.Exit(code=1)
