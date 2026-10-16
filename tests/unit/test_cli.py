# -*- coding: utf-8 -*-
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from cc_hub import __version__
from cc_hub.cli import app

HOOK_EVENTS = [
    b'{"session_id": "s", "transcript_path": "/nowhere/t.jsonl", '
    b'"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}',
    b"not json at all \x00\xff",
    b"",
]

# cli.main as the console script runs it; exit 3 if anything heavy was imported on the way
FAST_PATH = (
    "import sys\n"
    "sys.argv = ['cc-hub', 'cron', 'guard']\n"
    "from cc_hub.cli import main\n"
    "main()\n"
    "heavy = ('typer', 'click', 'rich', 'cc_hub.commands.root', 'cc_hub.commands.cron')\n"
    "sys.exit(3 if any(m in sys.modules for m in heavy) else 0)\n"
)


@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_cron_guard_fast_path_says_nothing_and_skips_typer(event: bytes) -> None:
    proc = subprocess.run([sys.executable, "-c", FAST_PATH], input=event, capture_output=True)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_cron_guard_through_the_entry_point_exits_0(event: bytes) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "cc_hub", "cron", "guard"], input=event, capture_output=True
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


@pytest.mark.parametrize("event", HOOK_EVENTS)
@pytest.mark.parametrize(
    "args",
    [
        ["cron", "guard"],
        ["--hub", "no-such-hub", "cron", "guard"],
        ["cron", "guard", "extra", "--flag"],
    ],
)
def test_cron_guard_command_exits_0_with_no_output(event: bytes, args: list[str]) -> None:
    result = CliRunner().invoke(app, args, input=event)
    assert (result.exit_code, result.stdout) == (0, ""), result.output


def test_cron_guard_is_hidden() -> None:
    result = CliRunner().invoke(app, ["cron", "--help"])
    assert result.exit_code == 0 and "guard" not in result.output


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
        "feedback", "cron", "report",
    }
