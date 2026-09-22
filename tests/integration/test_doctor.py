# -*- coding: utf-8 -*-
import json
from pathlib import Path

from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.doctor import run_checks
from cc_hub.commands.init import init_hub

NO_AGENTS = dict(which=lambda name: None, which_daemon=lambda name: None)


def statuses(checks) -> dict[str, str]:
    return {c.id: c.status for c in checks}


def test_fresh_hub_has_no_failures(hub: Path, tmp_path: Path) -> None:
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["hub-toml"] == "ok"
    assert s["required-files"] == "ok"
    assert s["bootstrap-pending"] == "warn"
    assert s["env-stale"] == "warn"
    assert s["pointers"] == "ok"
    assert s["daemon-path"] == "ok"
    assert s["nested-git"] == "ok"
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
    (hub / ".claude" / "settings.json").write_text(
        '{"hooks": {"PreToolUse": [{"hooks": [{"command": "cc-hub hook pre-tool-use"}]}]}}',
        encoding="utf-8",
    )
    s = statuses(run_checks(hub, home=home, **NO_AGENTS))
    assert s["pointers:claude"] == "ok"


def test_daemon_path_warns_when_binary_is_hidden(hub: Path, tmp_path: Path) -> None:
    checks = run_checks(
        hub,
        home=tmp_path / "home",
        which=lambda name: f"/opt/bin/{name}",
        which_daemon=lambda name: None,
    )
    check = next(c for c in checks if c.id == "daemon-path")
    assert check.status == "warn"
    assert "cc-hub" in check.message
    assert "projects.agent.options.env" in check.fix


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
    assert {"hub-toml", "required-files", "daemon-path"} <= ids


def test_doctor_cli_exit_1_on_fail(hub: Path) -> None:
    (hub / "MEMORY.md").write_text("\n".join(["- x"] * 201), encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "doctor"])
    assert result.exit_code == 1
