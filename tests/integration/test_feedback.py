# -*- coding: utf-8 -*-
import json
import platform
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub import __version__, apps
from cc_hub.applock import load_lock, save_lock
from cc_hub.cli import app
from cc_hub.commands.feedback import feedback_info, package_issues_url

TRACKER = "https://github.com/Jenwein/cc-hub/issues"


def private_bits(hub: Path) -> list[str]:
    bits = [str(Path.home()), str(hub), hub.as_posix()]
    node = platform.node()
    return bits + ([node] if len(node) > 3 else [])


def test_the_package_names_its_issue_tracker() -> None:
    assert package_issues_url() == TRACKER


def test_feedback_about_cc_hub(hub: Path) -> None:
    (hub / ".claude" / "skills").mkdir(parents=True)
    info = feedback_info(hub, issues_url=TRACKER)
    assert info["target"] == TRACKER
    assert info["github_repo"] == "Jenwein/cc-hub"
    assert info["new_issue_url"] == TRACKER + "/new"
    env = info["environment"]
    assert env["cc-hub"] == __version__
    assert env["agents"] == ["claude"]
    assert set(env) == {"cc-hub", "python", "os", "agents"}
    text = json.dumps(info)
    for bit in private_bits(hub):
        assert bit not in text


@pytest.fixture
def ledger_installed(hub: Path, ledger_tap: Path, register_tap) -> Path:
    register_tap(hub, "my-apps", ledger_tap)
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    return hub


def set_app_issues(hub: Path, value: str) -> None:
    """Add an `issues` line to the installed ledger app's [app] table."""
    toml = hub / "apps" / "ledger" / "app.toml"
    issues = f'issues = "{value}"\n'
    description = 'description = "Plain-text bookkeeping"\n'
    text = toml.read_text(encoding="utf-8").replace(description, description + issues)
    toml.write_text(text, encoding="utf-8")


def test_feedback_about_an_app_from_a_github_tap(ledger_installed: Path) -> None:
    hub = ledger_installed
    lock = load_lock(hub)
    lock.taps["my-apps"] = {"url": "https://u:tok@github.com/you/my-apps.git"}
    save_lock(hub, lock)
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://github.com/you/my-apps/issues"
    assert info["github_repo"] == "you/my-apps"
    app_env = info["environment"]["app"]
    assert app_env["source"] == "https://github.com/you/my-apps.git"
    assert app_env["name"] == "ledger" and app_env["version"] == "0.1.0"
    assert app_env["setup"] == "pending"
    assert "tok" not in json.dumps(info)


def test_feedback_about_an_app_with_its_own_tracker_or_none(ledger_installed: Path) -> None:
    hub = ledger_installed
    info = feedback_info(hub, "ledger")
    assert info["target"] is None and info["github_repo"] is None
    assert info["environment"]["app"]["source"] == "a local tap"
    set_app_issues(hub, "https://gitlab.com/you/apps/-/issues")
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://gitlab.com/you/apps/-/issues"
    assert info["new_issue_url"] is None and info["github_repo"] is None
    with pytest.raises(apps.AppError):
        feedback_info(hub, "nope")


def test_feedback_cli(hub: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hub), "feedback"])
    assert r.exit_code == 0, r.output
    assert f"report to: {TRACKER}" in r.output
    assert 'gh issue create -R Jenwein/cc-hub --title "<title>" --body-file <file>' in r.output
    assert "environment:" in r.output and f"cc-hub: {__version__}" in r.output
    data = json.loads(CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--json"]).stdout)
    assert data["github_repo"] == "Jenwein/cc-hub"
    assert CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "nope"]).exit_code == 1


def test_an_apps_own_issues_url_loses_its_credentials(ledger_installed: Path) -> None:
    hub = ledger_installed
    set_app_issues(hub, "https://u:tok@github.com/you/repo/issues")
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://github.com/you/repo/issues"
    assert info["new_issue_url"] == "https://github.com/you/repo/issues/new"
    assert info["github_repo"] == "you/repo"
    assert "tok" not in json.dumps(info)


def test_new_issue_url_comes_from_the_repo(ledger_installed: Path) -> None:
    hub = ledger_installed
    set_app_issues(hub, "https://github.com/you/repo")
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://github.com/you/repo"
    assert info["new_issue_url"] == "https://github.com/you/repo/issues/new"


def test_feedback_cli_says_a_local_tap_app_is_the_users_own(ledger_installed: Path) -> None:
    hub = ledger_installed
    r = CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "ledger"])
    assert r.exit_code == 0, r.output
    assert "no issue tracker: ledger is the user's own" in r.output
    assert "environment:" in r.output
    as_json = CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "ledger", "--json"])
    assert json.loads(as_json.stdout)["environment"]["app"]["kind"] == "local tap"


def test_feedback_cli_says_a_remote_tap_without_a_tracker_is_unknown(
    ledger_installed: Path,
) -> None:
    hub = ledger_installed
    lock = load_lock(hub)
    lock.taps["my-apps"] = {"url": "https://gitlab.com/you/apps.git"}
    save_lock(hub, lock)
    r = CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "ledger"])
    assert r.exit_code == 0, r.output
    assert "no issue tracker known for ledger; its tap is https://gitlab.com/you/apps.git" in (
        r.output
    )
    assert "the user's own" not in r.output


def test_a_linked_app_is_the_users_own(hub: Path, tmp_path: Path) -> None:
    dev = tmp_path / "dev" / "notes"
    dev.mkdir(parents=True)
    (dev / "app.toml").write_text(
        '[app]\nname = "notes"\nversion = "0.1.0"\ndescription = "Notes"\n', encoding="utf-8"
    )
    apps.install(hub, apps.plan_install(hub, str(dev), link=True))
    info = feedback_info(hub, "notes")
    assert info["target"] is None
    assert info["environment"]["app"]["kind"] == "link"
    r = CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "notes"])
    assert "no issue tracker: notes is the user's own" in r.output
