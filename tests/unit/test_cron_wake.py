# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

import pytest

from cc_hub.cronoverrides import save
from cc_hub.crontasks import CronError, find_job_id, wake
from tests.conftest import write

LISTING = (
    "Scheduled tasks (3):\n\n"
    "  ⏸ a1b2c3  0 0 1 1 *  hub:mail/triage\n"
    "  ✅ d4e5f6  */5 * * * *  hub:mail/poll\n"
    "  ⏸ 0a0b0c  0 0 1 1 *  hub:mail/triage-old\n"
)
CC = "/bin/cc-connect"


def fake_run(calls: list, *, listing: str = LISTING, list_code: int = 0, exec_code: int = 0):
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["cron", "list"]:
            return subprocess.CompletedProcess(argv, list_code, stdout=listing, stderr="refused")
        return subprocess.CompletedProcess(argv, exec_code, stdout="ok", stderr="boom")

    return run


def test_find_job_id_matches_exactly() -> None:
    assert find_job_id(LISTING, "mail/triage") == "a1b2c3"
    assert find_job_id(LISTING, "mail/poll") == "d4e5f6"


def test_find_job_id_reads_crlf_and_an_enabled_mark() -> None:
    assert find_job_id(LISTING.replace("\n", "\r\n"), "mail/poll") == "d4e5f6"


def test_find_job_id_missing_and_duplicate() -> None:
    with pytest.raises(CronError, match="hub:mail/digest is not registered in cc-connect"):
        find_job_id(LISTING, "mail/digest")
    with pytest.raises(CronError, match="hub:mail/triage is not registered"):
        find_job_id("No scheduled tasks.\n", "mail/triage")
    twice = LISTING + "  ⏸ ffffff  0 0 1 1 *  hub:mail/triage\n"
    with pytest.raises(CronError, match="hub:mail/triage is registered more than once"):
        find_job_id(twice, "mail/triage")


def test_find_job_id_ignores_the_header_and_other_text() -> None:
    assert find_job_id("Scheduled tasks (1):\n\n  ⏸ a1  0 0 1 1 *  hub:x\n", "x") == "a1"
    with pytest.raises(CronError, match="not registered"):
        find_job_id("Scheduled tasks  (1):\nhub:x\n", "x")


def test_wake_runs_list_then_exec(hub_with_mail: Path) -> None:
    calls: list = []
    job = wake(hub_with_mail, "mail/triage", which=lambda _: CC, run=fake_run(calls))
    assert job == "a1b2c3"
    assert calls == [[CC, "cron", "list"], [CC, "cron", "exec", "a1b2c3"]]


def test_wake_reads_cc_connect_output_as_utf8(hub_with_mail: Path) -> None:
    seen: list = []

    def run(argv, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=LISTING, stderr="")

    wake(hub_with_mail, "mail/triage", which=lambda _: CC, run=run)
    assert len(seen) == 2
    for kwargs in seen:
        assert kwargs["capture_output"] is True and kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
        assert kwargs["timeout"] == 60


@pytest.mark.parametrize("stuck", ["list", "exec"])
def test_wake_gives_up_on_a_cc_connect_that_does_not_answer(
    hub_with_mail: Path, stuck: str
) -> None:
    def run(argv, **kwargs):
        if argv[2] == stuck:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=LISTING, stderr="")

    with pytest.raises(CronError) as info:
        wake(hub_with_mail, "mail/triage", which=lambda _: CC, run=run)
    message = str(info.value)
    assert f"cc-connect cron {stuck}" in message
    assert "did not answer within 60 seconds" in message


def prepare(hub: Path, case: str) -> tuple[str, dict]:
    """The task to wake and the keyword arguments of wake() for one failure case."""
    calls: list = []
    kwargs = {"which": lambda _: CC, "run": fake_run(calls)}
    if case == "prompt task":
        return "memory-consolidate", kwargs
    if case == "exec task":
        return "mail/poll", kwargs
    if case == "unknown":
        return "mail/nothing", kwargs
    if case == "turned off":
        save(hub, "mail/triage", {"enabled": False})
    if case == "no binary":
        kwargs["which"] = lambda _: None
    if case == "list fails":
        kwargs["run"] = fake_run(calls, list_code=1)
    if case == "not registered":
        kwargs["run"] = fake_run(calls, listing="No scheduled tasks.\n")
    if case == "exec fails":
        kwargs["run"] = fake_run(calls, exec_code=1)
    if case == "cannot start":
        def run(argv, **kw):
            raise PermissionError("denied")
        kwargs["run"] = run
    return "mail/triage", kwargs


@pytest.mark.parametrize("case, words", [
    ("prompt task", "not an on-demand task"),
    ("exec task", "not an on-demand task"),
    ("unknown", "no task"),
    ("turned off", "turned off; cc-hub cron set mail/triage --on"),
    ("no binary", "not found"),
    ("list fails", "not running"),
    ("not registered", "not registered"),
    ("exec fails", "exec"),
    ("cannot start", "denied"),
])
def test_wake_failures(hub_with_mail: Path, case: str, words: str) -> None:
    name, kwargs = prepare(hub_with_mail, case)
    with pytest.raises(CronError, match=words):
        wake(hub_with_mail, name, **kwargs)


def test_wake_does_not_call_cc_connect_when_the_task_cannot_be_woken(hub_with_mail: Path) -> None:
    calls: list = []
    save(hub_with_mail, "mail/triage", {"enabled": False})
    with pytest.raises(CronError):
        wake(hub_with_mail, "mail/triage", which=lambda _: CC, run=fake_run(calls))
    assert calls == []


def test_wake_does_not_exec_when_the_listing_has_no_match(hub_with_mail: Path) -> None:
    calls: list = []
    run = fake_run(calls, listing="No scheduled tasks.\n")
    with pytest.raises(CronError):
        wake(hub_with_mail, "mail/triage", which=lambda _: CC, run=run)
    assert calls == [[CC, "cron", "list"]]


def test_wake_reports_a_task_with_a_definition_error(hub: Path) -> None:
    write(hub / "cron/broken.md", "---\non_demand: true\nschedule: \"0 0 * * *\"\n---\n")
    with pytest.raises(CronError, match="cannot wake broken: .*schedule"):
        wake(hub, "broken", which=lambda _: CC, run=fake_run([]))
