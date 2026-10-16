# -*- coding: utf-8 -*-
import json
import os
import threading
import time
import tomllib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cc_hub import reportstate as rs

CST = timezone(timedelta(hours=8))
T1 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 16, 18, 30, tzinfo=CST)


# --- approvals ---


def test_load_state_is_empty_when_missing_or_unreadable(hub: Path):
    assert rs.load_state(hub) == {}
    path = hub / rs.STATE_DIR / "state.toml"
    path.parent.mkdir(parents=True)
    path.write_text("not [valid toml", encoding="utf-8")
    assert rs.load_state(hub) == {}
    path.write_bytes(b"\xff\xfe\x00")
    assert rs.load_state(hub) == {}


def test_state_file_layout_is_toml_under_the_hub(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a"})
    rs.record_run(hub, "daily", T1, sent=True)
    text = (hub / ".cc-hub" / "reports" / "state.toml").read_text(encoding="utf-8")
    assert "[approved.ledger]" in text and 'daily = "uv run a"' in text
    assert "[runs.daily]" in text and 'last_run = "' not in text  # a TOML datetime, not a string
    run = tomllib.loads(text)["runs"]["daily"]
    assert isinstance(run["last_run"], datetime) and run["last_run"] == T1


def test_approve_then_exact_match(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a", "weekly": "uv run b"})
    state = rs.load_state(hub)
    assert rs.is_approved(state, "ledger", "daily", "uv run a") is True
    assert rs.is_approved(state, "ledger", "weekly", "uv run b") is True
    assert rs.is_approved(state, "ledger", "daily", "uv run a ") is False
    assert rs.is_approved(state, "ledger", "daily", "uv run b") is False
    assert rs.is_approved(state, "ledger", "monthly", "uv run a") is False
    assert rs.is_approved(state, "plans", "daily", "uv run a") is False
    assert rs.is_approved({}, "ledger", "daily", "uv run a") is False


def test_approve_replaces_that_apps_approvals(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a", "weekly": "uv run b"})
    rs.approve(hub, "plans", {"daily": "uv run p"})
    rs.approve(hub, "ledger", {"daily": "uv run a2"})
    state = rs.load_state(hub)
    assert rs.is_approved(state, "ledger", "daily", "uv run a") is False
    assert rs.is_approved(state, "ledger", "daily", "uv run a2") is True
    assert rs.is_approved(state, "ledger", "weekly", "uv run b") is False
    assert rs.is_approved(state, "plans", "daily", "uv run p") is True


def test_approve_nothing_drops_the_app(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a"})
    rs.approve(hub, "ledger", {})
    assert "ledger" not in rs.load_state(hub).get("approved", {})


def test_is_approved_ignores_a_damaged_state():
    assert rs.is_approved({"approved": "x"}, "ledger", "daily", "c") is False
    assert rs.is_approved({"approved": {"ledger": "x"}}, "ledger", "daily", "c") is False
    assert rs.is_approved({"approved": {"ledger": {"daily": 3}}}, "ledger", "daily", "3") is False


def test_chinese_and_dotted_names_round_trip_in_the_state(hub: Path):
    command = "uv run 报告.py --标题 '本周 账本'"
    rs.approve(hub, "my.app", {"daily": command})
    state = rs.load_state(hub)
    assert rs.is_approved(state, "my.app", "daily", command) is True


# --- notes ---


def test_notes_append_in_order(hub: Path):
    rs.add_note(hub, "daily", "ledger", "first", T1)
    rs.add_note(hub, "daily", "plans", "second", T2)
    notes = rs.read_notes(hub, "daily")
    assert [n["text"] for n in notes] == ["first", "second"]
    assert [n["from"] for n in notes] == ["ledger", "plans"]
    assert [n["at"] for n in notes] == [T1.isoformat(), T2.isoformat()]
    assert rs.read_notes(hub, "weekly") == []


def test_note_is_one_json_line_in_the_period_file(hub: Path):
    rs.add_note(hub, "daily", "ledger", "多行\n文本", T1)
    raw = (hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl").read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8")) == {
        "at": T1.isoformat(), "from": "ledger", "text": "多行\n文本",
    }
    assert "多行".encode() in raw  # not escaped to \uXXXX


def test_drop_notes_keeps_the_later_ones(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    rs.add_note(hub, "daily", "b", "second", T2)
    rs.drop_notes(hub, "daily", 1)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["second"]
    rs.add_note(hub, "daily", "c", "third", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["second", "third"]


def test_drop_all_notes_and_overshoot(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    rs.add_note(hub, "daily", "b", "second", T2)
    rs.drop_notes(hub, "daily", 0)
    assert len(rs.read_notes(hub, "daily")) == 2
    rs.drop_notes(hub, "daily", 5)
    assert rs.read_notes(hub, "daily") == []
    rs.drop_notes(hub, "weekly", 1)  # nothing there: no error
    assert rs.read_notes(hub, "weekly") == []


def test_a_corrupt_line_is_skipped(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{broken\n\n[1, 2]\n")
    rs.add_note(hub, "daily", "b", "second", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["first", "second"]


def test_a_note_without_a_text_and_a_sender_is_skipped(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    damaged = [
        "{}",
        '{"from": "a"}',
        '{"text": "x"}',
        '{"from": 1, "text": "x"}',
        '{"from": "a", "text": null}',
        '{"from": "a", "text": ["x"]}',
    ]
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(damaged) + "\n")
    rs.add_note(hub, "daily", "b", "second", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["first", "second"]
    rs.drop_notes(hub, "daily", 1)  # counts the notes read_notes returns, not the damaged lines
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["second"]


def test_drop_counts_notes_not_corrupt_lines(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{broken\n")
    rs.add_note(hub, "daily", "b", "second", T2)
    rs.add_note(hub, "daily", "c", "third", T2)
    rs.drop_notes(hub, "daily", 2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["third"]


def test_a_note_after_a_torn_last_line_is_not_glued_to_it(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    with path.open("ab") as fh:
        fh.write(b'{"at": "2026')  # a write that was cut off
    rs.add_note(hub, "daily", "b", "second", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["first", "second"]


def test_a_line_cut_in_the_middle_of_a_character_costs_only_that_line(hub: Path):
    rs.add_note(hub, "daily", "a", "first", T1)
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    with path.open("ab") as fh:
        fh.write('{"text": "报'.encode()[:-1])  # two of the three bytes of 报
    rs.add_note(hub, "daily", "b", "第二", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["first", "第二"]
    rs.drop_notes(hub, "daily", 1)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["第二"]


def test_unicode_line_separators_in_a_note_stay_in_its_line(hub: Path):
    text = "报告 第二行 第三行\x85结束"
    rs.add_note(hub, "daily", "a", text, T1)
    rs.add_note(hub, "daily", "b", "next", T2)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == [text, "next"]
    rs.drop_notes(hub, "daily", 1)
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["next"]


def test_chinese_note_round_trips(hub: Path):
    rs.add_note(hub, "weekly", "账本", "本周花销偏高", T1)
    assert rs.read_notes(hub, "weekly")[0]["from"] == "账本"
    assert rs.read_notes(hub, "weekly")[0]["text"] == "本周花销偏高"


# --- drafts ---


def test_drafts_put_read_clear_per_period(hub: Path):
    rs.put_draft(hub, "daily", "ledger", "今天花了 30 元\n")
    rs.put_draft(hub, "daily", "plans", "two")
    rs.put_draft(hub, "weekly", "ledger", "week")
    assert rs.read_draft(hub, "daily", "ledger") == "今天花了 30 元\n"
    assert (hub / ".cc-hub" / "reports" / "drafts" / "daily" / "ledger.md").is_file()
    rs.put_draft(hub, "daily", "ledger", "replaced")
    assert rs.read_draft(hub, "daily", "ledger") == "replaced"
    rs.clear_drafts(hub, "daily")
    assert rs.read_draft(hub, "daily", "ledger") == ""
    assert rs.read_draft(hub, "daily", "plans") == ""
    assert rs.read_draft(hub, "weekly", "ledger") == "week"
    rs.clear_drafts(hub, "daily")  # already clear: no error
    rs.clear_drafts(hub, "monthly")  # never existed: no error


def test_missing_draft_reads_empty(hub: Path):
    assert rs.read_draft(hub, "daily", "ledger") == ""


# --- forget_app ---


def test_forget_app_removes_its_approvals_and_drafts_only(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a"})
    rs.approve(hub, "plans", {"daily": "uv run p"})
    rs.put_draft(hub, "daily", "ledger", "l-d")
    rs.put_draft(hub, "weekly", "ledger", "l-w")
    rs.put_draft(hub, "daily", "plans", "p-d")
    rs.record_run(hub, "daily", T1, sent=True)
    rs.add_note(hub, "daily", "ledger", "keep me", T1)

    rs.forget_app(hub, "ledger")

    state = rs.load_state(hub)
    assert rs.is_approved(state, "ledger", "daily", "uv run a") is False
    assert rs.is_approved(state, "plans", "daily", "uv run p") is True
    assert rs.read_draft(hub, "daily", "ledger") == ""
    assert rs.read_draft(hub, "weekly", "ledger") == ""
    assert rs.read_draft(hub, "daily", "plans") == "p-d"
    assert rs.last_run(state, "daily") == T1
    assert [n["text"] for n in rs.read_notes(hub, "daily")] == ["keep me"]


def test_forget_app_that_has_nothing_is_a_no_op(hub: Path):
    rs.forget_app(hub, "ledger")
    assert rs.load_state(hub) == {}
    assert not (hub / rs.STATE_DIR / "state.toml").exists()


# --- runs ---


def test_record_run_without_sending_sets_only_last_run(hub: Path):
    rs.record_run(hub, "daily", T1, sent=False)
    state = rs.load_state(hub)
    assert rs.last_run(state, "daily") == T1
    assert rs.last_sent(state, "daily") is None
    assert state["runs"]["daily"] == {"last_run": T1}


def test_record_run_sent_sets_both_and_keeps_last_sent_otherwise(hub: Path):
    rs.record_run(hub, "daily", T1, sent=True)
    rs.record_run(hub, "weekly", T1, sent=False)
    state = rs.load_state(hub)
    assert rs.last_run(state, "daily") == T1 and rs.last_sent(state, "daily") == T1

    rs.record_run(hub, "daily", T2, sent=False)
    state = rs.load_state(hub)
    assert rs.last_run(state, "daily") == T2
    assert rs.last_sent(state, "daily") == T1
    assert rs.last_run(state, "weekly") == T1
    assert rs.last_sent(state, "weekly") is None


def test_run_times_come_back_timezone_aware_and_equal(hub: Path):
    rs.record_run(hub, "daily", T2, sent=True)
    got = rs.last_run(rs.load_state(hub), "daily")
    assert isinstance(got, datetime) and got.tzinfo is not None
    assert got == T2 and got.utcoffset() == timedelta(hours=8)


def test_run_times_of_unknown_periods_or_bad_values_are_none():
    assert rs.last_run({}, "daily") is None
    assert rs.last_sent({}, "daily") is None
    assert rs.last_run({"runs": {"daily": {"last_run": "yesterday"}}}, "daily") is None
    assert rs.last_run({"runs": {"daily": "x"}}, "daily") is None
    assert rs.last_run({"runs": 3}, "daily") is None


def test_approvals_and_runs_share_one_state_file_without_clobbering(hub: Path):
    rs.approve(hub, "ledger", {"daily": "uv run a"})
    rs.record_run(hub, "daily", T1, sent=True)
    rs.approve(hub, "plans", {"daily": "uv run p"})
    rs.record_run(hub, "daily", T2, sent=False)
    state = rs.load_state(hub)
    assert rs.is_approved(state, "ledger", "daily", "uv run a")
    assert rs.is_approved(state, "plans", "daily", "uv run p")
    assert rs.last_sent(state, "daily") == T1


# --- nothing escapes its directory ---

BAD = ["", ".", "..", "../x", "a/b", "a\\b", "x..y", "/abs", "C:evil", "a\x00b"]


@pytest.mark.parametrize("bad", BAD)
def test_period_cannot_leave_its_directory(hub: Path, bad: str):
    with pytest.raises(ValueError):
        rs.add_note(hub, bad, "ledger", "x", T1)
    with pytest.raises(ValueError):
        rs.read_notes(hub, bad)
    with pytest.raises(ValueError):
        rs.drop_notes(hub, bad, 1)
    with pytest.raises(ValueError):
        rs.put_draft(hub, bad, "ledger", "x")
    with pytest.raises(ValueError):
        rs.read_draft(hub, bad, "ledger")
    with pytest.raises(ValueError):
        rs.clear_drafts(hub, bad)


@pytest.mark.parametrize("bad", BAD)
def test_app_cannot_leave_its_directory(hub: Path, bad: str):
    with pytest.raises(ValueError):
        rs.put_draft(hub, "daily", bad, "x")
    with pytest.raises(ValueError):
        rs.read_draft(hub, "daily", bad)
    with pytest.raises(ValueError):
        rs.forget_app(hub, bad)


def test_nothing_was_written_outside_the_reports_dir(hub: Path, tmp_path: Path):
    before = {p for p in tmp_path.rglob("*")}
    for bad in ("../../escape", "..\\..\\escape"):
        with pytest.raises(ValueError):
            rs.put_draft(hub, bad, "ledger", "x")
        with pytest.raises(ValueError):
            rs.put_draft(hub, "daily", bad, "x")
        with pytest.raises(ValueError):
            rs.add_note(hub, bad, "ledger", "x", T1)
    assert {p for p in tmp_path.rglob("*")} == before


# --- locks ---


def test_state_lock_is_a_file_under_the_reports_dir_and_is_released(hub: Path):
    lock = hub / ".cc-hub" / "reports" / "state.lock"
    with rs.state_lock(hub):
        assert lock.is_file()
    assert not lock.exists()
    with rs.state_lock(hub):  # and can be taken again
        pass
    assert not lock.exists()


def test_state_lock_is_released_when_the_block_fails(hub: Path):
    with pytest.raises(RuntimeError), rs.state_lock(hub):
        raise RuntimeError("boom")
    assert not (hub / rs.STATE_DIR / "state.lock").exists()


def test_state_lock_held_by_a_live_holder_times_out(hub: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rs, "STATE_LOCK_WAIT", 0.3)
    with rs.state_lock(hub):
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="the reports state is busy; try again shortly"):
            with rs.state_lock(hub):
                pytest.fail("the lock was taken twice")
        assert 0.25 <= time.monotonic() - started < 5
        assert (hub / rs.STATE_DIR / "state.lock").is_file()  # the holder's lock is untouched


def test_state_lock_waits_for_the_holder_to_let_go(hub: Path):
    holder = rs.state_lock(hub)
    holder.__enter__()
    timer = threading.Timer(0.3, lambda: holder.__exit__(None, None, None))
    timer.start()
    try:
        started = time.monotonic()
        with rs.state_lock(hub):
            assert time.monotonic() - started >= 0.2
    finally:
        timer.join()


def test_state_lock_takes_over_a_stale_lock(hub: Path):
    lock = hub / rs.STATE_DIR / "state.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("123 left-behind", encoding="utf-8")
    old = time.time() - 61
    os.utime(lock, (old, old))
    with rs.state_lock(hub):
        assert lock.read_text(encoding="utf-8") != "123 left-behind"
    assert not lock.exists()


def test_state_lock_does_not_remove_a_lock_that_is_no_longer_its_own(hub: Path):
    lock = hub / rs.STATE_DIR / "state.lock"
    with rs.state_lock(hub):
        lock.write_text("999 someone-else", encoding="utf-8")  # taken over meanwhile
    assert lock.read_text(encoding="utf-8") == "999 someone-else"


def test_lock_helpers(hub: Path):
    path = hub / rs.STATE_DIR / "x.lock"
    token = rs.acquire_lock(path, stale_after=3600)
    assert token is not None and path.read_text(encoding="utf-8") == token
    assert rs.acquire_lock(path, stale_after=3600) is None  # held
    old = time.time() - 1000
    os.utime(path, (old, old))
    rs.refresh_lock(path, token)
    assert time.time() - path.stat().st_mtime < 60  # refreshed
    os.utime(path, (old, old))
    rs.refresh_lock(path, "not-the-token")
    assert time.time() - path.stat().st_mtime > 900  # not ours: left alone
    rs.release_lock(path, "not-the-token")
    assert path.exists()
    rs.release_lock(path, token)
    assert not path.exists()
    rs.release_lock(path, token)  # already gone: nothing happens
    rs.refresh_lock(path, token)
