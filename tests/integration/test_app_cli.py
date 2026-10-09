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
