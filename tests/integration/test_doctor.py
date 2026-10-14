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
from cc_hub.cronguard import HOOK_COMMAND
from tests.conftest import write

NO_AGENTS = dict(which=lambda name: None)
CHECK_IDS = [
    "hub-toml",
    "required-files",
    "bootstrap-pending",
    "memory-budget:MEMORY.md",
    "memory-budget:USER.md",
    "memory-files",
    "pointers",
    "apps",
    "cron",
    "git",
    "nested-git",
]


def statuses(checks) -> dict[str, str]:
    return {c.id: c.status for c in checks}


def test_fresh_hub_runs_the_hub_checks(hub: Path, tmp_path: Path) -> None:
    checks = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    assert [c.id for c in checks] == CHECK_IDS
    assert [c.id for c in checks if c.status != "ok"] == ["bootstrap-pending", "git"]


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
    assert "not linked: hub-adapt, hub-apps, hub-feedback, hub-memory" in check.message
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


def _git_check(hub: Path, tmp_path: Path):
    return next(c for c in run_checks(hub, home=tmp_path / "home", **NO_AGENTS) if c.id == "git")


def test_git_check_without_a_repository(hub: Path, tmp_path: Path) -> None:
    check = _git_check(hub, tmp_path)
    assert check.status == "warn"
    assert "not a git repository" in check.message
    assert "cc-hub init" in check.fix


def test_git_check_reports_uncommitted_changes_and_a_missing_remote(
    git_hub: Path, tmp_path: Path
) -> None:
    check = _git_check(git_hub, tmp_path)
    assert check.status == "warn"
    assert check.message == "no remote: the hub is not backed up"
    (git_hub / "SOUL.md").write_text("changed", encoding="utf-8")
    assert "1 uncommitted change(s)" in _git_check(git_hub, tmp_path).message


def test_git_check_ok_with_a_remote(git_hub: Path, tmp_path: Path) -> None:
    from cc_hub.gitops import run_git

    run_git(git_hub, "remote", "add", "origin", "https://example.invalid/hub.git")
    check = _git_check(git_hub, tmp_path)
    assert check.status == "ok"
    assert "origin" in check.message


def test_fix_commits_what_it_restored(git_hub: Path, tmp_path: Path) -> None:
    from cc_hub.gitops import run_git

    (git_hub / "USER.md").unlink()
    run_git(git_hub, "commit", "-qam", "lose USER.md")
    run_checks(git_hub, fix=True, home=tmp_path / "home", **NO_AGENTS)
    log = run_git(git_hub, "log", "-1", "--format=%s").stdout.strip()
    assert log == "cc-hub: doctor --fix"
    shown = run_git(git_hub, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert shown == ["USER.md"]


def _apps_check(hub: Path, tmp_path: Path, which=lambda name: None):
    checks = run_checks(hub, home=tmp_path / "home", which=which)
    return next(c for c in checks if c.id == "apps")


def test_apps_check_without_apps(hub: Path, tmp_path: Path) -> None:
    check = _apps_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "no apps installed")


def test_apps_check_reports_software_and_setup(
    hub: Path, tmp_path: Path, ledger_tap: Path, register_tap
) -> None:
    from cc_hub import apps

    register_tap(hub, "my-apps", ledger_tap)
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    check = _apps_check(hub, tmp_path)
    assert check.status == "warn"
    assert "ledger: needs cc-hub-test-no-such-bin (uv tool install beancount)" in check.message
    assert "ledger: setup pending" in check.message
    assert "hub-apps" in check.fix
    apps.set_setup_state(hub, "ledger", "done")
    check = _apps_check(hub, tmp_path, which=lambda name: f"/usr/bin/{name}")
    assert (check.status, check.message) == ("ok", "1 app(s) set up")
    from cc_hub.platform import rmtree

    rmtree(hub / "apps" / "ledger")
    check = _apps_check(hub, tmp_path)
    assert "ledger: missing from apps/" in check.message
    assert "cc-hub app sync" in check.fix


def test_a_broken_apps_lock_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "apps.lock").write_text("[apps\n", encoding="utf-8")
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["apps"] == "fail"
    assert s["nested-git"] == "ok"


def test_a_wrongly_shaped_apps_lock_fails_only_that_check(hub: Path, tmp_path: Path) -> None:
    (hub / "apps.lock").write_text("taps = 1\n", encoding="utf-8")
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["apps"] == "fail"
    assert s["nested-git"] == "ok"


def test_a_link_whose_source_is_gone_says_so(hub: Path, tmp_path: Path) -> None:
    from cc_hub import apps
    from cc_hub.platform import rmtree

    dev = tmp_path / "dev" / "notes"
    dev.mkdir(parents=True)
    (dev / "app.toml").write_text(
        '[app]\nname = "notes"\nversion = "0.1.0"\ndescription = "Notes"\n', encoding="utf-8"
    )
    apps.install(hub, apps.plan_install(hub, str(dev), link=True))
    rmtree(dev)
    check = _apps_check(hub, tmp_path)
    assert check.status == "warn"
    assert "notes: link source" in check.message and "does not exist" in check.message
    assert "cc-hub app remove notes --yes" in check.fix
    assert "app sync" not in check.fix


def test_an_unreadable_app_toml_says_so(
    hub: Path, tmp_path: Path, ledger_tap: Path, register_tap
) -> None:
    from cc_hub import apps

    register_tap(hub, "my-apps", ledger_tap)
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    (hub / "apps" / "ledger" / "app.toml").write_text("[app\n", encoding="utf-8")
    check = _apps_check(hub, tmp_path)
    assert check.status == "warn"
    assert "ledger: app.toml in apps/ledger is unreadable" in check.message
    assert "cc-hub app remove ledger --yes" in check.fix
    assert "app sync" not in check.fix


def test_git_check_points_at_doctor_fix_when_the_identity_is_missing(
    git_hub: Path, git_env: Path, tmp_path: Path
) -> None:
    assert "identity" not in _git_check(git_hub, tmp_path).message
    git_env.write_text("", encoding="utf-8")
    check = _git_check(git_hub, tmp_path)
    assert check.status == "warn"
    assert "no git identity" in check.message
    assert "run `cc-hub doctor --fix` to set a repository-local identity" in check.fix


def test_fix_sets_a_repository_local_identity_before_it_commits(
    git_hub: Path, git_env: Path, tmp_path: Path
) -> None:
    from cc_hub.gitops import run_git

    (git_hub / "USER.md").unlink()
    run_git(git_hub, "commit", "-qam", "lose USER.md")
    git_env.write_text("", encoding="utf-8")
    checks = run_checks(git_hub, fix=True, home=tmp_path / "home", **NO_AGENTS)
    assert run_git(git_hub, "config", "--local", "user.email").stdout.strip() == (
        "hub@cc-hub.invalid"
    )
    assert run_git(git_hub, "config", "--local", "user.name").stdout.strip() == (
        "中文 hub (cc-hub)"
    )
    assert run_git(git_hub, "log", "-1", "--format=%s").stdout.strip() == "cc-hub: doctor --fix"
    assert "identity" not in next(c for c in checks if c.id == "git").message


def test_fix_leaves_the_identity_alone_in_a_hub_that_is_not_a_repository(
    hub: Path, tmp_path: Path
) -> None:
    run_checks(hub, fix=True, home=tmp_path / "home", **NO_AGENTS)
    assert not (hub / ".git").exists()


def _cron_check(hub: Path, tmp_path: Path):
    checks = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    return next(c for c in checks if c.id == "cron")


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _hook(matcher: str, command: str) -> dict:
    return {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}


def test_cron_check_is_ok_for_a_hub_with_tasks_and_a_valid_override(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    from cc_hub.cronoverrides import save

    save(hub_with_mail, "mail/poll", {"schedule": "0 8 * * *"})
    check = _cron_check(hub_with_mail, tmp_path)
    assert (check.status, check.message) == ("ok", "3 task(s) checked")


def test_cron_check_names_a_broken_task_file(hub: Path, tmp_path: Path) -> None:
    write(hub / "cron" / "broken.md", "---\ndefault: true\n---\n")
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn"
    assert "cron/broken.md: schedule is required" in check.message
    assert "cron/broken.md" in check.fix


def test_cron_check_names_a_broken_task_file_of_an_app(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    write(hub_with_mail / "apps" / "mail" / "cron" / "poll.md", "no frontmatter\n")
    check = _cron_check(hub_with_mail, tmp_path)
    assert check.status == "warn"
    assert "apps/mail/cron/poll.md" in check.message
    assert "cc-hub app update mail" in check.fix


def test_cron_check_reports_an_override_whose_task_is_gone(hub: Path, tmp_path: Path) -> None:
    _append(hub / "hub.toml", '\n[cron."gone/task"]\nschedule = "0 7 * * *"\n')
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [cron."gone/task"] has no task' in check.message
    assert "cc-hub cron reset gone/task" in check.fix


def test_cron_check_reports_an_invalid_expression_in_an_override(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    _append(hub_with_mail / "hub.toml", '\n[cron."mail/poll"]\nschedule = "every day"\n')
    check = _cron_check(hub_with_mail, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [cron."mail/poll"]' in check.message and "five fields" in check.message
    assert "cc-hub cron reset mail/poll" in check.fix


def test_cron_check_reports_an_override_of_the_wrong_type(hub: Path, tmp_path: Path) -> None:
    _append(hub / "hub.toml", '\n[cron."memory-consolidate"]\nenabled = "no"\n')
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn"
    assert "enabled must be true or false" in check.message
    assert "cc-hub cron reset memory-consolidate" in check.fix


def test_cron_check_reports_a_cron_table_of_the_wrong_shape(hub: Path, tmp_path: Path) -> None:
    _append(hub / "hub.toml", "\n[cron]\nschedule = 1\n")
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn" and "hub.toml" in check.message


def test_cron_check_leaves_an_unreadable_hub_toml_to_the_hub_toml_check(
    hub: Path, tmp_path: Path
) -> None:
    (hub / "hub.toml").write_text("[hub\n", encoding="utf-8")
    check = _cron_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "hub.toml unreadable; see hub-toml")


def test_cron_check_leaves_a_broken_apps_lock_to_the_apps_check(
    hub: Path, tmp_path: Path
) -> None:
    (hub / "apps.lock").write_text("[apps\n", encoding="utf-8")
    check = _cron_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "apps.lock unreadable; see apps")


def test_cron_check_leaves_the_overrides_of_an_app_that_is_not_synced_yet(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    from cc_hub.cronoverrides import save
    from cc_hub.platform import rmtree

    save(hub_with_mail, "mail/poll", {"schedule": "0 8 * * *"})
    rmtree(hub_with_mail / "apps" / "mail")  # as in a clone before `cc-hub app sync`
    assert _cron_check(hub_with_mail, tmp_path).status == "ok"
    s = statuses(run_checks(hub_with_mail, home=tmp_path / "home", **NO_AGENTS))
    assert s["apps"] == "warn"


def test_cron_check_warns_of_a_restricted_task_without_the_guard(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    from cc_hub import cronguard

    write(hub_with_mail / "CLAUDE.md", "@AGENTS.md\n")
    check = _cron_check(hub_with_mail, tmp_path)
    assert check.status == "warn"
    assert "mail/triage" in check.message and ".claude/settings.json" in check.message
    assert "hub-adapt" in check.fix
    assert cronguard.setup(hub_with_mail) is True
    assert _cron_check(hub_with_mail, tmp_path).status == "ok"


def test_cron_check_counts_a_claude_skills_directory_as_claude_code_set_up(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    (hub_with_mail / ".claude" / "skills").mkdir(parents=True)
    assert _cron_check(hub_with_mail, tmp_path).status == "warn"


def test_cron_check_is_quiet_where_claude_code_was_never_set_up(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    assert _cron_check(hub_with_mail, tmp_path).status == "ok"


def test_cron_check_is_quiet_without_a_restricted_task(hub: Path, tmp_path: Path) -> None:
    write(hub / "CLAUDE.md", "@AGENTS.md\n")
    assert _cron_check(hub, tmp_path).status == "ok"


@pytest.mark.parametrize(
    "settings",
    [
        "not json",
        "[]",
        '{"hooks": []}',
        '{"hooks": {"PreToolUse": {}}}',
        '{"hooks": {"PreToolUse": [1, {"hooks": 2}, {"hooks": [3, {"command": "other"}]}]}}',
    ],
)
def test_cron_check_does_not_count_a_settings_file_without_the_guard(
    hub_with_mail: Path, tmp_path: Path, settings: str
) -> None:
    write(hub_with_mail / "CLAUDE.md", "@AGENTS.md\n")
    write(hub_with_mail / ".claude" / "settings.json", settings)
    assert _cron_check(hub_with_mail, tmp_path).status == "warn"


def test_cron_check_finds_the_guard_next_to_the_users_own_hooks(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    write(hub_with_mail / "CLAUDE.md", "@AGENTS.md\n")
    write(
        hub_with_mail / ".claude" / "settings.json",
        json.dumps({"hooks": {"PreToolUse": [_hook("Bash", "mine"), _hook("*", HOOK_COMMAND)]}}),
    )
    assert _cron_check(hub_with_mail, tmp_path).status == "ok"
