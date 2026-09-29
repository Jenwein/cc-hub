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
from cc_hub.platform import COPY_MARKER

Which = Callable[[str], "str | None"]


@dataclass
class Check:
    id: str
    status: str  # ok | warn | fail
    message: str
    fix: str = ""


DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
ENV_MAX_AGE_DAYS = 7
VALID_SHELLS = ("bash", "pwsh", "powershell")
AGENT_MARKERS = {"claude": ("claude", ".claude"), "codex": ("codex", ".codex")}
# agent -> [(relative path, "exists" | "if-present-contains", needle)]
# A CLAUDE.md is optional (Claude Code reads AGENTS.md when there is none), but
# one without the import would shadow AGENTS.md.
POINTER_RULES: dict[str, list[tuple[str, str, str]]] = {
    "claude": [
        (".claude/skills", "exists", ""),
        ("CLAUDE.md", "if-present-contains", "@AGENTS.md"),
    ],
    "codex": [
        (".agents/skills", "exists", ""),
    ],
}
# Hook configs that cc-hub 0.1.0's hub-adapt wrote into; `cc-hub hook` no longer exists.
HOOK_CONFIGS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".codex/hooks.json",
    ".codex/config.toml",
)
CC_HUB_HOOK = re.compile(r"\bhook (?:pre|post)-tool-use\b")
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
        rules = POINTER_RULES[agent]
        if not any((hub / rel).exists() for rel, _, _ in rules):
            checks.append(_ok(
                f"pointers:{agent}",
                "not set up here; the hub-adapt skill does it when this runtime runs here",
            ))
            continue
        problems = []
        for rel, kind, needle in rules:
            p = hub / rel
            if not p.exists():
                if kind == "exists":
                    problems.append(f"{rel} missing")
                continue
            if kind == "exists":
                continue
            try:
                found = needle in read_text(p)
            except _READ_ERRORS as exc:
                problems.append(f"{rel} unreadable: {exc}")
                continue
            if not found:
                problems.append(f"{rel} lacks '{needle}' and hides AGENTS.md")
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

    # stale-hooks
    leftover = []
    for rel in HOOK_CONFIGS:
        p = hub / rel
        try:
            if p.is_file() and CC_HUB_HOOK.search(read_text(p)):
                leftover.append(rel)
        except _READ_ERRORS:
            continue
    if leftover:
        checks.append(
            Check(
                "stale-hooks",
                "warn",
                "cc-hub hook entries left in: " + ", ".join(leftover),
                "remove them (the command no longer exists); the hub-adapt skill does this",
            )
        )
    else:
        checks.append(_ok("stale-hooks", "no leftover cc-hub hooks"))

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
