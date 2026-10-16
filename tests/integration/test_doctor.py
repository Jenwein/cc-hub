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
from tests.conftest import fake_app, write

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
    "reports",
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


def test_cron_check_is_ok_for_a_hub_with_tasks_and_a_valid_override(
    hub_with_plans: Path, tmp_path: Path
) -> None:
    from cc_hub.cronoverrides import save

    save(hub_with_plans, "plans/morning", {"schedule": "0 7 * * *"})
    check = _cron_check(hub_with_plans, tmp_path)
    assert (check.status, check.message) == ("ok", "8 task(s) checked")


def test_cron_check_names_a_broken_task_file(hub: Path, tmp_path: Path) -> None:
    write(hub / "cron" / "broken.md", "---\ndefault: true\n---\n")
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn"
    assert "cron/broken.md: schedule is required" in check.message
    assert "cron/broken.md" in check.fix


def test_cron_check_names_a_broken_task_file_of_an_app(
    hub_with_plans: Path, tmp_path: Path
) -> None:
    write(hub_with_plans / "apps" / "plans" / "cron" / "morning.md", "no frontmatter\n")
    check = _cron_check(hub_with_plans, tmp_path)
    assert check.status == "warn"
    assert "apps/plans/cron/morning.md" in check.message
    assert "cc-hub app update plans" in check.fix


def test_cron_check_reports_an_override_whose_task_is_gone(hub: Path, tmp_path: Path) -> None:
    _append(hub / "hub.toml", '\n[cron."gone/task"]\nschedule = "0 7 * * *"\n')
    check = _cron_check(hub, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [cron."gone/task"] has no task' in check.message
    assert "cc-hub cron reset gone/task" in check.fix


def test_cron_check_reports_an_invalid_expression_in_an_override(
    hub_with_plans: Path, tmp_path: Path
) -> None:
    _append(hub_with_plans / "hub.toml", '\n[cron."plans/morning"]\nschedule = "every day"\n')
    check = _cron_check(hub_with_plans, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [cron."plans/morning"]' in check.message
    assert "five fields" in check.message
    assert "cc-hub cron reset plans/morning" in check.fix


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
    hub_with_plans: Path, tmp_path: Path
) -> None:
    from cc_hub.cronoverrides import save
    from cc_hub.platform import rmtree

    save(hub_with_plans, "plans/morning", {"schedule": "0 7 * * *"})
    rmtree(hub_with_plans / "apps" / "plans")  # as in a clone before `cc-hub app sync`
    assert _cron_check(hub_with_plans, tmp_path).status == "ok"
    s = statuses(run_checks(hub_with_plans, home=tmp_path / "home", **NO_AGENTS))
    assert s["apps"] == "warn"


# --- reports ---

MAIL_CMD = "cc-hub-mail report daily"
MAIL_DAILY = f'---\ncommand: "{MAIL_CMD}"\ntitle: Mail\n---\n'
DIARY_WEEKLY = "---\ntitle: Diary\n---\nSummarise the week.\n"


def _reports_check(hub: Path, tmp_path: Path):
    checks = run_checks(hub, home=tmp_path / "home", **NO_AGENTS)
    return next(c for c in checks if c.id == "reports")


def _hub_with_sections(hub: Path, *, approved: bool = True) -> Path:
    from cc_hub import reportstate

    fake_app(hub, "mail", {"reports/daily.md": MAIL_DAILY})
    fake_app(hub, "diary", {"reports/weekly.md": DIARY_WEEKLY})
    if approved:
        reportstate.approve(hub, "mail", {"daily": MAIL_CMD})
    return hub


def test_reports_check_runs_right_after_the_cron_check(hub: Path, tmp_path: Path) -> None:
    ids = [c.id for c in run_checks(hub, home=tmp_path / "home", **NO_AGENTS)]
    assert ids.index("reports") == ids.index("cron") + 1


def test_reports_check_is_ok_for_a_hub_without_sections(hub: Path, tmp_path: Path) -> None:
    check = _reports_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "0 report section(s) checked")


def test_reports_check_is_ok_for_a_clean_hub(hub: Path, tmp_path: Path) -> None:
    check = _reports_check(_hub_with_sections(hub), tmp_path)
    assert (check.status, check.message) == ("ok", "2 report section(s) checked")


def test_reports_check_names_a_broken_section_file(hub: Path, tmp_path: Path) -> None:
    _hub_with_sections(hub)
    write(hub / "apps" / "diary" / "reports" / "weekly.md", "no frontmatter\n")
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "apps/diary/reports/weekly.md: needs a frontmatter block" in check.message
    assert "mail" not in check.message
    assert check.fix == (
        "fix apps/diary/reports/weekly.md, or run cc-hub app update diary"
    )


def test_reports_check_names_an_empty_command(hub: Path, tmp_path: Path) -> None:
    fake_app(hub, "mail", {"reports/daily.md": "---\ncommand:\n---\n"})
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "apps/mail/reports/daily.md: command is empty" in check.message


def test_reports_check_names_a_file_that_is_not_a_period(hub: Path, tmp_path: Path) -> None:
    fake_app(hub, "mail", {"reports/hourly.md": "---\n---\n"})
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "apps/mail/reports/hourly.md: hourly is not a report period" in check.message
    assert "apps/mail/reports/hourly.md" in check.fix and "cc-hub app update mail" in check.fix


def test_reports_check_joins_the_problems_of_several_files(hub: Path, tmp_path: Path) -> None:
    fake_app(hub, "mail", {"reports/hourly.md": "---\n---\n", "reports/daily.md": "nope\n"})
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "hourly.md" in check.message and "daily.md" in check.message
    assert check.message.count("; ") == 1
    assert "fix apps/mail/reports/daily.md," in check.fix
    assert "fix apps/mail/reports/hourly.md," in check.fix


def test_reports_check_prints_the_error_of_an_app_name_apps_lock_cannot_hold(
    hub: Path, tmp_path: Path
) -> None:
    fake_app(hub, "Bad_App", {"reports/daily.md": MAIL_DAILY})
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "apps.lock: app name 'Bad_App': use lowercase letters" in check.message
    assert "Bad_App/" not in check.message  # the section key of such an error is not shown
    assert "apps.lock" in check.fix and "Bad_App/" not in check.fix


def test_reports_check_reports_a_bad_report_setting(hub: Path, tmp_path: Path) -> None:
    _append(hub / "hub.toml", "\n[report]\nlanguage = 7\n")
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "hub.toml: [report] language must be a language tag" in check.message
    assert check.fix == "fix hub.toml"


@pytest.mark.parametrize(
    "text, message",
    [
        ("\n[report]\nfoo = 1\n", "foo is not a setting"),
        ('\n[report."mail"]\nenabled = false\n', "the table name must be <app>/<period>"),
        ('\n[report."mail/daily"]\nenabled = "no"\n', "enabled must be true or false"),
        ("\n[report]\norder = 3\n", "order must be a list of app names"),
    ],
)
def test_reports_check_reports_each_kind_of_bad_setting(
    hub: Path, tmp_path: Path, text: str, message: str
) -> None:
    _append(hub / "hub.toml", text)
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn" and message in check.message
    assert check.fix == "fix hub.toml"


def test_reports_check_reports_a_table_whose_section_is_gone(hub: Path, tmp_path: Path) -> None:
    _hub_with_sections(hub)
    _append(hub / "hub.toml", '\n[report."gone/daily"]\nenabled = false\n')
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [report."gone/daily"] has no section' in check.message
    assert check.fix == "run cc-hub report section gone daily --on"


def test_reports_check_reports_a_table_for_a_period_the_app_has_no_section_for(
    hub: Path, tmp_path: Path
) -> None:
    _hub_with_sections(hub)
    _append(hub / "hub.toml", '\n[report."mail/weekly"]\nenabled = false\n')
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert 'hub.toml: [report."mail/weekly"] has no section' in check.message
    assert check.fix == "run cc-hub report section mail weekly --on"


def test_reports_check_accepts_the_table_of_a_section_that_is_switched_off(
    hub: Path, tmp_path: Path
) -> None:
    from cc_hub.reports import save_section

    _hub_with_sections(hub)
    save_section(hub, "diary/weekly", False)
    check = _reports_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "2 report section(s) checked")


def test_reports_check_does_not_call_a_table_orphaned_because_its_file_is_broken(
    hub: Path, tmp_path: Path
) -> None:
    from cc_hub.reports import save_section

    _hub_with_sections(hub)
    save_section(hub, "diary/weekly", False)
    write(hub / "apps" / "diary" / "reports" / "weekly.md", "no frontmatter\n")
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn"
    assert "has no section" not in check.message and "frontmatter" in check.message


def test_reports_check_leaves_the_tables_of_an_app_that_is_not_synced_yet(
    hub: Path, tmp_path: Path
) -> None:
    from cc_hub.platform import rmtree
    from cc_hub.reports import save_section

    _hub_with_sections(hub)
    save_section(hub, "diary/weekly", False)
    rmtree(hub / "apps" / "diary")  # as in a clone before `cc-hub app sync`
    assert _reports_check(hub, tmp_path).status == "ok"
    s = statuses(run_checks(hub, home=tmp_path / "home", **NO_AGENTS))
    assert s["apps"] == "warn"


def test_reports_check_warns_about_a_command_that_is_not_approved(
    hub: Path, tmp_path: Path
) -> None:
    check = _reports_check(_hub_with_sections(hub, approved=False), tmp_path)
    assert check.status == "warn"
    assert "mail/daily" in check.message and "not approved" in check.message
    assert "diary" not in check.message  # a section with instructions needs no approval
    assert check.fix == "approve it during app setup: cc-hub report approve mail"


def test_reports_check_warns_when_a_command_changed_after_it_was_approved(
    hub: Path, tmp_path: Path
) -> None:
    _hub_with_sections(hub)
    assert _reports_check(hub, tmp_path).status == "ok"
    write(hub / "apps" / "mail" / "reports" / "daily.md", MAIL_DAILY.replace("daily", "daily -v"))
    check = _reports_check(hub, tmp_path)
    assert check.status == "warn" and "mail/daily" in check.message


def test_reports_check_asks_about_each_app_whose_commands_are_not_approved(
    hub: Path, tmp_path: Path
) -> None:
    _hub_with_sections(hub, approved=False)
    fake_app(hub, "feeds", {"reports/monthly.md": '---\ncommand: "feeds-report"\n---\n'})
    check = _reports_check(hub, tmp_path)
    assert "mail/daily" in check.message and "feeds/monthly" in check.message
    assert "cc-hub report approve mail" in check.fix and "cc-hub report approve feeds" in check.fix


def test_reports_check_does_not_ask_to_approve_a_section_switched_off(
    hub: Path, tmp_path: Path
) -> None:
    from cc_hub.reports import save_section

    _hub_with_sections(hub, approved=False)
    save_section(hub, "mail/daily", False)
    assert _reports_check(hub, tmp_path).status == "ok"


def test_reports_check_leaves_an_unreadable_hub_toml_to_the_hub_toml_check(
    hub: Path, tmp_path: Path
) -> None:
    (hub / "hub.toml").write_text("[hub\n", encoding="utf-8")
    check = _reports_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "hub.toml unreadable; see hub-toml")


def test_reports_check_leaves_a_missing_hub_toml_to_the_hub_toml_check(
    hub: Path, tmp_path: Path
) -> None:
    (hub / "hub.toml").unlink()
    check = _reports_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "hub.toml unreadable; see hub-toml")


def test_reports_check_leaves_a_broken_apps_lock_to_the_apps_check(
    hub: Path, tmp_path: Path
) -> None:
    (hub / "apps.lock").write_text("[apps\n", encoding="utf-8")
    check = _reports_check(hub, tmp_path)
    assert (check.status, check.message) == ("ok", "apps.lock unreadable; see apps")
