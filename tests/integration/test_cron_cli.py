# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.cron import reregister_steps
from cc_hub.cronoverrides import load, save
from cc_hub.crontasks import rows
from cc_hub.gitops import run_git
from tests.conftest import write


def run(hub: Path, *args: str):
    return CliRunner().invoke(app, ["--hub", str(hub), *args])


def git_log_subject(hub: Path) -> str:
    return run_git(hub, "log", "-1", "--format=%s").stdout.strip()


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


def test_set_writes_commits_and_prints_steps(git_hub: Path) -> None:
    r = run(git_hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 0, r.output
    assert load(git_hub)["memory-consolidate"] == {"schedule": "30 2 * * *"}
    assert git_log_subject(git_hub) == "cc-hub: cron set memory-consolidate"
    assert "cc-connect cron del" in r.stdout and '--cron "30 2 * * *"' in r.stdout
    assert r.stdout.splitlines()[0] == "next, in a direct chat with the user:"


def test_set_stores_the_expression_single_spaced(git_hub: Path) -> None:
    r = run(git_hub, "cron", "set", "memory-consolidate", "  30   2 * * *  ")
    assert r.exit_code == 0, r.output
    assert load(git_hub)["memory-consolidate"] == {"schedule": "30 2 * * *"}
    assert '--cron "30 2 * * *"' in r.stdout


def test_off_then_on_then_reset(git_hub: Path) -> None:
    off = run(git_hub, "cron", "set", "memory-consolidate", "--off")
    assert load(git_hub)["memory-consolidate"] == {"enabled": False}
    assert "cc-connect cron del" in off.stdout and "cron add" not in off.stdout
    out = run(git_hub, "cron", "set", "memory-consolidate", "--on").stdout
    assert load(git_hub)["memory-consolidate"] == {"enabled": True} and "cron add" in out
    run(git_hub, "cron", "reset", "memory-consolidate")
    assert "memory-consolidate" not in load(git_hub)
    assert git_log_subject(git_hub) == "cc-hub: cron reset memory-consolidate"


def test_off_keeps_a_time_override_and_a_time_keeps_off(hub: Path) -> None:
    run(hub, "cron", "set", "memory-consolidate", "0 1 * * *")
    run(hub, "cron", "set", "memory-consolidate", "--off")
    assert load(hub)["memory-consolidate"] == {"schedule": "0 1 * * *", "enabled": False}
    run(hub, "cron", "set", "memory-consolidate", "0 2 * * *")
    assert load(hub)["memory-consolidate"] == {"schedule": "0 2 * * *", "enabled": False}
    run(hub, "cron", "set", "memory-consolidate", "--on")
    assert load(hub)["memory-consolidate"] == {"schedule": "0 2 * * *", "enabled": True}


@pytest.mark.parametrize(
    "args, words",
    [
        (["no-such-task", "0 1 * * *"], "no task"),
        (["memory-consolidate", "0 3 * *"], "five"),
        (["memory-consolidate"], "one of"),
        (["memory-consolidate", "0 1 * * *", "--off"], "one of"),
        (["memory-consolidate", "--on", "--off"], "one of"),
    ],
)
def test_set_errors_write_nothing(git_hub: Path, args: list[str], words: str) -> None:
    before = (git_hub / "hub.toml").read_bytes()
    r = run(git_hub, "cron", "set", *args)
    assert r.exit_code == 1 and words in r.stderr
    assert (git_hub / "hub.toml").read_bytes() == before


def test_set_on_a_task_with_a_broken_definition_is_refused(hub: Path) -> None:
    write(hub / "cron/broken.md", "---\ndefault: true\n---\n")
    before = (hub / "hub.toml").read_bytes()
    r = run(hub, "cron", "set", "broken", "0 1 * * *")
    assert r.exit_code == 1 and "cron/broken.md: schedule is required" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_set_time_on_on_demand_task_is_refused(hub_with_mail: Path) -> None:
    hub = hub_with_mail
    before = (hub / "hub.toml").read_bytes()
    r = run(hub, "cron", "set", "mail/triage", "0 1 * * *")
    assert r.exit_code == 1 and "on-demand" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before

    off = run(hub, "cron", "set", "mail/triage", "--off")
    assert off.exit_code == 0, off.output
    assert load(hub)["mail/triage"] == {"enabled": False}
    assert "cc-connect cron del" in off.stdout and "cron add" not in off.stdout

    on = run(hub, "cron", "set", "mail/triage", "--on")
    assert on.exit_code == 0, on.output
    assert "cron edit <id> enabled false" in on.stdout


def test_set_a_script_task_prints_its_exec_registration(hub_with_mail: Path) -> None:
    r = run(hub_with_mail, "cron", "set", "mail/poll", "0 8 * * *")
    assert r.exit_code == 0, r.output
    assert '--cron "0 8 * * *" --exec "uv run apps/mail/scripts/mk.py poll"' in r.stdout
    assert "cron edit <id> mute true" in r.stdout


def test_reset_of_leftover_override_for_missing_task(hub: Path) -> None:
    save(hub, "gone/task", {"schedule": "0 1 * * *"})
    r = run(hub, "cron", "reset", "gone/task")
    assert r.exit_code == 0, r.output
    assert "gone/task" not in load(hub)
    assert "cc-connect cron del" in r.stdout and "cron add" not in r.stdout
    assert "hub:gone/task" in r.stdout


def test_reset_without_an_override_says_so_and_commits_nothing(git_hub: Path) -> None:
    before = git_log_subject(git_hub)
    r = run(git_hub, "cron", "reset", "memory-consolidate")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "no override for memory-consolidate"
    assert git_log_subject(git_hub) == before


def test_reset_prints_the_steps_for_the_file_time(hub: Path) -> None:
    run(hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    r = run(hub, "cron", "reset", "memory-consolidate")
    assert r.exit_code == 0, r.output
    assert '--cron "0 3 * * *"' in r.stdout and "30 2" not in r.stdout


def test_set_commits_only_hub_toml(git_hub: Path) -> None:
    write(git_hub / "notes.txt", "unrelated\n")
    run(git_hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    files = run_git(git_hub, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["hub.toml"]
    assert "?? notes.txt" in run_git(git_hub, "status", "--short").stdout


def test_set_keeps_the_rest_of_hub_toml(hub: Path) -> None:
    path = hub / "hub.toml"
    path.write_bytes(path.read_bytes() + b"\r\n# my note\r\n")
    old = path.read_bytes().decode("utf-8")
    r = run(hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 0, r.output
    assert path.read_bytes().decode("utf-8").startswith(old)


def test_set_with_a_broken_hub_toml_fails(hub: Path) -> None:
    (hub / "hub.toml").write_text("[cron\n", encoding="utf-8")
    r = run(hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 1 and "hub.toml" in r.stderr


def test_set_in_a_hub_path_with_spaces_and_cjk(git_hub: Path) -> None:
    assert " " in git_hub.name and not git_hub.name.isascii()
    r = run(git_hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 0, r.output
    assert "warning" not in r.stderr
    assert git_log_subject(git_hub) == "cc-hub: cron set memory-consolidate"


def test_a_failed_commit_is_a_warning_not_an_error(git_hub: Path, monkeypatch) -> None:
    monkeypatch.setattr("cc_hub.gitops.commit_paths", lambda *a, **k: "not committed: boom")
    r = run(git_hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 0, r.output
    assert "warning: not committed: boom" in r.stderr
    assert load(git_hub)["memory-consolidate"] == {"schedule": "30 2 * * *"}


def test_a_busy_hub_is_an_error(hub: Path) -> None:
    from cc_hub.apps import hub_lock

    before = (hub / "hub.toml").read_bytes()
    with hub_lock(hub):
        r = run(hub, "cron", "set", "memory-consolidate", "30 2 * * *")
    assert r.exit_code == 1 and "another cc-hub" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_reregister_steps_for_a_row_that_is_off_or_gone() -> None:
    steps = reregister_steps(None, "gone/task")
    assert steps[0] == "next, in a direct chat with the user:"
    assert steps[1].strip().startswith("cc-connect cron list")
    assert "hub:gone/task" in steps[1] and steps[2].strip() == "cc-connect cron del <id>"
    assert len(steps) == 3
    off = {"enabled": False, "commands": ["cc-connect cron add ..."]}
    assert reregister_steps(off, "x") == reregister_steps(None, "x")
    on = {"enabled": True, "commands": ["cc-connect cron add ...", "cc-connect cron edit <id> x"]}
    assert reregister_steps(on, "x")[3:] == [
        "  cc-connect cron add ...",
        "  cc-connect cron edit <id> x",
    ]


def test_wake_prints_the_job_id(hub_with_mail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list = []

    def fake_wake(hub: Path, name: str) -> str:
        woken.append((hub, name))
        return "a1b2c3"

    monkeypatch.setattr("cc_hub.crontasks.wake", fake_wake)
    r = run(hub_with_mail, "cron", "wake", "mail/triage")
    assert r.exit_code == 0, r.output
    assert r.stdout == "woke hub:mail/triage (a1b2c3)\n"
    assert woken == [(hub_with_mail, "mail/triage")]


def test_wake_failure_goes_to_stderr_with_exit_1(
    hub_with_mail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # an empty PATH: cc-connect is not found, and nothing real is run
    monkeypatch.setenv("PATH", "")
    r = run(hub_with_mail, "cron", "wake", "mail/triage")
    assert r.exit_code == 1
    assert r.stdout == "" and "cc-connect" in r.stderr and "not found" in r.stderr


def test_wake_refuses_a_task_that_is_not_on_demand(hub_with_mail: Path) -> None:
    r = run(hub_with_mail, "cron", "wake", "mail/poll")
    assert r.exit_code == 1
    assert r.stdout == "" and "not an on-demand task" in r.stderr


def test_wake_with_an_unreadable_hub_toml_fails(hub: Path) -> None:
    (hub / "hub.toml").write_text("[cron\n", encoding="utf-8")
    r = run(hub, "cron", "wake", "mail/triage")
    assert r.exit_code == 1 and "hub.toml" in r.stderr
