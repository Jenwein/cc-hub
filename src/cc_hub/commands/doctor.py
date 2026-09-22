# -*- coding: utf-8 -*-
"""cc-hub doctor: health checks for a hub directory."""

from __future__ import annotations

import re
import shutil
import time
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from cc_hub import __version__, manifest
from cc_hub.commands.init import enclosing_git_repo
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import load_config
from cc_hub.platform import COPY_MARKER, which_minimal

Which = Callable[[str], "str | None"]


@dataclass
class Check:
    id: str
    status: str  # ok | warn | fail
    message: str
    fix: str = ""


DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
ENV_MAX_AGE_DAYS = 7
DAEMON_BINARIES = ("cc-hub", "uv", "cc-connect", "claude", "codex")
VALID_SHELLS = ("bash", "pwsh", "powershell")
AGENT_MARKERS = {"claude": ("claude", ".claude"), "codex": ("codex", ".codex")}
# agent -> [(relative path, "exists" | "contains", needle)]
POINTER_RULES: dict[str, list[tuple[str, str, str]]] = {
    "claude": [
        ("CLAUDE.md", "contains", "@AGENTS.md"),
        (".claude/skills", "exists", ""),
        (".claude/settings.json", "contains", "pre-tool-use"),
    ],
    "codex": [
        (".agents/skills", "exists", ""),
        (".codex/hooks.json", "contains", "pre-tool-use"),
    ],
}
PATH_FIX = "set PATH in cc-connect's [projects.agent.options.env] (see docs/cc-connect.md)"
_READ_ERRORS = (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError)


def detect_agents(*, home: Path, which: Which) -> list[str]:
    return [a for a, (exe, dot) in AGENT_MARKERS.items() if which(exe) or (home / dot).exists()]


def _ok(id_: str, message: str) -> Check:
    return Check(id_, "ok", message)


def _load_table(path: Path, key: str) -> list[dict]:
    if not path.is_file():
        return []
    return list(tomllib.loads(read_text(path)).get(key, []))


def run_checks(
    hub: Path,
    *,
    fix: bool = False,
    home: Path | None = None,
    which: Which = shutil.which,
    which_daemon: Which = which_minimal,
    now: float | None = None,
    package_version: str = __version__,
) -> list[Check]:
    hub = Path(hub)
    home = home or Path.home()
    now = time.time() if now is None else now
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
        write_text(
            hub / ".gitignore", manifest.render(".gitignore", name=name, version=package_version)
        )
        for d in manifest.USER_DIRS:
            (hub / d).mkdir(exist_ok=True)
        for rel in manifest.USER_OWNED:
            if not (hub / rel).is_file():
                write_text(hub / rel, manifest.render(rel, name=name, version=package_version))
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

    # projects
    try:
        projects = _load_table(hub / "projects.toml", "project")
        gone = [
            str(p.get("name", "?"))
            for p in projects
            if not Path(str(p.get("path", ""))).expanduser().is_dir()
        ]
        if gone:
            checks.append(
                Check(
                    "projects",
                    "warn",
                    "paths missing: " + ", ".join(gone),
                    "cc-hub projects remove <name>",
                )
            )
        else:
            checks.append(_ok("projects", f"{len(projects)} registered"))
    except _READ_ERRORS as exc:
        checks.append(Check("projects", "fail", f"projects.toml: {exc}", "fix the TOML"))

    # hosts
    try:
        hosts = _load_table(hub / "hosts.toml", "host")
        bad_shell = [
            str(h.get("name", "?")) for h in hosts if h.get("shell", "bash") not in VALID_SHELLS
        ]
        if bad_shell:
            checks.append(
                Check(
                    "hosts",
                    "fail",
                    "invalid shell for: " + ", ".join(bad_shell),
                    "shell must be bash | pwsh | powershell",
                )
            )
        else:
            checks.append(_ok("hosts", f"{len(hosts)} registered"))
    except _READ_ERRORS as exc:
        checks.append(Check("hosts", "fail", f"hosts.toml: {exc}", "fix the TOML"))

    # env-stale
    env_md = hub / "ENV.md"
    if not env_md.is_file():
        checks.append(Check("env-stale", "warn", "ENV.md missing", "run `cc-hub env`"))
    else:
        age = (now - env_md.stat().st_mtime) / 86400
        if age <= ENV_MAX_AGE_DAYS:
            checks.append(_ok("env-stale", f"ENV.md is {age:.0f} days old"))
        else:
            checks.append(
                Check("env-stale", "warn", f"ENV.md is {age:.0f} days old", "run `cc-hub env`")
            )

    # pointers
    agents = detect_agents(home=home, which=which)
    if not agents:
        checks.append(_ok("pointers", "no agent runtimes detected on this machine"))
    for agent in agents:
        problems = []
        for rel, kind, needle in POINTER_RULES[agent]:
            p = hub / rel
            if kind == "exists":
                if not p.exists():
                    problems.append(f"{rel} missing")
                continue
            try:
                found = p.is_file() and needle in read_text(p)
            except _READ_ERRORS as exc:
                problems.append(f"{rel} unreadable: {exc}")
                continue
            if not found:
                problems.append(f"{rel} missing or lacks '{needle}'")
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

    # link-stale
    skills = hub / "skills"
    src_mtime = max((p.stat().st_mtime for p in skills.rglob("*") if p.is_file()), default=0.0)
    stale = [
        str(m.parent.relative_to(hub))
        for m in hub.glob(f".*/skills/{COPY_MARKER}")
        if m.stat().st_mtime < src_mtime
    ]
    if stale:
        checks.append(
            Check(
                "link-stale",
                "warn",
                "stale copies: " + ", ".join(stale),
                "re-run the hub-adapt skill (cc-hub link)",
            )
        )
    else:
        checks.append(_ok("link-stale", "no stale copies"))

    # daemon-path
    lost = [b for b in DAEMON_BINARIES if which(b) and not which_daemon(b)]
    if lost:
        checks.append(
            Check(
                "daemon-path",
                "warn",
                "not visible under a minimal PATH: " + ", ".join(lost),
                PATH_FIX,
            )
        )
    else:
        checks.append(_ok("daemon-path", "all installed binaries visible under a minimal PATH"))

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

    # jobs-lost
    from cc_hub.commands.jobs import is_lost, list_jobs, reconcile

    if fix and (hub / "jobs").is_dir():
        for j in list_jobs(hub):
            reconcile(hub, j)
    lost_jobs = list_jobs(hub) if (hub / "jobs").is_dir() else []
    lost_ids = [j.id for j in lost_jobs if is_lost(j)]
    if lost_ids:
        checks.append(Check("jobs-lost", "warn", "running but dead: " + ", ".join(lost_ids),
                            "`cc-hub doctor --fix` marks them lost"))
    else:
        checks.append(_ok("jobs-lost", "no orphaned jobs"))

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
