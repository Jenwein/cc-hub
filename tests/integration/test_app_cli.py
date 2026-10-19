# -*- coding: utf-8 -*-
import json
from pathlib import Path

from typer.testing import CliRunner

from cc_hub.cli import app


def run(hub: Path, *args: str):
    return CliRunner().invoke(app, ["--hub", str(hub), *args])


def test_tap_and_app_commands_end_to_end(hub: Path, ledger_tap: Path, tap_commit) -> None:
    r = run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps")
    assert r.exit_code == 0, r.output
    assert "added tap my-apps" in r.output and "(1 app)" in r.output
    assert json.loads(run(hub, "tap", "list", "--json").stdout)[0]["apps"] == 1
    assert "my-apps/ledger  0.1.0  Plain-text bookkeeping" in run(hub, "app", "search").output

    r = run(hub, "app", "install", "my-apps/ledger")
    assert r.exit_code == 0, r.output
    assert "hub:ledger/monthly: 0 9 1 * * (default, new_per_run)" in r.output
    assert "beancount (cc-hub-test-no-such-bin): uv tool install beancount" in r.output
    assert "nothing changed yet" in r.output
    assert not (hub / "apps").exists()
    confirm = r.output.strip().splitlines()[-1].split()
    assert confirm[:5] == ["cc-hub", "app", "install", "my-apps/ledger", "--ref"]
    assert confirm[-1] == "--yes"

    r = run(hub, *confirm[1:])
    assert r.exit_code == 0, r.output
    assert "installed ledger 0.1.0" in r.output and "setup pending" in r.output
    assert json.loads(run(hub, "app", "list", "--json").stdout)[0]["setup"] == "pending"
    assert run(hub, "app", "setup-state", "ledger", "done").exit_code == 0
    assert "setup: done" in run(hub, "app", "list").output
    assert "is up to date" in run(hub, "app", "update", "ledger").output

    tap_commit(ledger_tap, {"ledger/SETUP.md": "# Setup v2\n"})
    r = run(hub, "app", "update", "ledger")
    assert "M SETUP.md" in r.output and "Setup v2" in r.output
    confirm = r.output.strip().splitlines()[-1].split()
    r = run(hub, *confirm[1:])
    assert r.exit_code == 0, r.output
    assert "setup pending" in r.output

    r = run(hub, "app", "remove", "ledger")
    assert "hub:ledger/monthly" in r.output and (hub / "apps" / "ledger").exists()
    r = run(hub, "app", "remove", "ledger", "--yes")
    assert r.exit_code == 0 and not (hub / "apps" / "ledger").exists()
    assert run(hub, "tap", "remove", "my-apps").exit_code == 0


def test_app_errors_exit_1(hub: Path) -> None:
    r = run(hub, "app", "install", "nowhere/ledger")
    assert r.exit_code == 1
    assert "no tap named" in r.output
    assert run(hub, "app", "update").exit_code == 1
    assert run(hub, "app", "setup-state", "ledger", "done").exit_code == 1


def test_sync_exits_1_when_an_app_cannot_be_restored(hub: Path) -> None:
    from cc_hub.applock import load_lock, save_lock

    lock = load_lock(hub)
    lock.apps["ghost"] = {"tap": "gone", "commit": "f" * 40, "version": "1"}
    save_lock(hub, lock)
    r = run(hub, "app", "sync")
    assert r.exit_code == 1
    assert "failed\tghost" in r.output


def test_update_ignores_tap_commits_that_do_not_touch_the_app(
    hub: Path, ledger_tap: Path, tap_commit
) -> None:
    from cc_hub.applock import load_lock

    assert run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps").exit_code == 0
    assert run(hub, "app", "install", "my-apps/ledger", "--yes").exit_code == 0
    installed = load_lock(hub).apps["ledger"]["commit"]

    tap_commit(ledger_tap, {"README.md": "only the readme\n"})
    r = run(hub, "app", "update", "ledger")
    assert r.exit_code == 0, r.output
    assert f"ledger is up to date ({installed[:7]})" in r.output
    assert "changed files:" not in r.output

    r = run(hub, "app", "update", "ledger", "--yes")
    assert r.exit_code == 0, r.output
    assert f"ledger is up to date ({installed[:7]})" in r.output
    assert "updated" not in r.output
    assert load_lock(hub).apps["ledger"]["commit"] == installed
    assert not (hub / ".cc-hub" / "backups" / "apps").exists()


def test_update_all_continues_past_a_failing_app(
    hub: Path, ledger_tap: Path, make_tap, tmp_path: Path
) -> None:
    from cc_hub.applock import load_lock, save_lock

    agenda = make_tap(
        "agenda-apps",
        {"agenda/app.toml": '[app]\nname = "agenda"\nversion = "1.0.0"\ndescription = "Agenda"\n'},
    )
    assert run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps").exit_code == 0
    assert run(hub, "tap", "add", agenda.as_uri(), "--name", "agenda-apps").exit_code == 0
    assert run(hub, "app", "install", "my-apps/ledger", "--yes").exit_code == 0
    assert run(hub, "app", "install", "agenda-apps/agenda", "--yes").exit_code == 0

    lock = load_lock(hub)
    lock.taps["agenda-apps"] = {"path": str(tmp_path / "gone")}
    save_lock(hub, lock)

    r = run(hub, "app", "update", "--all")
    assert r.exit_code == 1
    assert "agenda: tap agenda-apps:" in r.output and "does not exist" in r.output
    assert "ledger is up to date" in r.output

    r = run(hub, "app", "update", "agenda")
    assert r.exit_code == 1
    assert "tap agenda-apps:" in r.output


def test_app_remove_lists_and_drops_the_overrides(git_hub_with_plans: Path) -> None:
    from cc_hub.cronoverrides import save
    from cc_hub.gitops import commit_paths

    hub = git_hub_with_plans
    save(hub, "plans/morning", {"schedule": "0 7 * * *"})
    save(hub, "ledger/prices", {"enabled": False})
    assert commit_paths(hub, ["hub.toml", "apps.lock"], "cc-hub: set up") is None
    r = run(hub, "app", "remove", "plans")
    assert r.exit_code == 0, r.output
    assert "overrides: plans/morning" in r.output and "ledger/prices" not in r.output
    assert (hub / "apps" / "plans").exists()
    r = run(hub, "app", "remove", "plans", "--yes")
    assert r.exit_code == 0, r.output
    toml = (hub / "hub.toml").read_text(encoding="utf-8")
    assert "plans/morning" not in toml and "ledger/prices" in toml


def test_app_remove_without_overrides_says_none(hub_with_plans: Path) -> None:
    r = run(hub_with_plans, "app", "remove", "plans")
    assert r.exit_code == 0, r.output
    assert "overrides: none" in r.output


SECTIONS = {
    "ledger/reports/daily.md": '---\ncommand: "ledger-report daily"\n---\n',
    "ledger/reports/weekly.md": "---\n---\nSummarise the week.\n",
}


def test_app_install_overview_lists_the_report_sections(
    hub: Path, ledger_tap: Path, tap_commit
) -> None:
    assert run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps").exit_code == 0
    r = run(hub, "app", "install", "my-apps/ledger")
    assert r.exit_code == 0, r.output
    assert "report sections: none" in r.output

    tap_commit(ledger_tap, SECTIONS)
    r = run(hub, "app", "install", "my-apps/ledger")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    start = lines.index("report sections:")
    assert lines[start : start + 3] == [
        "report sections:",
        "  daily: command ledger-report daily",
        "  weekly: instructions",
    ]


def test_app_install_refuses_a_report_file_that_is_not_a_period(
    hub: Path, ledger_tap: Path, tap_commit
) -> None:
    tap_commit(ledger_tap, {"ledger/reports/hourly.md": "---\n---\n"})
    assert run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps").exit_code == 0
    r = run(hub, "app", "install", "my-apps/ledger", "--yes")
    assert r.exit_code == 1
    assert "ledger/reports/hourly.md: hourly is not a report period" in r.output
    assert not (hub / "apps").exists()


def test_app_update_preview_shows_a_changed_report_section(
    hub: Path, ledger_tap: Path, tap_commit
) -> None:
    tap_commit(ledger_tap, SECTIONS)
    assert run(hub, "tap", "add", ledger_tap.as_uri(), "--name", "my-apps").exit_code == 0
    assert run(hub, "app", "install", "my-apps/ledger", "--yes").exit_code == 0
    daily_v2 = '---\ncommand: "ledger-report daily -v"\n---\n'
    tap_commit(ledger_tap, {"ledger/reports/daily.md": daily_v2})
    r = run(hub, "app", "update", "ledger")
    assert r.exit_code == 0, r.output
    assert "M reports/daily.md" in r.output
    assert "--- app.toml, SETUP.md, REMOVE.md, skills/, scripts/, cron/, reports/ ---" in r.output
    assert '+command: "ledger-report daily -v"' in r.output


def test_app_remove_lists_and_drops_the_report_settings(git_hub_with_plans: Path) -> None:
    from cc_hub import reports
    from cc_hub.gitops import commit_paths

    hub = git_hub_with_plans
    reports.save_section(hub, "plans/daily", False)
    reports.save_section(hub, "ledger/monthly", False)
    assert commit_paths(hub, ["hub.toml", "apps.lock"], "cc-hub: set up") is None
    r = run(hub, "app", "remove", "plans")
    assert r.exit_code == 0, r.output
    assert "report settings: plans/daily (removed from hub.toml)" in r.output
    assert "ledger/monthly" not in r.output
    assert (hub / "apps" / "plans").exists()
    r = run(hub, "app", "remove", "plans", "--yes")
    assert r.exit_code == 0, r.output
    toml = (hub / "hub.toml").read_text(encoding="utf-8")
    assert "plans/daily" not in toml and "ledger/monthly" in toml


def test_app_remove_without_report_settings_says_none(hub_with_plans: Path) -> None:
    r = run(hub_with_plans, "app", "remove", "plans")
    assert r.exit_code == 0, r.output
    assert "report settings: none" in r.output


def test_app_remove_warns_when_the_report_state_stays(
    hub_with_plans: Path, monkeypatch
) -> None:
    from contextlib import contextmanager

    from cc_hub import reportstate

    @contextmanager
    def busy(_hub):
        raise TimeoutError("the reports state is busy; try again shortly")
        yield  # pragma: no cover

    monkeypatch.setattr(reportstate, "state_lock", busy)
    r = run(hub_with_plans, "app", "remove", "plans", "--yes")
    assert r.exit_code == 0, r.output
    assert "removed plans" in r.output and "reports state is busy" in r.output
    assert not (hub_with_plans / "apps" / "plans").exists()
