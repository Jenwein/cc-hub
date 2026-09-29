# -*- coding: utf-8 -*-
import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.doctor import run_checks
from cc_hub.commands.init import init_hub

NO_AGENTS = dict(which=lambda name: None)


def statuses(checks) -> dict[str, str]:
    return {c.id: c.status for c in checks}


def test_fresh_hub_has_no_failures(hub: Path, tmp_path: Path) -> None:
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["hub-toml"] == "ok"
    assert s["required-files"] == "ok"
    assert s["bootstrap-pending"] == "warn"
    assert s["env-stale"] == "warn"
    assert s["pointers"] == "ok"
    assert "daemon-path" not in s
    assert s["nested-git"] == "ok"
    assert s["stale-hooks"] == "ok"
    assert "jobs-lost" not in s
    assert "fail" not in s.values()


def test_memory_over_budget_fails(hub: Path, tmp_path: Path) -> None:
    (hub / "MEMORY.md").write_text("\n".join(["- x"] * 201), encoding="utf-8")
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["memory-budget:MEMORY.md"] == "fail"


def test_template_version_mismatch_warns(hub: Path, tmp_path: Path) -> None:
    s = statuses(run_checks(hub, home=tmp_path / "home", package_version="9.9.9", **NO_AGENTS))
    assert s["hub-toml"] == "warn"


def test_pointer_check_for_detected_claude(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    s = statuses(run_checks(hub, home=home, **NO_AGENTS))
    assert s["pointers:claude"] == "warn"
    (hub / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (hub / ".claude" / "skills").mkdir(parents=True)
    s = statuses(run_checks(hub, home=home, **NO_AGENTS))
    assert s["pointers:claude"] == "ok"


def test_pointer_check_for_detected_codex_needs_only_skills(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    assert statuses(run_checks(hub, home=home, **NO_AGENTS))["pointers:codex"] == "warn"
    (hub / ".agents" / "skills").mkdir(parents=True)
    assert statuses(run_checks(hub, home=home, **NO_AGENTS))["pointers:codex"] == "ok"


@pytest.mark.parametrize("rel", [".claude/settings.json", ".codex/hooks.json"])
def test_leftover_cc_hub_hooks_warn(hub: Path, tmp_path: Path, rel: str) -> None:
    assert statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))["stale-hooks"] == "ok"
    path = hub / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", '
        '"command": "C:\\\\Users\\\\u\\\\.local\\\\bin\\\\cc-hub.EXE hook pre-tool-use"}]}]}}',
        encoding="utf-8",
    )
    check = next(c for c in run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
                 if c.id == "stale-hooks")
    assert check.status == "warn"
    assert rel in check.message
    assert "hub-adapt" in check.fix


def test_other_hooks_are_not_reported_as_stale(hub: Path, tmp_path: Path) -> None:
    (hub / ".claude").mkdir()
    (hub / ".claude" / "settings.json").write_text(
        '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]}}',
        encoding="utf-8",
    )
    assert statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))["stale-hooks"] == "ok"


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


def test_stale_env_md_warns(hub: Path, tmp_path: Path) -> None:
    env_md = hub / "ENV.md"
    env_md.write_text("# env", encoding="utf-8")
    fresh = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert fresh["env-stale"] == "ok"
    future = env_md.stat().st_mtime + 8 * 86400
    old = statuses(run_checks(hub, home=tmp_path / "home", now=future, **NO_AGENTS))
    assert old["env-stale"] == "warn"


def test_doctor_cli_json(hub: Path) -> None:
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor", "--json"])
    assert result.exit_code == 0, result.output
    ids = {c["id"] for c in json.loads(result.output)}
    assert {"hub-toml", "required-files", "stale-hooks"} <= ids


def test_doctor_cli_exit_1_on_fail(hub: Path) -> None:
    (hub / "MEMORY.md").write_text("\n".join(["- x"] * 201), encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor"])
    assert result.exit_code == 1


def test_doctor_cli_table_escapes_rich_markup(hub: Path) -> None:
    (hub / "memory" / "[note].md").write_text("x", encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor"])
    assert result.exit_code == 0, result.output
    assert "[note].md" in result.output


def test_unreadable_projects_toml_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "projects.toml").write_bytes(b"\xff\xfe[[project]]\n")
    s = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    ids = statuses(s)
    assert ids["projects"] == "fail"
    assert "nested-git" in ids
    assert "stale-hooks" in ids


def test_invalid_toml_syntax_in_hosts_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "hosts.toml").write_text("[[host]\nname = \n", encoding="utf-8")
    s = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    ids = statuses(s)
    assert ids["hosts"] == "fail"
    assert "nested-git" in ids


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
