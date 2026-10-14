# -*- coding: utf-8 -*-
from typer.testing import CliRunner

from cc_hub import __version__
from cc_hub.cli import app


def test_version_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_no_args_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_app_does_not_dump_locals_in_tracebacks() -> None:
    from cc_hub.cli import app as cli_app

    assert cli_app.pretty_exceptions_show_locals is False


def test_where_without_hub_still_prints_package(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CC_HUB_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["where"])
    assert result.exit_code == 1
    assert "package:" in result.stdout
    assert "hub: not found" in result.stdout


def _command_names() -> set[str]:
    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    return names | {g.name for g in app.registered_groups}


def test_cli_exposes_exactly_the_hub_commands() -> None:
    assert _command_names() == {
        "init", "doctor", "update", "memory", "link", "where", "version", "tap", "app",
        "feedback", "cron",
    }
