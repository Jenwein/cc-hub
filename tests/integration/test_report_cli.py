# -*- coding: utf-8 -*-
import json
import shlex
import sys
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub import apps, cronoverrides, reportbuild, reports, reportstate
from cc_hub.cli import app
from cc_hub.gitops import run_git
from cc_hub.reports import ReportError
from tests.conftest import fake_app, write

REPORT_CRON = '---\nschedule: "0 8 * * *"\ndefault: false\nsession: new_per_run\n---\nx\n'
MAIL = "uv run mail.py"
SECRET = "SECRET-BODY-42"
UNKNOWN = "unknown period {}; use daily, weekly, monthly, quarterly or yearly"


def run(hub: Path, *args: str, input: str | bytes | None = None):
    return CliRunner().invoke(app, ["--hub", str(hub), *args], input=input)


def now() -> datetime:
    return datetime.now().astimezone()


def git_log_subject(hub: Path) -> str:
    return run_git(hub, "log", "-1", "--format=%s").stdout.strip()


def periods_on(hub: Path, *periods: str) -> None:
    """The report tasks exist for every period (a later task ships them); only `periods` are on."""
    for p in reports.PERIODS:
        write(hub / f"cron/report-{p}.md", REPORT_CRON)
    for p in periods:
        cronoverrides.save(hub, f"report-{p}", {"enabled": True})


def install(hub: Path, name: str, period: str, text: str) -> None:
    if (hub / "apps" / name).exists():  # fake_app registers an app once
        write(hub / "apps" / name / "reports" / f"{period}.md", text)
    else:
        fake_app(hub, name, {f"reports/{period}.md": text})


def instruction(hub: Path, name: str, period: str = "daily", title: str | None = None) -> None:
    head = f'title: "{title}"\n' if title else ""
    install(hub, name, period, f"---\n{head}---\nWrite the section.\n")


def command(hub: Path, name: str, period: str = "daily", cmd: str = MAIL) -> None:
    install(hub, name, period, f'---\ncommand: "{cmd}"\ntitle: "{name}"\n---\n')


def echo_cmd(text: str) -> str:
    """A command line that prints `text`, with no double quote in it: a section file can hold it."""
    return shlex.join([sys.executable, "-c", "import sys;print(sys.argv[1])", text])


class Collector:
    """A sender that keeps what it is given, standing in for cc-connect."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def __call__(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Collector:
    collector = Collector()
    monkeypatch.setattr(reportbuild, "cc_connect_sender", lambda: collector)
    return collector


@pytest.fixture
def busy_state(monkeypatch: pytest.MonkeyPatch):
    """Make a busy reports state fail fast instead of waiting its full time."""
    monkeypatch.setattr(reportstate, "STATE_LOCK_WAIT", 0.3)
    monkeypatch.setattr(reportstate, "LOCK_POLL", 0.05)


# --- the group ---


def test_report_group_in_help() -> None:
    r = CliRunner().invoke(app, ["--help"])
    assert "report" in r.output
    assert "Reports: daily to yearly digests that apps add sections to." in r.output
    sub = CliRunner().invoke(app, ["report", "--help"])
    for name in ("list", "plan", "put", "send", "note", "section", "language", "approve"):
        assert name in sub.output, name


# --- list ---


def test_list_json_periods_and_language(hub: Path) -> None:
    periods_on(hub, "daily")
    cronoverrides.save(hub, "report-weekly", {"schedule": "0 9 * * 1"})
    r = run(hub, "report", "list", "--json")
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["language"] == "en" and data["sections"] == []
    assert [p["period"] for p in data["periods"]] == list(reports.PERIODS)
    assert data["periods"][0] == {
        "period": "daily", "task": "report-daily", "schedule": "0 8 * * *", "on": True,
    }
    assert data["periods"][1] == {
        "period": "weekly", "task": "report-weekly", "schedule": "0 9 * * 1", "on": False,
    }


def test_list_json_without_report_tasks_has_no_schedule(hub: Path) -> None:
    data = json.loads(run(hub, "report", "list", "--json").stdout)
    assert all(p["schedule"] is None and p["on"] is False for p in data["periods"])
    assert data["periods"][0]["task"] == "report-daily"


def test_list_json_language_is_the_one_in_hub_toml(hub: Path) -> None:
    reports.save_language(hub, "zh-CN")
    assert json.loads(run(hub, "report", "list", "--json").stdout)["language"] == "zh-CN"


def test_list_json_sections(hub: Path) -> None:
    command(hub, "mail")
    instruction(hub, "diary", title="Diary")
    instruction(hub, "quiet", "weekly")
    write(hub / "apps/mail/reports/bogus.md", "---\n---\n")
    write(hub / "apps/diary/reports/weekly.md", "---\ncommand:\n---\n")
    reports.save_section(hub, "quiet/weekly", False)
    reportstate.approve(hub, "mail", {"daily": MAIL})
    r = run(hub, "report", "list", "--json")
    assert r.exit_code == 0, r.output
    rows = {(s["app"], s["period"]): s for s in json.loads(r.stdout)["sections"]}
    assert rows[("mail", "daily")] == {
        "app": "mail", "period": "daily", "kind": "command", "title": "mail", "command": MAIL,
        "file": "apps/mail/reports/daily.md", "on": True, "approved": True, "error": None,
    }
    assert rows[("diary", "daily")]["kind"] == "instruction"
    assert rows[("diary", "daily")]["title"] == "Diary"
    assert rows[("diary", "daily")]["approved"] is None
    assert rows[("quiet", "weekly")]["on"] is False
    broken = rows[("mail", "bogus")]
    assert "bogus" in broken["error"]
    assert {broken[k] for k in ("kind", "title", "command", "on", "approved")} == {None}
    assert broken["file"] == "apps/mail/reports/bogus.md"
    assert rows[("diary", "weekly")]["error"] and rows[("diary", "weekly")]["on"] is None


def test_list_json_command_that_changed_is_not_approved(hub: Path) -> None:
    command(hub, "mail")
    reportstate.approve(hub, "mail", {"daily": "uv run other.py"})
    data = json.loads(run(hub, "report", "list", "--json").stdout)
    assert data["sections"][0]["approved"] is False


def test_list_text_lines(hub: Path) -> None:
    periods_on(hub, "daily")
    command(hub, "mail")
    instruction(hub, "diary")
    write(hub / "apps/mail/reports/bogus.md", "---\n---\n")
    reportstate.approve(hub, "mail", {"daily": MAIL})
    reports.save_section(hub, "diary/daily", False)
    r = run(hub, "report", "list")
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert lines[:5] == [
        "daily  report-daily  0 8 * * *  on",
        "weekly  report-weekly  0 8 * * *  off",
        "monthly  report-monthly  0 8 * * *  off",
        "quarterly  report-quarterly  0 8 * * *  off",
        "yearly  report-yearly  0 8 * * *  off",
    ]
    assert lines[5:] == [
        "diary/daily  instruction  off",
        "mail/bogus  error: apps/mail/reports/bogus.md: bogus is not a report period "
        "(daily, weekly, monthly, quarterly, yearly)",
        "mail/daily  command  on  approved",
    ]


def test_list_text_marks_a_command_that_is_not_approved(hub: Path) -> None:
    command(hub, "mail")
    assert "mail/daily  command  on  not approved" in run(hub, "report", "list").stdout


def test_list_text_without_report_tasks(hub: Path) -> None:
    assert run(hub, "report", "list").stdout.splitlines()[0] == "daily  report-daily  -  off"


def test_list_with_a_broken_hub_toml_fails(hub: Path) -> None:
    (hub / "hub.toml").write_text("[report\n", encoding="utf-8")
    r = run(hub, "report", "list")
    assert r.exit_code == 1 and "hub.toml" in r.stderr


def test_list_with_a_broken_lock_fails(hub: Path) -> None:
    write(hub / "apps.lock", "[apps\n")
    r = run(hub, "report", "list")
    assert r.exit_code == 1 and "apps.lock" in r.stderr


# --- plan ---


def test_plan_json(hub: Path) -> None:
    periods_on(hub, "daily")
    command(hub, "mail")
    instruction(hub, "diary")
    r = run(hub, "report", "plan", "daily", "--json")
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["period"] == "daily" and data["empty"] is False and data["notes"] == 0
    assert [(s["app"], s["kind"], s["approved"]) for s in data["sections"]] == [
        ("diary", "instruction", None), ("mail", "command", False),
    ]
    assert {"language", "since", "until"} <= set(data)


def test_plan_text_summary(hub: Path) -> None:
    periods_on(hub, "daily")
    command(hub, "mail")
    instruction(hub, "diary")
    reportstate.approve(hub, "mail", {"daily": MAIL})
    reportstate.add_note(hub, "daily", "mail", "hello", now())
    r = run(hub, "report", "plan", "daily")
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert lines[0] == "daily: 2 section(s), 1 note(s)"
    assert lines[1].startswith("since ") and " until " in lines[1]
    assert lines[1].endswith(", language en")
    assert lines[2:] == ["  diary  instruction", "  mail  command  approved"]


def test_plan_text_of_an_empty_report(hub: Path) -> None:
    r = run(hub, "report", "plan", "weekly")
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines()[0] == "weekly: 0 section(s), 0 note(s)"
    assert r.stdout.splitlines()[-1] == "nothing to send"


def test_plan_text_marks_a_command_that_is_not_approved(hub: Path) -> None:
    command(hub, "mail")
    assert "  mail  command  not approved" in run(hub, "report", "plan", "daily").stdout


@pytest.mark.parametrize("sub", ["plan", "send"])
def test_unknown_period(hub: Path, sub: str) -> None:
    r = run(hub, "report", sub, "hourly")
    assert r.exit_code == 1
    assert r.stderr.strip() == UNKNOWN.format("hourly")


def test_plan_does_not_send_or_store_anything(hub: Path) -> None:
    periods_on(hub, "daily")
    instruction(hub, "diary")
    run(hub, "report", "plan", "daily")
    assert not (hub / "reports").exists()
    assert reportstate.last_run(reportstate.load_state(hub), "daily") is None


# --- put ---


def test_put_text(hub: Path) -> None:
    instruction(hub, "diary")
    r = run(hub, "report", "put", "daily", "diary", "--text", "Slept well. 睡得好")
    assert r.exit_code == 0, r.output
    assert reportstate.read_draft(hub, "daily", "diary") == "Slept well. 睡得好"
    assert r.stdout.strip() == "draft saved for diary/daily"


def test_put_reads_stdin_as_utf8(hub: Path) -> None:
    instruction(hub, "diary")
    r = run(hub, "report", "put", "daily", "diary", input="第一行\n第二行\n".encode())
    assert r.exit_code == 0, r.output
    assert reportstate.read_draft(hub, "daily", "diary") == "第一行\n第二行\n"


def test_put_text_wins_over_stdin(hub: Path) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "from option", input="from stdin")
    assert reportstate.read_draft(hub, "daily", "diary") == "from option"


def test_put_replaces_the_draft(hub: Path) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "one")
    run(hub, "report", "put", "daily", "diary", "--text", "two")
    assert reportstate.read_draft(hub, "daily", "diary") == "two"


def test_put_with_bytes_that_are_not_utf8_fails(hub: Path) -> None:
    instruction(hub, "diary")
    r = run(hub, "report", "put", "daily", "diary", input=b"\xff\xfe\xfa")
    assert r.exit_code == 1
    assert reportstate.read_draft(hub, "daily", "diary") == ""


def test_put_refuses_a_command_section(hub: Path) -> None:
    command(hub, "mail")
    r = run(hub, "report", "put", "daily", "mail", "--text", "x")
    assert r.exit_code == 1 and "mail/daily" in r.stderr and "command" in r.stderr
    assert reportstate.read_draft(hub, "daily", "mail") == ""


def test_put_refuses_a_section_that_is_off(hub: Path) -> None:
    instruction(hub, "diary")
    reports.save_section(hub, "diary/daily", False)
    r = run(hub, "report", "put", "daily", "diary", "--text", "x")
    assert r.exit_code == 1 and "switched off" in r.stderr
    assert reportstate.read_draft(hub, "daily", "diary") == ""


def test_put_refuses_a_section_that_does_not_exist(hub: Path) -> None:
    instruction(hub, "diary")
    r = run(hub, "report", "put", "weekly", "diary", "--text", "x")
    assert r.exit_code == 1 and "diary has no weekly report section" in r.stderr
    r = run(hub, "report", "put", "daily", "ghost", "--text", "x")
    assert r.exit_code == 1 and "ghost has no daily report section" in r.stderr
    assert not (hub / ".cc-hub/reports/drafts").exists()


def test_put_refuses_a_section_whose_file_is_broken(hub: Path) -> None:
    write(hub / "apps/diary/reports/daily.md", "---\ncommand:\n---\n")
    fake_app(hub, "diary", {})
    r = run(hub, "report", "put", "daily", "diary", "--text", "x")
    assert r.exit_code == 1 and "apps/diary/reports/daily.md" in r.stderr


def test_put_with_an_unknown_period(hub: Path) -> None:
    r = run(hub, "report", "put", "hourly", "diary", "--text", "x")
    assert r.exit_code == 1 and r.stderr.strip() == UNKNOWN.format("hourly")


def test_put_with_a_busy_state_is_an_error(hub: Path, busy_state) -> None:
    instruction(hub, "diary")
    with reportstate.state_lock(hub):
        r = run(hub, "report", "put", "daily", "diary", "--text", "x")
    assert r.exit_code == 1 and "busy" in r.stderr
    assert reportstate.read_draft(hub, "daily", "diary") == ""


# --- send ---


def test_send_sends_archives_and_counts(hub: Path, sent: Collector) -> None:
    periods_on(hub, "daily")
    instruction(hub, "diary", title="Diary")
    run(hub, "report", "put", "daily", "diary", "--text", f"all good {SECRET}")
    run(hub, "report", "note", "daily", "--from", "mail", "remember the milk")
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "sent: 1 section(s), 1 note(s)"
    assert len(sent.sent) == 1 and SECRET in sent.sent[0] and "remember the milk" in sent.sent[0]
    archives = list((hub / "reports").rglob("*-daily.md"))
    assert len(archives) == 1 and SECRET in archives[0].read_text(encoding="utf-8")
    assert reportstate.read_notes(hub, "daily") == []
    assert reportstate.read_draft(hub, "daily", "diary") == ""
    assert reportstate.last_sent(reportstate.load_state(hub), "daily") is not None


def test_send_output_never_contains_report_text(hub: Path, sent: Collector) -> None:
    periods_on(hub, "daily")
    command(hub, "mail", cmd=echo_cmd(SECRET))
    reportstate.approve(hub, "mail", {"daily": echo_cmd(SECRET)})
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert SECRET in sent.sent[0]
    assert SECRET not in r.output
    assert r.stdout.strip() == "sent: 1 section(s), 0 note(s)"


def test_send_nothing_to_send(hub: Path, sent: Collector) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "nothing to send" and sent.sent == []
    state = reportstate.load_state(hub)
    assert reportstate.last_run(state, "daily") is not None
    assert reportstate.last_sent(state, "daily") is None


def test_send_nothing_to_send_clears_stale_drafts(hub: Path, sent: Collector) -> None:
    instruction(hub, "diary")
    reportstate.put_draft(hub, "daily", "diary", "")
    assert run(hub, "report", "send", "daily").stdout.strip() == "nothing to send"
    assert not (hub / ".cc-hub/reports/drafts/daily").exists()


def test_send_twice_a_day_says_already_and_clears_the_drafts(hub: Path, sent: Collector) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "morning")
    assert run(hub, "report", "send", "daily").exit_code == 0
    run(hub, "report", "put", "daily", "diary", "--text", "evening")
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "already sent today; --again sends it once more"
    assert len(sent.sent) == 1
    assert reportstate.read_draft(hub, "daily", "diary") == ""  # an unsent draft is not kept


def test_send_again_sends_once_more(hub: Path, sent: Collector) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "morning")
    run(hub, "report", "send", "daily")
    run(hub, "report", "put", "daily", "diary", "--text", "evening")
    r = run(hub, "report", "send", "daily", "--again")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "sent: 1 section(s), 0 note(s)"
    assert len(sent.sent) == 2 and "evening" in sent.sent[1]
    assert len(list((hub / "reports").rglob("*-daily*.md"))) == 2


def test_send_already_with_a_busy_state_is_an_error(
    hub: Path, sent: Collector, busy_state
) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "morning")
    run(hub, "report", "send", "daily")
    with reportstate.state_lock(hub):
        r = run(hub, "report", "send", "daily")
    assert r.exit_code == 1 and "busy" in r.stderr


def test_send_failure_is_an_error_and_changes_nothing(
    hub: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", f"body {SECRET}")

    def broken(text: str) -> None:
        raise ReportError("cc-connect not found on PATH")

    monkeypatch.setattr(reportbuild, "cc_connect_sender", lambda: broken)
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 1 and r.stderr.strip() == "cc-connect not found on PATH"
    assert SECRET not in r.output
    assert reportstate.read_draft(hub, "daily", "diary") != ""
    assert not (hub / "reports").exists()


def test_send_error_does_not_echo_the_report(hub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", f"line with {SECRET} in it")

    def fake_run(argv, **kwargs):
        # cc-connect echoes the text it was given on stderr
        return subprocess.CompletedProcess(argv, 2, b"", kwargs["input"])

    real = reportbuild.cc_connect_sender
    monkeypatch.setattr(
        reportbuild, "cc_connect_sender", lambda: real(which=lambda name: name, run=fake_run)
    )
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 1 and "cc-connect send failed (exit 2)" in r.stderr
    assert SECRET not in r.output


def test_send_commit_warning_goes_to_stderr(
    git_hub: Path, sent: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    instruction(git_hub, "diary")
    run(git_hub, "report", "put", "daily", "diary", "--text", "hello")
    monkeypatch.setattr("cc_hub.gitops.commit_paths", lambda *a, **k: "not committed: boom")
    r = run(git_hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "sent: 1 section(s), 0 note(s)"
    assert "warning: not committed: boom" in r.stderr


def test_send_commits_the_archive(git_hub: Path, sent: Collector) -> None:
    instruction(git_hub, "diary")
    run(git_hub, "report", "put", "daily", "diary", "--text", "hello")
    r = run(git_hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output
    assert "warning" not in r.stderr
    assert git_log_subject(git_hub) == "cc-hub: report daily"


def test_send_while_another_send_runs_is_an_error(hub: Path, sent: Collector) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "hello")
    token = reportstate.acquire_lock(
        hub / ".cc-hub/reports/send-daily.lock", stale_after=3600.0
    )
    assert token is not None
    r = run(hub, "report", "send", "daily")
    assert r.exit_code == 1 and "is being sent" in r.stderr
    assert sent.sent == []


def test_send_does_not_need_the_hub_lock(hub: Path, sent: Collector) -> None:
    instruction(hub, "diary")
    run(hub, "report", "put", "daily", "diary", "--text", "hello")
    with apps.hub_lock(hub):
        r = run(hub, "report", "send", "daily")
    assert r.exit_code == 0, r.output


# --- note ---


def test_note_is_kept_for_the_report_that_is_on(hub: Path) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "note", "daily", "--from", "mail", "remember the milk")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "kept for the daily report"
    notes = reportstate.read_notes(hub, "daily")
    assert [(n["from"], n["text"]) for n in notes] == [("mail", "remember the milk")]


def test_note_for_a_period_that_is_off_goes_to_the_next_one_on(hub: Path) -> None:
    periods_on(hub, "weekly")
    r = run(hub, "report", "note", "daily", "--from", "plans/morning", "call mum")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "kept for the weekly report"
    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["call mum"]


def test_note_exit_code_when_all_off(hub: Path) -> None:
    periods_on(hub)
    r = run(hub, "report", "note", "daily", "--from", "mail", "call mum")
    assert r.exit_code == 3
    assert r.stderr.strip() == "not kept: no report is on; reply with it yourself"
    assert reportstate.read_notes(hub, "daily") == []


def test_note_exit_code_when_a_longer_period_only_is_on(hub: Path) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "note", "weekly", "--from", "mail", "call mum")
    assert r.exit_code == 3  # notes go to a longer period, never to a shorter one


def test_note_keeps_text_as_given(hub: Path) -> None:
    periods_on(hub, "daily")
    run(hub, "report", "note", "daily", "--from", "mail", "  带空格 & 中文  ")
    assert reportstate.read_notes(hub, "daily")[0]["text"] == "  带空格 & 中文  "


@pytest.mark.parametrize(
    "source",
    ["Mail", "mail\n", "-mail", "a b", "a" * 101, "", "mail:x", "../x", "mail x", "邮件"],
)
def test_note_refuses_a_source_that_is_not_a_name(hub: Path, source: str) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "note", "daily", "--from", source, "text")
    assert r.exit_code == 1 and "--from" in r.stderr
    assert reportstate.read_notes(hub, "daily") == []


@pytest.mark.parametrize("source", ["mail", "plans/morning", "a" * 100, "0-x"])
def test_note_accepts_a_source_that_is_a_name(hub: Path, source: str) -> None:
    periods_on(hub, "daily")
    assert run(hub, "report", "note", "daily", "--from", source, "text").exit_code == 0


def test_note_refuses_empty_text(hub: Path) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "note", "daily", "--from", "mail", "   ")
    assert r.exit_code == 1 and "empty" in r.stderr
    assert reportstate.read_notes(hub, "daily") == []


def test_note_needs_from(hub: Path) -> None:
    periods_on(hub, "daily")
    r = run(hub, "report", "note", "daily", "text")
    assert r.exit_code == 2


def test_note_with_an_unknown_period(hub: Path) -> None:
    r = run(hub, "report", "note", "hourly", "--from", "mail", "text")
    assert r.exit_code == 1 and r.stderr.strip() == UNKNOWN.format("hourly")


def test_note_with_a_busy_state_exits_1_not_3(hub: Path, busy_state) -> None:
    periods_on(hub, "daily")
    with reportstate.state_lock(hub):
        r = run(hub, "report", "note", "daily", "--from", "mail", "text")
    assert r.exit_code == 1 and "busy" in r.stderr
    assert reportstate.read_notes(hub, "daily") == []


def test_note_with_nothing_on_does_not_wait_for_a_busy_state(hub: Path, busy_state) -> None:
    periods_on(hub)
    with reportstate.state_lock(hub):
        r = run(hub, "report", "note", "daily", "--from", "mail", "text")
    assert r.exit_code == 3


def test_note_does_not_need_the_hub_lock(hub: Path) -> None:
    periods_on(hub, "daily")
    with apps.hub_lock(hub):
        r = run(hub, "report", "note", "daily", "--from", "mail", "text")
    assert r.exit_code == 0, r.output


def test_note_with_a_broken_cron_override_fails(hub: Path) -> None:
    (hub / "hub.toml").write_text("[cron\n", encoding="utf-8")
    r = run(hub, "report", "note", "daily", "--from", "mail", "text")
    assert r.exit_code == 1 and "hub.toml" in r.stderr


# --- section ---


def test_section_off_writes_commits_and_prints(git_hub: Path) -> None:
    instruction(git_hub, "diary")
    r = run(git_hub, "report", "section", "diary", "daily", "--off")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "diary/daily: off"
    assert reports.load_config(git_hub).off == {"diary/daily"}
    assert git_log_subject(git_hub) == "cc-hub: report section diary/daily"
    files = run_git(git_hub, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["hub.toml"]


def test_section_on_removes_the_table(git_hub: Path) -> None:
    instruction(git_hub, "diary")
    run(git_hub, "report", "section", "diary", "daily", "--off")
    r = run(git_hub, "report", "section", "diary", "daily", "--on")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "diary/daily: on"
    assert reports.load_config(git_hub).off == set()
    assert "diary/daily" not in (git_hub / "hub.toml").read_text(encoding="utf-8")
    assert git_log_subject(git_hub) == "cc-hub: report section diary/daily"


def test_section_on_clears_a_leftover_table_of_a_removed_app(hub: Path) -> None:
    reports.save_section(hub, "gone/daily", False)  # the app was removed, its table stayed
    assert reports.load_config(hub).off == {"gone/daily"}
    r = run(hub, "report", "section", "gone", "daily", "--on")
    assert r.exit_code == 0, r.output
    assert reports.load_config(hub).off == set()


def test_section_off_needs_the_section_to_exist(hub: Path) -> None:
    before = (hub / "hub.toml").read_bytes()
    r = run(hub, "report", "section", "gone", "daily", "--off")
    assert r.exit_code == 1 and "no section gone/daily" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_section_off_of_a_section_with_a_broken_file_is_allowed(hub: Path) -> None:
    write(hub / "apps/diary/reports/daily.md", "---\ncommand:\n---\n")
    fake_app(hub, "diary", {})
    assert run(hub, "report", "section", "diary", "daily", "--off").exit_code == 0
    assert reports.load_config(hub).off == {"diary/daily"}


@pytest.mark.parametrize("flags", [[], ["--on", "--off"]])
def test_section_needs_exactly_one_flag(hub: Path, flags: list[str]) -> None:
    instruction(hub, "diary")
    before = (hub / "hub.toml").read_bytes()
    r = run(hub, "report", "section", "diary", "daily", *flags)
    assert r.exit_code == 1 and "one of" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_section_with_an_unknown_period(hub: Path) -> None:
    r = run(hub, "report", "section", "diary", "hourly", "--off")
    assert r.exit_code == 1 and r.stderr.strip() == UNKNOWN.format("hourly")


def test_section_with_a_bad_app_name(hub: Path) -> None:
    r = run(hub, "report", "section", "Bad App", "daily", "--on")
    assert r.exit_code == 1 and "not a section" in r.stderr


def test_section_keeps_the_rest_of_hub_toml(hub: Path) -> None:
    instruction(hub, "diary")
    path = hub / "hub.toml"
    path.write_bytes(path.read_bytes() + b"\r\n# my note\r\n")
    old = path.read_bytes().decode("utf-8")
    assert run(hub, "report", "section", "diary", "daily", "--off").exit_code == 0
    assert path.read_bytes().decode("utf-8").startswith(old)


def test_section_commit_warning_is_a_warning(git_hub: Path, monkeypatch) -> None:
    instruction(git_hub, "diary")
    monkeypatch.setattr("cc_hub.gitops.commit_paths", lambda *a, **k: "not committed: boom")
    r = run(git_hub, "report", "section", "diary", "daily", "--off")
    assert r.exit_code == 0, r.output
    assert "warning: not committed: boom" in r.stderr
    assert reports.load_config(git_hub).off == {"diary/daily"}


def test_section_with_a_busy_hub_is_an_error(hub: Path) -> None:
    instruction(hub, "diary")
    before = (hub / "hub.toml").read_bytes()
    with apps.hub_lock(hub):
        r = run(hub, "report", "section", "diary", "daily", "--off")
    assert r.exit_code == 1 and "another cc-hub" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_section_off_takes_the_section_out_of_the_plan(hub: Path) -> None:
    periods_on(hub, "daily")
    instruction(hub, "diary")
    run(hub, "report", "section", "diary", "daily", "--off")
    data = json.loads(run(hub, "report", "plan", "daily", "--json").stdout)
    assert data["sections"] == []


# --- language ---


def test_language_writes_commits_and_prints(git_hub: Path) -> None:
    r = run(git_hub, "report", "language", "zh-CN")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "language: zh-CN"
    assert reports.load_config(git_hub).language == "zh-CN"
    assert git_log_subject(git_hub) == "cc-hub: report language"
    files = run_git(git_hub, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["hub.toml"]


def test_language_changes_the_language(hub: Path) -> None:
    run(hub, "report", "language", "zh")
    run(hub, "report", "language", "en")
    assert reports.load_config(hub).language == "en"


@pytest.mark.parametrize("tag", ["", "e", "english!", "en_US", "zh-", "en\n", "中文"])
def test_language_refuses_what_is_not_a_tag(hub: Path, tag: str) -> None:
    before = (hub / "hub.toml").read_bytes()
    r = run(hub, "report", "language", tag)
    assert r.exit_code == 1 and "language tag" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_language_with_a_busy_hub_is_an_error(hub: Path) -> None:
    before = (hub / "hub.toml").read_bytes()
    with apps.hub_lock(hub):
        r = run(hub, "report", "language", "zh")
    assert r.exit_code == 1 and "another cc-hub" in r.stderr
    assert (hub / "hub.toml").read_bytes() == before


def test_language_commit_warning_is_a_warning(git_hub: Path, monkeypatch) -> None:
    monkeypatch.setattr("cc_hub.gitops.commit_paths", lambda *a, **k: "not committed: boom")
    r = run(git_hub, "report", "language", "zh")
    assert r.exit_code == 0, r.output
    assert "warning: not committed: boom" in r.stderr


# --- approve ---


def test_approve_records_every_command_section(hub: Path) -> None:
    command(hub, "mail", "daily", "uv run mail.py daily")
    command(hub, "mail", "weekly", "uv run mail.py weekly")
    instruction(hub, "mail", "monthly")
    r = run(hub, "report", "approve", "mail")
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines() == [
        "approved: daily: uv run mail.py daily",
        "approved: weekly: uv run mail.py weekly",
    ]
    state = reportstate.load_state(hub)
    assert reportstate.is_approved(state, "mail", "daily", "uv run mail.py daily")
    assert reportstate.is_approved(state, "mail", "weekly", "uv run mail.py weekly")
    assert not reportstate.is_approved(state, "mail", "monthly", "uv run mail.py daily")


def test_approve_then_list_shows_approved(hub: Path) -> None:
    command(hub, "mail")
    run(hub, "report", "approve", "mail")
    assert json.loads(run(hub, "report", "list", "--json").stdout)["sections"][0]["approved"]


def test_approve_replaces_the_old_approvals(hub: Path) -> None:
    command(hub, "mail", "daily", "uv run old.py")
    run(hub, "report", "approve", "mail")
    command(hub, "mail", "daily", "uv run new.py")
    r = run(hub, "report", "approve", "mail")
    assert r.stdout.strip() == "approved: daily: uv run new.py"
    state = reportstate.load_state(hub)
    assert not reportstate.is_approved(state, "mail", "daily", "uv run old.py")
    assert reportstate.is_approved(state, "mail", "daily", "uv run new.py")


def test_approve_leaves_other_apps_alone(hub: Path) -> None:
    command(hub, "mail")
    command(hub, "bank", "daily", "uv run bank.py")
    run(hub, "report", "approve", "bank")
    run(hub, "report", "approve", "mail")
    state = reportstate.load_state(hub)
    assert reportstate.is_approved(state, "bank", "daily", "uv run bank.py")


def test_approve_an_app_without_command_sections(hub: Path) -> None:
    instruction(hub, "diary")
    r = run(hub, "report", "approve", "diary")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "nothing to approve"
    assert reportstate.load_state(hub) == {}


def test_approve_an_app_without_reports(hub: Path) -> None:
    fake_app(hub, "plain", {"app.toml": "x\n"})
    r = run(hub, "report", "approve", "plain")
    assert r.exit_code == 0 and r.stdout.strip() == "nothing to approve"


def test_approve_skips_a_section_with_a_broken_file(hub: Path) -> None:
    command(hub, "mail")
    write(hub / "apps/mail/reports/weekly.md", "---\ncommand:\n---\n")
    r = run(hub, "report", "approve", "mail")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == f"approved: daily: {MAIL}"


def test_approve_an_app_that_is_not_installed(hub: Path) -> None:
    r = run(hub, "report", "approve", "ghost")
    assert r.exit_code == 1 and "ghost" in r.stderr
    assert reportstate.load_state(hub) == {}


def test_approve_with_a_busy_state_is_an_error(hub: Path, busy_state) -> None:
    command(hub, "mail")
    with reportstate.state_lock(hub):
        r = run(hub, "report", "approve", "mail")
    assert r.exit_code == 1 and "busy" in r.stderr
    assert reportstate.load_state(hub) == {}


def test_approve_in_a_hub_path_with_spaces_and_cjk(git_hub: Path) -> None:
    assert " " in git_hub.name and not git_hub.name.isascii()
    command(git_hub, "mail")
    assert run(git_hub, "report", "approve", "mail").exit_code == 0


# --- end to end ---


def test_approved_command_runs_when_sent(hub: Path, sent: Collector) -> None:
    periods_on(hub, "daily")
    cmd = echo_cmd("from the command")
    command(hub, "mail", cmd=cmd)
    unapproved = run(hub, "report", "send", "daily", "--again")
    assert unapproved.exit_code == 0 and "not approved on this machine" in sent.sent[0]
    run(hub, "report", "approve", "mail")
    r = run(hub, "report", "send", "daily", "--again")
    assert r.exit_code == 0, r.output
    assert "from the command" in sent.sent[1]
