# -*- coding: utf-8 -*-
import json
from pathlib import Path

from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.cronoverrides import save
from cc_hub.crontasks import rows
from tests.conftest import write


def run(hub: Path, *args: str):
    return CliRunner().invoke(app, ["--hub", str(hub), *args])


def test_list_json_is_the_rows(hub_with_mail: Path) -> None:
    save(hub_with_mail, "mail/poll", {"schedule": "0 8 * * *"})
    r = run(hub_with_mail, "cron", "list", "--json")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == rows(hub_with_mail)
    assert {x["name"] for x in json.loads(r.stdout)} == {
        "memory-consolidate", "mail/poll", "mail/triage",
    }


def test_list_prints_one_line_per_task(hub_with_mail: Path) -> None:
    save(hub_with_mail, "mail/poll", {"schedule": "0 8 * * *"})
    save(hub_with_mail, "memory-consolidate", {"enabled": False})
    r = run(hub_with_mail, "cron", "list")
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines() == [
        "mail/poll  exec  0 8 * * * (overridden, file: */5 * * * *)  on",
        "mail/triage  on_demand  on demand  on",
        "memory-consolidate  prompt  0 3 * * *  off",
    ]


def test_list_shows_an_error_row_as_an_error_line(hub: Path) -> None:
    write(hub / "cron/broken.md", "---\ndefault: true\n---\n")
    r = run(hub, "cron", "list")
    assert r.exit_code == 0, r.output
    assert "broken  error: cron/broken.md: schedule is required" in r.stdout


def test_list_with_an_unreadable_hub_toml_fails(hub: Path) -> None:
    (hub / "hub.toml").write_text("[cron\n", encoding="utf-8")
    r = run(hub, "cron", "list")
    assert r.exit_code == 1 and "hub.toml" in r.output


def test_list_with_a_broken_lock_fails(hub: Path) -> None:
    write(hub / "apps.lock", "[apps\n")
    r = run(hub, "cron", "list")
    assert r.exit_code == 1 and "apps.lock" in r.output


def test_cron_group_is_documented_in_help() -> None:
    r = CliRunner().invoke(app, ["--help"])
    assert "cron" in r.output and "Scheduled tasks" in r.output


def test_list_in_a_hub_with_a_non_ascii_path(git_hub_with_mail: Path) -> None:
    r = run(git_hub_with_mail, "cron", "list", "--json")
    assert r.exit_code == 0, r.output
    assert [x["name"] for x in json.loads(r.stdout)] == [
        "mail/poll", "mail/triage", "memory-consolidate",
    ]
