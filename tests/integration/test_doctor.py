# -*- coding: utf-8 -*-
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.doctor import run_checks
from cc_hub.commands.init import init_hub
from cc_hub.commands.link import sync_skill_links

NO_AGENTS = dict(which=lambda name: None)
CHECK_IDS = [
    "hub-toml",
    "required-files",
    "bootstrap-pending",
    "memory-budget:MEMORY.md",
    "memory-budget:USER.md",
    "memory-files",
    "pointers",
    "nested-git",
]


def statuses(checks) -> dict[str, str]:
    return {c.id: c.status for c in checks}


def test_fresh_hub_runs_the_hub_checks(hub: Path, tmp_path: Path) -> None:
    checks = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    assert [c.id for c in checks] == CHECK_IDS
    assert [c.id for c in checks if c.status != "ok"] == ["bootstrap-pending"]


def test_memory_over_budget_fails(hub: Path, tmp_path: Path) -> None:
    (hub / "MEMORY.md").write_text("\n".join(["- x"] * 201), encoding="utf-8")
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["memory-budget:MEMORY.md"] == "fail"


def test_template_version_mismatch_warns(hub: Path, tmp_path: Path) -> None:
    s = statuses(run_checks(hub, home=tmp_path / "home", package_version="9.9.9", **NO_AGENTS))
    assert s["hub-toml"] == "warn"


def test_broken_hub_toml_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "hub.toml").write_text("[hub\n", encoding="utf-8")
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["hub-toml"] == "fail"
    assert s["memory-budget:MEMORY.md"] == "ok"
    assert s["nested-git"] == "ok"


def _pointer(hub: Path, home: Path, agent: str):
    return next(c for c in run_checks(hub, home=home, **NO_AGENTS) if c.id == f"pointers:{agent}")


def test_runtime_not_set_up_here_is_not_a_warning(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    for agent in ("claude", "codex"):
        check = _pointer(hub, home, agent)
        assert check.status == "ok", agent
        assert "not set up" in check.message


def test_claude_pointers(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    sync_skill_links(hub, hub / ".claude" / "skills")
    check = _pointer(hub, home, "claude")
    assert check.status == "warn" and "CLAUDE.md missing" in check.message
    (hub / "CLAUDE.md").write_text("# my notes\n", encoding="utf-8")
    check = _pointer(hub, home, "claude")
    assert check.status == "warn" and "@AGENTS.md" in check.message
    (hub / "CLAUDE.md").write_text("@AGENTS.md\n\n- a note from /memory add\n", encoding="utf-8")
    assert _pointer(hub, home, "claude").status == "ok"


def test_skill_links_are_checked_per_skill(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    target = hub / ".agents" / "skills"
    target.mkdir(parents=True)
    check = _pointer(hub, home, "codex")
    assert check.status == "warn"
    assert "not linked: hub-adapt, hub-memory" in check.message
    assert "hub-adapt" in check.fix
    sync_skill_links(hub, target)
    assert _pointer(hub, home, "codex").status == "ok"
    mine = hub / "skills" / "mine"
    mine.mkdir()
    (mine / "SKILL.md").write_text("---\nname: mine\n---\n", encoding="utf-8")
    assert "not linked: mine" in _pointer(hub, home, "codex").message
    sync_skill_links(hub, target)
    shutil.rmtree(mine)
    assert "dangling: mine" in _pointer(hub, home, "codex").message


def test_fix_recreates_missing_user_file_but_not_framework_file(hub: Path, tmp_path: Path) -> None:
    (hub / "USER.md").unlink()
    (hub / "AGENTS.md").unlink()
    s = statuses(run_checks(hub, fix=True, home=tmp_path / "home", **NO_AGENTS))
    assert (hub / "USER.md").is_file()
    assert not (hub / "AGENTS.md").exists()
    assert s["required-files"] == "fail"


def test_nested_git_fails(tmp_path: Path) -> None:
    h = tmp_path / "h"
    init_hub(h, git=False)
    (tmp_path / ".git").mkdir()
    s = statuses(run_checks(h, home=tmp_path / "home", **NO_AGENTS))
    assert s["nested-git"] == "fail"


def test_doctor_cli_json(hub: Path) -> None:
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor", "--json"])
    assert result.exit_code == 0, result.output
    ids = {c["id"] for c in json.loads(result.output)}
    assert {"hub-toml", "required-files", "nested-git"} <= ids


def test_doctor_cli_exit_1_on_fail(hub: Path) -> None:
    (hub / "MEMORY.md").write_text("\n".join(["- x"] * 201), encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor"])
    assert result.exit_code == 1


def test_doctor_cli_table_escapes_rich_markup(hub: Path) -> None:
    (hub / "memory" / "[note].md").write_text("x", encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor"])
    assert result.exit_code == 0, result.output
    assert "[note].md" in result.output


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads anything")
def test_unreadable_memory_file_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "MEMORY.md").chmod(0o000)
    try:
        ids = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    finally:
        (hub / "MEMORY.md").chmod(0o644)
    assert ids["memory-budget:MEMORY.md"] == "fail"
    assert "nested-git" in ids


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads anything")
def test_unreadable_pointer_file_warns(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (hub / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (hub / "CLAUDE.md").chmod(0o000)
    try:
        ids = statuses(run_checks(hub, home=home, **NO_AGENTS))
    finally:
        (hub / "CLAUDE.md").chmod(0o644)
    assert ids["pointers:claude"] == "warn"
