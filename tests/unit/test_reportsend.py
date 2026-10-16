# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cc_hub import apps, cronoverrides, gitops, reportbuild, reports, reportstate
from cc_hub.reportbuild import (
    SOURCE_RULE,
    SendResult,
    add_routed_note,
    cc_connect_sender,
    send,
)
from cc_hub.reports import ReportError
from tests.conftest import fake_app, write

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=TZ)
REPORT_CRON = '---\nschedule: "0 8 * * *"\ndefault: false\nsession: new_per_run\n---\nx\n'
MAIL = "uv run mail.py"
ARCHIVE = "reports/2026/2026-10-16-daily.md"


def periods_on(hub: Path, *periods: str) -> None:
    """The report tasks exist for every period (Task 7 ships them); only `periods` are enabled."""
    for p in reports.PERIODS:
        write(hub / f"cron/report-{p}.md", REPORT_CRON)
    for p in periods:
        cronoverrides.save(hub, f"report-{p}", {"enabled": True})


def install(hub: Path, app: str, period: str, text: str) -> None:
    if (hub / "apps" / app).exists():
        write(hub / "apps" / app / "reports" / f"{period}.md", text)
    else:
        fake_app(hub, app, {f"reports/{period}.md": text})


def command_section(hub: Path, app: str, period: str = "daily", command: str = MAIL) -> None:
    install(hub, app, period, f'---\ncommand: "{command}"\ntitle: "{app}"\n---\n')
    reportstate.approve(hub, app, {period: command})


class Runner:
    def __init__(self, output: str = "3 封新邮件", on_call=None):
        self.output = output
        self.on_call = on_call
        self.calls: list[str] = []

    def __call__(self, hub: Path, command: str, env: dict[str, str]):
        self.calls.append(command)
        if self.on_call is not None:
            self.on_call()
        return self.output, None


class Sink:
    """A sender that collects the text it is given."""

    def __init__(self):
        self.texts: list[str] = []

    def __call__(self, text: str) -> None:
        self.texts.append(text)


def failing_sender(text: str) -> None:
    raise ReportError("cc-connect send failed (exit 1): not running")


def send_lock(hub: Path, period: str = "daily") -> Path:
    return hub / ".cc-hub" / "reports" / f"send-{period}.lock"


def state_lock(hub: Path) -> Path:
    return hub / ".cc-hub" / "reports" / "state.lock"


def git_out(hub: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(hub), *args], capture_output=True, text=True, encoding="utf-8",
        check=True,
    ).stdout


def archive_files(hub: Path) -> list[str]:
    root = hub / "reports"
    if not root.exists():
        return []
    return sorted(p.relative_to(hub).as_posix() for p in root.rglob("*") if p.is_file())


# --- send ---


def test_send_archives_commits_and_clears(git_hub: Path):
    hub = git_hub
    periods_on(hub, "daily")
    command_section(hub, "mail")
    install(hub, "plans", "daily", "---\ntitle: \"计划\"\n---\n")
    reportstate.put_draft(hub, "daily", "plans", "今天三件事\n")
    reportstate.add_note(hub, "daily", "feishu", "别忘了周五的会", NOW)
    runner, sink = Runner(), Sink()

    result = send(hub, "daily", NOW, runner=runner, sender=sink)

    assert result == SendResult("sent", 2, 1, ARCHIVE, None)
    assert len(sink.texts) == 1
    text = sink.texts[0]
    assert text.startswith("# Daily report · 2026-10-16\n")
    assert "3 封新邮件" in text and "今天三件事" in text and "- feishu: 别忘了周五的会" in text
    # the archive holds the text that was sent, plus a final newline, with LF endings
    assert (hub / ARCHIVE).read_bytes() == (text + "\n").encode("utf-8")
    assert git_out(hub, "log", "-1", "--format=%s").strip() == "cc-hub: report daily"
    assert git_out(hub, "show", "--name-only", "--format=", "HEAD").split() == [ARCHIVE]
    assert git_out(hub, "status", "--porcelain", "--", "reports") == ""
    # what went in is gone; the run is recorded
    assert reportstate.read_notes(hub, "daily") == []
    assert reportstate.read_draft(hub, "daily", "plans") == ""
    state = reportstate.load_state(hub)
    assert reportstate.last_sent(state, "daily") == NOW
    assert reportstate.last_run(state, "daily") == NOW
    assert not send_lock(hub).exists()

    # a second send on the same day does nothing at all
    again = send(hub, "daily", NOW + timedelta(hours=3), runner=runner, sender=sink)
    assert again == SendResult("already", 0, 0, None, None)
    assert len(sink.texts) == 1 and len(runner.calls) == 1
    assert archive_files(hub) == [ARCHIVE]

    # --again sends it once more and keeps both archives
    third = send(hub, "daily", NOW + timedelta(hours=3), again=True, runner=runner, sender=sink)
    assert third.status == "sent"
    assert third.archive == "reports/2026/2026-10-16-daily-2.md"
    assert len(sink.texts) == 2
    fourth = send(hub, "daily", NOW + timedelta(hours=4), again=True, runner=runner, sender=sink)
    assert fourth.archive == "reports/2026/2026-10-16-daily-3.md"
    assert archive_files(hub) == sorted(
        [ARCHIVE, "reports/2026/2026-10-16-daily-2.md", "reports/2026/2026-10-16-daily-3.md"]
    )
    assert git_out(hub, "log", "-1", "--format=%s").strip() == "cc-hub: report daily"
    assert git_out(hub, "status", "--porcelain", "--", "reports") == ""


def test_send_in_a_hub_without_git_archives_without_a_warning(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    result = send(hub, "daily", NOW, sender=Sink())
    assert result == SendResult("sent", 0, 1, ARCHIVE, None)
    assert (hub / ARCHIVE).is_file()


def test_empty_report_is_not_sent_nor_archived(git_hub: Path):
    hub = git_hub
    periods_on(hub, "daily")
    install(hub, "plans", "daily", "---\n---\n")  # an instruction section nobody wrote a draft for
    reportstate.put_draft(hub, "daily", "stale", "left over from an app that is gone\n")
    sink = Sink()
    head = git_out(hub, "rev-parse", "HEAD")

    result = send(hub, "daily", NOW, sender=sink)

    assert result == SendResult("empty", 0, 0, None, None)
    assert sink.texts == []
    assert archive_files(hub) == [] and not (hub / "reports").exists()
    assert git_out(hub, "rev-parse", "HEAD") == head
    assert reportstate.read_draft(hub, "daily", "stale") == ""  # drafts are cleared
    state = reportstate.load_state(hub)
    assert reportstate.last_run(state, "daily") == NOW  # it ran ...
    assert reportstate.last_sent(state, "daily") is None  # ... and sent nothing
    # nothing was sent today, so a later send is not "already"
    reportstate.add_note(hub, "daily", "me", "later", NOW)
    assert send(hub, "daily", NOW + timedelta(hours=1), sender=sink).status == "sent"


def test_send_failure_keeps_everything(git_hub: Path):
    hub = git_hub
    periods_on(hub, "daily")
    install(hub, "plans", "daily", "---\n---\n")
    reportstate.put_draft(hub, "daily", "plans", "the draft\n")
    reportstate.add_note(hub, "daily", "feishu", "a note", NOW)
    head = git_out(hub, "rev-parse", "HEAD")

    with pytest.raises(ReportError, match=r"^cc-connect send failed \(exit 1\): not running$"):
        send(hub, "daily", NOW, sender=failing_sender)

    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["a note"]
    assert reportstate.read_draft(hub, "daily", "plans") == "the draft\n"
    assert not (hub / "reports").exists()
    assert git_out(hub, "rev-parse", "HEAD") == head
    state = reportstate.load_state(hub)
    assert reportstate.last_sent(state, "daily") is None
    assert reportstate.last_run(state, "daily") is None
    assert not send_lock(hub).exists()  # the lock is released on failure too
    # and trying again works
    sink = Sink()
    assert send(hub, "daily", NOW, sender=sink).status == "sent"
    assert "a note" in sink.texts[0]


def test_note_added_after_assembly_stays(hub: Path):
    periods_on(hub, "daily")
    command_section(hub, "mail")
    reportstate.add_note(hub, "daily", "feishu", "first", NOW)
    # a note arrives while the section commands run, after the notes were read
    runner = Runner(on_call=lambda: reportstate.add_note(hub, "daily", "feishu", "second", NOW))
    sink = Sink()

    result = send(hub, "daily", NOW, runner=runner, sender=sink)

    assert result.notes == 1
    assert "- feishu: first" in sink.texts[0] and "second" not in sink.texts[0]
    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["second"]


def test_the_next_report_starts_without_the_drafts_of_the_last(hub: Path):
    periods_on(hub, "daily")
    install(hub, "plans", "daily", "---\n---\n")
    reportstate.put_draft(hub, "daily", "plans", "today\n")
    send(hub, "daily", NOW, sender=Sink())
    assert reportstate.read_draft(hub, "daily", "plans") == ""
    assert send(hub, "daily", NOW + timedelta(days=1), sender=Sink()).status == "empty"


def test_archive_failure_after_sending_is_a_warning_and_the_run_is_recorded(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    write(hub / "reports", "a file where the archive folder should be")
    sink = Sink()

    result = send(hub, "daily", NOW, sender=sink)

    assert (result.status, result.archive, result.notes) == ("sent", None, 1)
    assert result.warning is not None and result.warning.startswith("report not archived: ")
    assert len(sink.texts) == 1  # it did go out, so it must not go out again
    assert reportstate.read_notes(hub, "daily") == []
    assert reportstate.last_sent(reportstate.load_state(hub), "daily") == NOW


def test_commit_warning_goes_into_the_result(hub: Path, monkeypatch: pytest.MonkeyPatch):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    seen = []

    def commit(hub_dir, paths, message):
        seen.append((hub_dir, paths, message))
        return "not committed: index.lock exists"

    monkeypatch.setattr(gitops, "commit_paths", commit)
    result = send(hub, "daily", NOW, sender=Sink())
    assert result.status == "sent" and result.archive == ARCHIVE
    assert result.warning == "not committed: index.lock exists"
    assert seen == [(hub.absolute(), [ARCHIVE], "cc-hub: report daily")]
    assert reportstate.last_sent(reportstate.load_state(hub), "daily") == NOW  # still recorded


def test_the_archive_is_named_for_the_local_date_of_now(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "late", NOW)
    now = datetime(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # 01-01 in UTC
    result = send(hub, "daily", now, sender=Sink())
    assert result.archive == "reports/2026/2026-12-31-daily.md"
    assert (hub / "reports/2026/2026-12-31-daily.md").read_text(encoding="utf-8").startswith(
        "# Daily report · 2026-12-31\n"
    )


def test_already_compares_the_dates_in_the_timezone_of_now(hub: Path):
    periods_on(hub, "daily")
    reportstate.record_run(hub, "daily", NOW, sent=True)  # 2026-10-16 01:00 UTC
    west = timezone(timedelta(hours=-5))
    sink = Sink()
    reportstate.add_note(hub, "daily", "me", "n", NOW)
    # at UTC-5 the earlier send was on 15 October: 16 October at 08:00 is a new day
    assert send(hub, "daily", datetime(2026, 10, 16, 8, 0, tzinfo=west), sender=sink).status == (
        "sent"
    )
    reportstate.record_run(hub, "daily", NOW, sent=True)
    # ... while 15 October at 21:00 at UTC-5 is the day of that send
    reportstate.add_note(hub, "daily", "me", "n", NOW)
    again = send(hub, "daily", datetime(2026, 10, 15, 21, 0, tzinfo=west), sender=sink)
    assert again.status == "already"
    assert len(sink.texts) == 1


def test_send_checks_the_period_and_a_naive_now(hub: Path):
    sink = Sink()
    with pytest.raises(ReportError, match="hourly"):
        send(hub, "hourly", NOW, sender=sink)
    with pytest.raises(ValueError, match="timezone"):
        send(hub, "daily", datetime(2026, 10, 16, 9, 0), sender=sink)
    with pytest.raises(ValueError, match="timezone"):
        add_routed_note(hub, "daily", "me", "x", datetime(2026, 10, 16, 9, 0))
    assert sink.texts == []
    assert not send_lock(hub).exists()


def test_send_looks_the_default_sender_up_when_it_is_called(hub: Path, monkeypatch):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    sink = Sink()
    monkeypatch.setattr(reportbuild, "cc_connect_sender", lambda: sink)
    assert send(hub, "daily", NOW).status == "sent"
    assert len(sink.texts) == 1


def test_send_prints_nothing(hub: Path, capfd: pytest.CaptureFixture[str]):
    periods_on(hub, "daily")
    command_section(hub, "mail")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    send(hub, "daily", NOW, runner=Runner(), sender=Sink())
    out, err = capfd.readouterr()
    assert out == "" and err == ""


# --- note routing ---


def test_note_routing(hub: Path):
    periods_on(hub, "weekly")  # daily is off
    command_section(hub, "mail", "weekly")
    assert add_routed_note(hub, "daily", "feishu", "note for the week", NOW) == "weekly"
    # stored under the period that was asked for ...
    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["note for the week"]
    assert reportstate.read_notes(hub, "weekly") == []
    assert add_routed_note(hub, "weekly", "me", "weekly note", NOW) == "weekly"
    # ... and the report it routes to picks it up
    sink = Sink()
    result = send(hub, "weekly", NOW, runner=Runner(), sender=sink)
    assert result.notes == 2
    assert "- feishu: note for the week" in sink.texts[0]
    assert "- me: weekly note" in sink.texts[0]
    # both stores are emptied by the send
    assert reportstate.read_notes(hub, "daily") == []
    assert reportstate.read_notes(hub, "weekly") == []


def test_note_routing_with_everything_off_stores_nothing(hub: Path):
    periods_on(hub)  # the tasks exist, none is enabled
    for period in reports.PERIODS:
        assert add_routed_note(hub, period, "feishu", "nobody listens", NOW) is None
        assert reportstate.read_notes(hub, period) == []
    assert not (hub / ".cc-hub" / "reports" / "notes").exists()
    assert not (hub / ".cc-hub" / "reports" / "state.lock").exists()


def test_a_period_that_is_on_keeps_its_own_note(hub: Path):
    periods_on(hub, "daily", "weekly")
    assert add_routed_note(hub, "daily", "me", "x", NOW) == "daily"
    assert add_routed_note(hub, "quarterly", "me", "y", NOW) is None  # nothing from quarterly up
    assert len(reportstate.read_notes(hub, "daily")) == 1
    assert reportstate.read_notes(hub, "quarterly") == []


def test_add_routed_note_checks_the_period(hub: Path):
    with pytest.raises(ReportError, match="hourly"):
        add_routed_note(hub, "hourly", "me", "x", NOW)


def test_source_rule():
    for ok in ("feishu", "feishu/x", "a-b", "0", "a" * 100):
        assert SOURCE_RULE.fullmatch(ok), ok
    for bad in ("", "-a", "/a", "A", "a b", "a_b", "a" * 101, "a\n", "飞书"):
        assert not SOURCE_RULE.fullmatch(bad), bad


# --- cc_connect_sender ---

CC = "/usr/bin/cc-connect"


def fake_run(returncode: int = 0, stdout="", stderr="", raises=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    run.calls = calls
    return run


def test_cc_connect_sender_builds_the_command():
    run = fake_run()
    sender = cc_connect_sender(
        which=lambda name: CC if name == "cc-connect" else None,
        run=run,
        env={"CC_PROJECT": "hub", "CC_SESSION_KEY": "feishu:x"},
    )
    text = "# 日报 · 2026-10-16\n\n## 邮件\n\n3 封新邮件\n"
    assert sender(text) is None
    [(argv, kwargs)] = run.calls
    assert argv == [CC, "send", "-p", "hub", "-s", "feishu:x", "--stdin"]
    assert text not in argv and all(text.strip() not in arg for arg in argv)  # never on the line
    assert kwargs["input"] == text.encode("utf-8")  # UTF-8 bytes, LF kept as is
    assert kwargs["timeout"] == 60
    assert kwargs["capture_output"] is True


@pytest.mark.parametrize(
    ("env", "tail"),
    [
        ({}, []),
        ({"CC_PROJECT": "hub"}, ["-p", "hub"]),
        ({"CC_SESSION_KEY": "feishu:x"}, ["-s", "feishu:x"]),
        ({"CC_PROJECT": "", "CC_SESSION_KEY": ""}, []),  # an empty variable counts as unset
    ],
)
def test_cc_connect_sender_adds_project_and_session_only_when_set(env, tail):
    run = fake_run()
    cc_connect_sender(which=lambda _: CC, run=run, env=env)("report")
    assert run.calls[0][0] == [CC, "send", *tail, "--stdin"]


def test_cc_connect_sender_reads_the_environment_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CC_PROJECT", "hub2")
    monkeypatch.delenv("CC_SESSION_KEY", raising=False)
    run = fake_run()
    cc_connect_sender(which=lambda _: CC, run=run)("report")
    assert run.calls[0][0] == [CC, "send", "-p", "hub2", "--stdin"]


def test_cc_connect_sender_not_on_path():
    run = fake_run()
    sender = cc_connect_sender(which=lambda _: None, run=run, env={})
    with pytest.raises(ReportError) as info:
        sender("report")
    assert str(info.value) == "cc-connect not found on PATH"
    assert run.calls == []


def test_cc_connect_sender_failure_messages():
    def raised(**kw):
        sender = cc_connect_sender(which=lambda _: CC, run=fake_run(**kw), env={})
        with pytest.raises(ReportError) as info:
            sender("report text")
        return str(info.value)

    assert raised(returncode=1, stderr="not running\n") == (
        "cc-connect send failed (exit 1): not running"
    )
    # only stderr is quoted, and only its first line
    assert raised(returncode=2, stdout="no such session\n") == "cc-connect send failed (exit 2)"
    assert raised(returncode=3, stdout="out", stderr="\n  err one  \nerr two\n") == (
        "cc-connect send failed (exit 3): err one"
    )
    assert raised(returncode=4) == "cc-connect send failed (exit 4)"
    assert raised(returncode=5, stderr="  \n \n") == "cc-connect send failed (exit 5)"
    assert raised(returncode=1, stderr=b"bytes \xe9\n") == (
        "cc-connect send failed (exit 1): bytes �"
    )
    assert "60 seconds" in raised(raises=subprocess.TimeoutExpired(["cc-connect"], 60))
    assert raised(raises=OSError("exec format error")) == (
        "cannot run cc-connect: exec format error"
    )


REPORT = (
    "# Daily report · 2026-10-16\n\n## Mail\n\n"
    "3 new mails: alice@example.com asks about the lunch on Friday\n"
    "short\n\n## Notes\n\n- feishu: remember the Friday meeting\n"
)
WITHHELD = "cc-connect send failed (exit 1): (details withheld)"


def failure(stderr: str, text: str = REPORT) -> str:
    sender = cc_connect_sender(
        which=lambda _: CC, run=fake_run(returncode=1, stderr=stderr), env={}
    )
    with pytest.raises(ReportError) as info:
        sender(text)
    return str(info.value)


@pytest.mark.parametrize(
    "stderr",
    [
        # the whole message echoed
        f"bad input: {REPORT}",
        # part of the message echoed: a whole report line in the detail
        "invalid message: 3 new mails: alice@example.com asks about the lunch on Friday",
        "- feishu: remember the Friday meeting (rejected)",
        # the detail is a piece of a report line
        "alice@example.com asks about the lunch",
        "remember the Friday meeting",
        # the first line is what counts, wherever the echo is cut
        "message too long: 3 new mails: alice@example.com asks about the lunch on Friday\nmore",
    ],
)
def test_cc_connect_sender_withholds_the_detail_when_it_echoes_the_report(stderr):
    assert failure(stderr) == WITHHELD


def test_cc_connect_sender_keeps_a_detail_that_shares_nothing_with_the_report():
    assert failure("session feishu:x not found") == (
        "cc-connect send failed (exit 1): session feishu:x not found"
    )
    # lines shorter than 8 characters, on either side, are not an echo
    assert failure("short") == "cc-connect send failed (exit 1): short"
    assert failure("short: connection refused") == (
        "cc-connect send failed (exit 1): short: connection refused"
    )
    assert failure("refused", "# Daily report\n\nrefused\n") == (
        "cc-connect send failed (exit 1): refused"
    )


def test_cc_connect_sender_caps_the_detail_at_200_characters():
    message = failure("x" * 5000)
    assert message == "cc-connect send failed (exit 1): " + "x" * 199 + "…"
    exactly = failure("y" * 200)
    assert exactly == "cc-connect send failed (exit 1): " + "y" * 200


def test_cc_connect_sender_never_quotes_stdout():
    sender = cc_connect_sender(
        which=lambda _: CC,
        run=fake_run(returncode=1, stdout="mail body: 3 new mails", stderr=""),
        env={},
    )
    with pytest.raises(ReportError) as info:
        sender("report")
    assert str(info.value) == "cc-connect send failed (exit 1)"


def test_cc_connect_sender_really_pipes_utf8_through_stdin(tmp_path: Path):
    """With a real process: the text reaches stdin byte for byte, with no CRLF on Windows."""
    out = tmp_path / "got.bin"
    script = (
        "import sys; open(sys.argv[1], 'wb').write(sys.stdin.buffer.read()); "
        "print('delivered')"
    )
    real_run = subprocess.run

    def run(argv, **kwargs):  # the real call, with a Python script standing for cc-connect
        assert argv[1:] == ["send", "--stdin"]
        return real_run([sys.executable, "-c", script, str(out)], **kwargs)

    text = "# 日报 · 2026-10-16\n\n## 邮件\n\n3 封新邮件 ✓\n\n- feishu: line one\n  line two"
    cc_connect_sender(which=lambda _: "cc-connect", run=run, env={})(text)
    assert out.read_bytes() == text.encode("utf-8")


# --- the send lock ---


def two_command_sections(hub: Path) -> None:
    periods_on(hub, "daily")
    command_section(hub, "mail")
    command_section(hub, "cal", command="uv run cal.py")


def test_send_refuses_while_another_send_of_the_period_is_running(hub: Path):
    periods_on(hub, "daily", "weekly")
    reportstate.add_note(hub, "daily", "me", "daily note", NOW)
    reportstate.add_note(hub, "weekly", "me", "weekly note", NOW)
    write(send_lock(hub), "4242 another-process")
    sink = Sink()

    with pytest.raises(ReportError, match=r"^a daily report is being sent; try again later$"):
        send(hub, "daily", NOW, sender=sink)

    assert sink.texts == []
    assert send_lock(hub).read_text(encoding="utf-8") == "4242 another-process"  # not ours: kept
    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["daily note"]
    assert not (hub / "reports").exists()
    assert reportstate.last_run(reportstate.load_state(hub), "daily") is None
    # the lock is per period
    assert send(hub, "weekly", NOW, sender=sink).status == "sent"


@pytest.mark.parametrize(("age", "taken"), [(3500, False), (3601, True)])
def test_a_send_lock_is_stale_after_an_hour(hub: Path, age: int, taken: bool):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    write(send_lock(hub), "4242 another-process")
    old = time.time() - age
    os.utime(send_lock(hub), (old, old))
    sink = Sink()
    if taken:
        assert send(hub, "daily", NOW, sender=sink).status == "sent"
        assert not send_lock(hub).exists()
    else:
        with pytest.raises(ReportError, match="is being sent"):
            send(hub, "daily", NOW, sender=sink)
        assert sink.texts == []


def test_the_send_lock_holds_our_pid_and_is_released_afterwards(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)
    seen = []

    def sender(text: str) -> None:
        seen.append(send_lock(hub).read_text(encoding="utf-8"))

    send(hub, "daily", NOW, sender=sender)
    assert seen[0].startswith(f"{os.getpid()} ") and len(seen[0]) > len(f"{os.getpid()} ") + 8
    assert not send_lock(hub).exists()


def test_send_does_not_remove_a_send_lock_that_is_no_longer_its_own(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "hello", NOW)

    def sender(text: str) -> None:
        write(send_lock(hub), "999 took-over")  # someone took the lock over meanwhile

    send(hub, "daily", NOW, sender=sender)
    assert send_lock(hub).read_text(encoding="utf-8") == "999 took-over"


def test_the_send_lock_is_refreshed_before_each_section_and_before_the_sender(hub: Path):
    two_command_sections(hub)
    ages: list[tuple[str, float]] = []

    def age_of_lock() -> float:
        return time.time() - send_lock(hub).stat().st_mtime

    def make_it_look_old() -> None:
        old = time.time() - 1800  # as if the step before had taken half an hour
        os.utime(send_lock(hub), (old, old))

    def runner(hub_dir: Path, command: str, env: dict[str, str]):
        ages.append((command, age_of_lock()))
        make_it_look_old()
        return "output", None

    def sender(text: str) -> None:
        ages.append(("sender", age_of_lock()))

    send(hub, "daily", NOW, runner=runner, sender=sender)

    assert [what for what, _ in ages] == ["uv run cal.py", MAIL, "sender"]
    assert all(age < 60 for _, age in ages), ages


def test_send_does_not_need_the_hub_lock_and_does_not_hold_it(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "first", NOW)
    sink = Sink()
    with apps.hub_lock(hub):  # an app or tap command is running when the send starts
        assert send(hub, "daily", NOW, sender=sink).status == "sent"

    reportstate.add_note(hub, "daily", "me", "second", NOW)

    def sender(text: str) -> None:
        with apps.hub_lock(hub):  # ... or starts in the middle of a send
            sink(text)

    assert send(hub, "daily", NOW, again=True, sender=sender).status == "sent"
    assert len(sink.texts) == 2


def test_notes_can_be_added_while_a_report_is_being_sent(hub: Path):
    periods_on(hub, "daily")
    reportstate.add_note(hub, "daily", "me", "before", NOW)
    sink = Sink()

    def sender(text: str) -> None:
        assert send_lock(hub).is_file()
        assert add_routed_note(hub, "daily", "cron", "during", NOW) == "daily"
        sink(text)

    send(hub, "daily", NOW, sender=sender)

    assert "- me: before" in sink.texts[0] and "during" not in sink.texts[0]
    assert [n["text"] for n in reportstate.read_notes(hub, "daily")] == ["during"]


def test_send_checks_the_period_before_it_makes_a_lock_file(hub: Path):
    for bad in ("../x", "daily/../../x", "", "Daily"):
        with pytest.raises(ReportError):
            send(hub, bad, NOW, sender=Sink())
    assert not (hub / ".cc-hub" / "reports").exists()


# --- the state lock ---


def test_add_routed_note_waits_for_the_state_lock_and_then_times_out(
    hub: Path, monkeypatch: pytest.MonkeyPatch
):
    periods_on(hub, "daily")
    monkeypatch.setattr(reportstate, "STATE_LOCK_WAIT", 0.3)
    with reportstate.state_lock(hub):  # a live holder
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="the reports state is busy; try again shortly"):
            add_routed_note(hub, "daily", "me", "x", NOW)
        assert time.monotonic() - started >= 0.25
        assert state_lock(hub).is_file()  # the holder's lock is untouched
    assert reportstate.read_notes(hub, "daily") == []
    assert add_routed_note(hub, "daily", "me", "x", NOW) == "daily"  # free again
    assert not state_lock(hub).exists()


def test_an_empty_report_needs_the_state_lock_and_gives_up_without_it(
    hub: Path, monkeypatch: pytest.MonkeyPatch
):
    periods_on(hub, "daily")
    monkeypatch.setattr(reportstate, "STATE_LOCK_WAIT", 0.2)
    sink = Sink()
    with reportstate.state_lock(hub), pytest.raises(TimeoutError, match="busy"):
        send(hub, "daily", NOW, sender=sink)
    assert sink.texts == [] and not send_lock(hub).exists()  # nothing went out; lock released
    assert reportstate.last_run(reportstate.load_state(hub), "daily") is None


# --- a problem after the report went out is a warning, not an exception ---


def sent_hub(hub: Path) -> None:
    """A hub whose daily report has a draft section and a note."""
    periods_on(hub, "daily")
    install(hub, "plans", "daily", "---\n---\n")
    reportstate.put_draft(hub, "daily", "plans", "today\n")
    reportstate.add_note(hub, "daily", "feishu", "a note", NOW)


def test_a_draft_that_cannot_be_removed_does_not_make_the_send_fail(
    hub: Path, monkeypatch: pytest.MonkeyPatch
):
    sent_hub(hub)

    def locked(path):  # e.g. a virus scanner holds the file on Windows
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(reportstate, "rmtree", locked)
    sink = Sink()

    result = send(hub, "daily", NOW, sender=sink)

    assert (result.status, result.archive) == ("sent", ARCHIVE)
    assert result.warning is not None and result.warning.startswith("drafts not removed: ")
    assert "Access is denied" in result.warning
    state = reportstate.load_state(hub)
    assert reportstate.last_sent(state, "daily") == NOW
    assert reportstate.read_notes(hub, "daily") == []  # the notes that went in are gone
    assert (hub / ARCHIVE).is_file()
    # a second send the same day does not send the report again
    assert send(hub, "daily", NOW + timedelta(hours=2), sender=sink).status == "already"
    assert len(sink.texts) == 1
    assert not send_lock(hub).exists() and not state_lock(hub).exists()


def test_notes_that_cannot_be_removed_do_not_keep_the_drafts_or_the_record(
    hub: Path, monkeypatch: pytest.MonkeyPatch
):
    sent_hub(hub)

    def locked(hub_dir, period, count):
        raise PermissionError(13, "Access is denied", "notes")

    monkeypatch.setattr(reportbuild, "drop_notes", locked)
    result = send(hub, "daily", NOW, sender=Sink())
    assert result.status == "sent"
    assert result.warning is not None and result.warning.startswith("notes not removed: ")
    assert reportstate.read_draft(hub, "daily", "plans") == ""  # the drafts went anyway
    assert reportstate.last_sent(reportstate.load_state(hub), "daily") == NOW


def test_a_run_that_cannot_be_recorded_is_a_warning(hub: Path, monkeypatch: pytest.MonkeyPatch):
    sent_hub(hub)

    def full(hub_dir, state):
        raise OSError("disk full")

    monkeypatch.setattr(reportstate, "save_state", full)
    result = send(hub, "daily", NOW, sender=Sink())
    assert result.status == "sent" and result.archive == ARCHIVE
    assert result.warning == "the send was not recorded: disk full"
    assert reportstate.read_notes(hub, "daily") == []  # the rest still happened
    assert reportstate.read_draft(hub, "daily", "plans") == ""


def test_a_busy_state_after_delivery_is_a_warning(hub: Path, monkeypatch: pytest.MonkeyPatch):
    sent_hub(hub)
    monkeypatch.setattr(reportstate, "STATE_LOCK_WAIT", 0.2)
    sink = Sink()
    with ExitStack() as stack:

        def sender(text: str) -> None:
            sink(text)
            stack.enter_context(reportstate.state_lock(hub))  # someone else is in the state

        result = send(hub, "daily", NOW, sender=sender)

    busy = "the reports state is busy; try again shortly"
    assert result.status == "sent" and result.archive == ARCHIVE
    assert result.warning == (
        f"the send was not recorded: {busy}; notes and drafts not removed: {busy}"
    )
    assert len(sink.texts) == 1 and (hub / ARCHIVE).is_file()
    assert len(reportstate.read_notes(hub, "daily")) == 1  # nothing was removed ...
    assert not send_lock(hub).exists()  # ... and the send lock is released


def test_the_run_is_recorded_before_the_archive_is_committed_and_the_notes_are_removed(
    hub: Path, monkeypatch: pytest.MonkeyPatch
):
    sent_hub(hub)
    seen = {}

    def commit(hub_dir, paths, message):
        seen["last_sent"] = reportstate.last_sent(reportstate.load_state(hub), "daily")
        seen["notes"] = len(reportstate.read_notes(hub, "daily"))
        seen["draft"] = reportstate.read_draft(hub, "daily", "plans")
        seen["archive"] = (hub / ARCHIVE).is_file()

    monkeypatch.setattr(gitops, "commit_paths", commit)
    send(hub, "daily", NOW, sender=Sink())
    assert seen == {"last_sent": NOW, "notes": 1, "draft": "today\n", "archive": True}


def test_several_warnings_are_joined(hub: Path, monkeypatch: pytest.MonkeyPatch):
    sent_hub(hub)
    write(hub / "reports", "a file where the archive folder should be")

    def locked(path):
        raise PermissionError("locked")

    monkeypatch.setattr(reportstate, "rmtree", locked)
    result = send(hub, "daily", NOW, sender=Sink())
    assert result.warning is not None
    first, second = result.warning.split("; drafts not removed: ")
    assert first.startswith("report not archived: ") and second == "locked"
