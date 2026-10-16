# -*- coding: utf-8 -*-
import json
import os
import shlex
import shutil
import sys
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cc_hub import cronoverrides, reportbuild, reports, reportstate
from cc_hub.reportbuild import (
    MAX_SECTION_CHARS,
    STRINGS,
    Built,
    build,
    plan,
    run_command,
    strings_for,
    window,
)
from tests.conftest import fake_app, write

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=TZ)
REPORT_CRON = '---\nschedule: "0 8 * * *"\ndefault: false\nsession: new_per_run\n---\nx\n'


def section(command: str | None = None, title: str | None = None) -> str:
    """A section file; quoted values are verbatim in the front matter, so no escaping."""
    lines = []
    if command is not None:
        lines.append(f'command: "{command}"')
    if title is not None:
        lines.append(f'title: "{title}"')
    return "---\n" + "".join(line + "\n" for line in lines) + "---\n"


def install(hub: Path, app: str, period: str, text: str) -> None:
    if (hub / "apps" / app).exists():  # fake_app registers an app once
        write(hub / "apps" / app / "reports" / f"{period}.md", text)
    else:
        fake_app(hub, app, {f"reports/{period}.md": text})


def set_language(hub: Path, tag: str) -> None:
    reports.save_language(hub, tag)


def periods_on(hub: Path, *periods: str) -> None:
    for p in reports.PERIODS:
        write(hub / f"cron/report-{p}.md", REPORT_CRON)
    for p in periods:
        cronoverrides.save(hub, f"report-{p}", {"enabled": True})


def note(hub: Path, period: str, source: str, text: str, at: datetime) -> None:
    reportstate.add_note(hub, period, source, text, at)


class Runner:
    """A runner that does not run anything: canned results by command, and a record of the calls."""

    def __init__(self, results: dict[str, tuple[str, str | None]] | None = None):
        self.results = results or {}
        self.calls: list[tuple[Path, str, dict[str, str]]] = []

    def __call__(self, hub: Path, command: str, env: dict[str, str]):
        self.calls.append((hub, command, env))
        return self.results.get(command, ("", None))


def py(script: str) -> str:
    """A command line that runs `script` with this interpreter, quoted as run_command splits it."""
    return shlex.join([sys.executable, "-c", script])


# --- strings and window ---


def test_strings_exact_wording():
    assert set(STRINGS) == {"en", "zh"}
    keys = {*reports.PERIODS, "notes", "failed", "unapproved", "cut"}
    assert set(STRINGS["en"]) == set(STRINGS["zh"]) == keys
    assert [STRINGS["en"][p] for p in reports.PERIODS] == [
        "Daily report", "Weekly report", "Monthly report", "Quarterly report", "Yearly report",
    ]
    assert [STRINGS["zh"][p] for p in reports.PERIODS] == ["日报", "周报", "月报", "季报", "年报"]
    assert STRINGS["en"]["notes"] == "Notes" and STRINGS["zh"]["notes"] == "留言"
    assert STRINGS["en"]["failed"] == "{title}: this section failed: {line}"
    assert STRINGS["zh"]["failed"] == "{title}：这一段出错了：{line}"
    assert STRINGS["en"]["unapproved"] == (
        "{title}: not run, because its command is not approved on this machine. "
        "Approve it with cc-hub report approve {app}."
    )
    assert STRINGS["zh"]["unapproved"] == (
        "{title}：没有运行，因为它的命令还没在这台机器上批准。批准：cc-hub report approve {app}"
    )
    assert STRINGS["en"]["cut"] == "(cut: too long)"
    assert STRINGS["zh"]["cut"] == "（太长，已截断）"


@pytest.mark.parametrize(
    ("language", "expect"),
    [(None, "en"), ("", "en"), ("en", "en"), ("en-US", "en"), ("fr", "en"),
     ("zh", "zh"), ("zh-CN", "zh"), ("zh-TW", "zh"), ("ZH-cn", "zh")],
)
def test_strings_for_language(language, expect):
    assert strings_for(language) is STRINGS[expect]


def test_window_first_run_and_month_clamp():
    since, until = window("monthly", datetime(2026, 3, 31, 9, tzinfo=TZ), None)
    assert since.date() == date(2026, 2, 28) and until == datetime(2026, 3, 31, 9, tzinfo=TZ)
    assert since.tzinfo == TZ and since.hour == 9
    last = datetime(2026, 3, 1, 9, tzinfo=UTC)
    assert window("monthly", datetime(2026, 3, 31, 9, tzinfo=TZ), last)[0] == last


@pytest.mark.parametrize(
    ("period", "now", "since"),
    [
        ("daily", datetime(2026, 3, 1, 8, tzinfo=TZ), datetime(2026, 2, 28, 8, tzinfo=TZ)),
        ("weekly", datetime(2026, 3, 3, 20, tzinfo=TZ), datetime(2026, 2, 24, 20, tzinfo=TZ)),
        ("monthly", datetime(2028, 3, 31, 9, tzinfo=TZ), datetime(2028, 2, 29, 9, tzinfo=TZ)),
        ("monthly", datetime(2026, 1, 15, 9, tzinfo=TZ), datetime(2025, 12, 15, 9, tzinfo=TZ)),
        ("quarterly", datetime(2026, 5, 31, 9, tzinfo=TZ), datetime(2026, 2, 28, 9, tzinfo=TZ)),
        ("quarterly", datetime(2026, 1, 1, 9, 10, tzinfo=TZ),
         datetime(2025, 10, 1, 9, 10, tzinfo=TZ)),
        ("quarterly", datetime(2026, 11, 30, 9, tzinfo=TZ), datetime(2026, 8, 30, 9, tzinfo=TZ)),
        ("yearly", datetime(2026, 1, 1, 9, 20, tzinfo=TZ), datetime(2025, 1, 1, 9, 20, tzinfo=TZ)),
        ("yearly", datetime(2028, 2, 29, 9, tzinfo=TZ), datetime(2027, 2, 28, 9, tzinfo=TZ)),
    ],
)
def test_window_one_period_back(period, now, since):
    assert window(period, now, None) == (since, now)


# --- plan ---


def test_plan_lists_enabled_sections_and_notes(hub: Path):
    install(hub, "mail", "daily", section("uv run mail.py", "Mail"))
    install(hub, "plans", "daily", section(None, "Plans"))
    reportstate.approve(hub, "plans", {"daily": "something else"})
    note(hub, "daily", "me", "hi", NOW)
    note(hub, "daily", "me", "again", NOW)
    got = plan(hub, "daily", NOW)
    assert got == {
        "period": "daily",
        "language": "en",
        "since": "2026-10-15T09:00:00+08:00",
        "until": "2026-10-16T09:00:00+08:00",
        "sections": [
            {"app": "mail", "kind": "command", "title": "Mail",
             "file": "apps/mail/reports/daily.md", "approved": False, "error": None},
            {"app": "plans", "kind": "instruction", "title": "Plans",
             "file": "apps/plans/reports/daily.md", "approved": None, "error": None},
        ],
        "notes": 2,
        "empty": False,
    }
    reportstate.approve(hub, "mail", {"daily": "uv run mail.py"})
    assert plan(hub, "daily", NOW)["sections"][0]["approved"] is True
    json.dumps(got)  # plain data


def test_plan_empty_hub_and_the_language_and_last_run(hub: Path):
    got = plan(hub, "weekly", NOW)
    assert got["sections"] == [] and got["notes"] == 0 and got["empty"] is True
    set_language(hub, "zh-CN")
    reportstate.record_run(hub, "weekly", datetime(2026, 10, 9, 20, tzinfo=TZ), sent=True)
    got = plan(hub, "weekly", NOW)
    assert got["language"] == "zh-CN"
    assert datetime.fromisoformat(got["since"]) == datetime(2026, 10, 9, 20, tzinfo=TZ)
    assert datetime.fromisoformat(got["until"]) == NOW


def test_plan_notes_without_sections_is_not_empty(hub: Path):
    note(hub, "daily", "me", "hi", NOW)
    got = plan(hub, "daily", NOW)
    assert got["sections"] == [] and got["notes"] == 1 and got["empty"] is False


def test_plan_leaves_out_sections_that_are_off(hub: Path):
    install(hub, "mail", "daily", section("uv run mail.py"))
    install(hub, "plans", "daily", section(None))
    install(hub, "broken", "daily", "no frontmatter at all")
    reports.save_section(hub, "plans/daily", False)
    reports.save_section(hub, "broken/daily", False)
    assert [s["app"] for s in plan(hub, "daily", NOW)["sections"]] == ["mail"]


BROKEN = "apps/broken/reports/daily.md: needs a frontmatter block between --- lines"


def test_plan_lists_a_section_whose_file_is_broken_with_its_error(hub: Path):
    install(hub, "broken", "daily", "no frontmatter at all")
    got = plan(hub, "daily", NOW)
    assert got["sections"] == [
        {"app": "broken", "kind": None, "title": "broken", "file": "apps/broken/reports/daily.md",
         "approved": None, "error": BROKEN},
    ]
    assert got["empty"] is False  # the report says what is wrong: it is not empty


def test_plan_unknown_period(hub: Path):
    with pytest.raises(reports.ReportError, match="not a report period"):
        plan(hub, "hourly", NOW)


def test_plan_counts_routed_notes_like_build_includes_them(hub: Path):
    periods_on(hub, "weekly")  # daily is off: its notes go to the weekly report
    note(hub, "daily", "a", "from daily", NOW)
    note(hub, "weekly", "b", "from weekly", NOW)
    note(hub, "monthly", "c", "monthly one", NOW)  # monthly is not on, nor does it route to weekly
    got = plan(hub, "weekly", NOW)
    built = build(hub, "weekly", NOW)
    assert got["notes"] == built.notes == 2 and got["empty"] is False
    assert plan(hub, "daily", NOW)["notes"] == 1  # a period that is off still has its own


def test_plan_empty_agrees_with_build_when_only_a_damaged_note_exists(hub: Path):
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    write(path, "{}\n")
    got = plan(hub, "daily", NOW)
    assert got["notes"] == 0 and got["empty"] is True
    assert build(hub, "daily", NOW).text == ""


# --- build ---


def test_build_layout_and_order(hub: Path):
    set_language(hub, "zh-CN")
    install(hub, "mail", "daily", section("uv run mail.py", "邮件"))
    install(hub, "plans", "daily", section(None, "计划"))
    reportstate.approve(hub, "mail", {"daily": "uv run mail.py"})
    reportstate.put_draft(hub, "daily", "plans", "今天三件事：\n\n1. 写报告\n")
    note(hub, "daily", "feishu", "别忘了周五的会", NOW)
    runner = Runner({"uv run mail.py": ("3 封新邮件\n", None)})
    built = build(hub, "daily", NOW, runner=runner)
    assert built.text == (
        "# 日报 · 2026-10-16\n"
        "\n"
        "## 邮件\n"
        "\n"
        "3 封新邮件\n"
        "\n"
        "## 计划\n"
        "\n"
        "今天三件事：\n"
        "\n"
        "1. 写报告\n"
        "\n"
        "## 留言\n"
        "\n"
        "- feishu: 别忘了周五的会"
    )
    assert built == Built(built.text, sections=2, notes=1, included={"daily": 1})


def test_build_english_and_title_falls_back_to_the_app_name(hub: Path):
    install(hub, "mail", "weekly", section("uv run mail.py"))
    reportstate.approve(hub, "mail", {"weekly": "uv run mail.py"})
    note(hub, "weekly", "a", "one", NOW)
    note(hub, "weekly", "b", "two", NOW + timedelta(minutes=1))
    built = build(hub, "weekly", NOW, runner=Runner({"uv run mail.py": ("ok", None)}))
    assert built.text == (
        "# Weekly report · 2026-10-16\n\n## mail\n\nok\n\n## Notes\n\n- a: one\n- b: two"
    )
    assert built.sections == 1 and built.notes == 2 and built.included == {"weekly": 2}


def test_title_date_is_the_date_of_now_in_its_own_timezone(hub: Path):
    install(hub, "plans", "daily", section(None))
    reportstate.put_draft(hub, "daily", "plans", "x")
    late = datetime(2026, 12, 31, 23, 30, tzinfo=TZ)
    assert build(hub, "daily", late).text.startswith("# Daily report · 2026-12-31\n")


def test_sections_follow_the_configured_order(hub: Path):
    for app in ("a", "b", "c"):
        install(hub, app, "daily", section(None))
        reportstate.put_draft(hub, "daily", app, f"text of {app}")
    toml = hub / "hub.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[report]\norder = ["c", "a"]\n', encoding="utf-8"
    )
    text = build(hub, "daily", NOW).text
    assert text.index("text of c") < text.index("text of a") < text.index("text of b")


def test_empty_sections_are_left_out_and_all_empty_gives_empty_text(hub: Path):
    install(hub, "mail", "daily", section("uv run mail.py", "Mail"))
    install(hub, "plans", "daily", section(None, "Plans"))
    install(hub, "todo", "daily", section("uv run todo.py", "Todo"))
    reportstate.approve(hub, "mail", {"daily": "uv run mail.py"})
    reportstate.approve(hub, "todo", {"daily": "uv run todo.py"})
    runner = Runner({"uv run mail.py": ("  \n\n", None), "uv run todo.py": ("two tasks", None)})
    # plans has no draft, mail prints only blanks
    built = build(hub, "daily", NOW, runner=runner)
    assert built.text == "# Daily report · 2026-10-16\n\n## Todo\n\ntwo tasks"
    assert built.sections == 1 and built.notes == 0 and built.included == {}
    # a draft of only whitespace is empty too
    reportstate.put_draft(hub, "daily", "plans", " \n\n")
    runner = Runner({"uv run mail.py": ("", None), "uv run todo.py": ("", None)})
    assert build(hub, "daily", NOW, runner=runner) == Built("", 0, 0, {})


def test_no_sections_no_notes_is_empty(hub: Path):
    assert build(hub, "yearly", NOW) == Built("", 0, 0, {})


def test_notes_alone_make_a_report(hub: Path):
    note(hub, "daily", "me", "hello", NOW)
    built = build(hub, "daily", NOW)
    assert built.text == "# Daily report · 2026-10-16\n\n## Notes\n\n- me: hello"
    assert (built.sections, built.notes, built.included) == (0, 1, {"daily": 1})


def test_unapproved_command_is_not_run(hub: Path):
    install(hub, "mail", "daily", section("uv run mail.py", "Mail"))
    runner = Runner({"uv run mail.py": ("SHOULD NOT APPEAR", None)})
    built = build(hub, "daily", NOW, runner=runner)
    assert runner.calls == []
    assert built.text == (
        "# Daily report · 2026-10-16\n\n## Mail\n\n"
        "Mail: not run, because its command is not approved on this machine. "
        "Approve it with cc-hub report approve mail."
    )
    assert built.sections == 1  # the line is content


def test_unapproved_line_in_chinese(hub: Path):
    set_language(hub, "zh")
    install(hub, "mail", "daily", section("uv run mail.py", "邮件"))
    text = build(hub, "daily", NOW, runner=Runner()).text
    assert text.endswith(
        "邮件：没有运行，因为它的命令还没在这台机器上批准。批准：cc-hub report approve mail"
    )


def test_a_command_changed_after_approval_is_not_run(hub: Path):
    install(hub, "mail", "daily", section("uv run mail.py --all", "Mail"))
    reportstate.approve(hub, "mail", {"daily": "uv run mail.py"})
    runner = Runner()
    assert "not approved" in build(hub, "daily", NOW, runner=runner).text
    assert runner.calls == []


def test_approval_is_per_period(hub: Path):
    install(hub, "mail", "weekly", section("uv run mail.py", "Mail"))
    reportstate.approve(hub, "mail", {"daily": "uv run mail.py"})
    runner = Runner()
    assert "not approved" in build(hub, "weekly", NOW, runner=runner).text
    assert runner.calls == []


def test_failed_and_cut_sections(hub: Path):
    install(hub, "a", "daily", section("run-a", "Alpha"))
    install(hub, "b", "daily", section("run-b", "Beta"))
    install(hub, "c", "daily", section("run-c", "Gamma"))
    reportstate.approve(hub, "a", {"daily": "run-a"})
    reportstate.approve(hub, "b", {"daily": "run-b"})
    reportstate.approve(hub, "c", {"daily": "run-c"})
    long = "x" * (MAX_SECTION_CHARS + 50)
    exact = "y" * MAX_SECTION_CHARS
    runner = Runner({"run-a": ("", "exit 3"), "run-b": (long, None), "run-c": (exact, None)})
    built = build(hub, "daily", NOW, runner=runner)
    parts = built.text.split("\n\n## ")
    assert parts[1] == "Alpha\n\nAlpha: this section failed: exit 3"
    beta = parts[2]
    assert beta == "Beta\n\n" + "x" * MAX_SECTION_CHARS + "\n(cut: too long)"
    assert parts[3] == "Gamma\n\n" + exact  # exactly the limit is not cut
    assert built.sections == 3


def test_failed_line_in_chinese_and_output_alongside_error_is_dropped(hub: Path):
    set_language(hub, "zh-CN")
    install(hub, "a", "daily", section("run-a", "甲"))
    reportstate.approve(hub, "a", {"daily": "run-a"})
    runner = Runner({"run-a": ("half an answer", "boom")})
    text = build(hub, "daily", NOW, runner=runner).text
    assert text.endswith("## 甲\n\n甲：这一段出错了：boom")
    assert "half an answer" not in text


def test_a_section_whose_file_is_broken_is_a_failed_line(hub: Path):
    install(hub, "broken", "daily", "no frontmatter at all")
    reportstate.put_draft(hub, "daily", "broken", "a draft is not used for a broken file")
    runner = Runner()
    built = build(hub, "daily", NOW, runner=runner)
    assert built.text == (
        f"# Daily report · 2026-10-16\n\n## broken\n\nbroken: this section failed: {BROKEN}"
    )
    assert built.sections == 1 and runner.calls == []
    reports.save_section(hub, "broken/daily", False)  # switched off, it is left out
    assert build(hub, "daily", NOW).text == ""


def test_a_long_error_is_cut_to_300_characters(hub: Path):
    install(hub, "a", "daily", section("run-a", "Alpha"))
    reportstate.approve(hub, "a", {"daily": "run-a"})
    prefix = "Alpha: this section failed: "
    text = build(hub, "daily", NOW, runner=Runner({"run-a": ("", "e" * 5000)})).text
    assert text.endswith("\n\n" + prefix + "e" * 299 + "…")
    text = build(hub, "daily", NOW, runner=Runner({"run-a": ("", "f" * 300)})).text
    assert text.endswith("\n\n" + prefix + "f" * 300)  # exactly the limit is not cut
    # a file error is cut the same way (the key of a broken line is in it)
    install(hub, "b", "daily", "---\n" + "k" * 400 + ': "unclosed\n---\n')
    line = build(hub, "daily", NOW, runner=Runner()).text.split("\n\n## b\n\n", 1)[1]
    line = line.split("\n\n", 1)[0]
    assert line.startswith("b: this section failed: apps/b/reports/daily.md: kkk")
    assert len(line) == len("b: this section failed: ") + 300 and line.endswith("…")


def test_cut_marker_in_chinese(hub: Path):
    set_language(hub, "zh-CN")
    install(hub, "a", "daily", section("run-a", "甲"))
    reportstate.approve(hub, "a", {"daily": "run-a"})
    runner = Runner({"run-a": ("z" * (MAX_SECTION_CHARS + 1), None)})
    text = build(hub, "daily", NOW, runner=runner).text
    assert text.endswith("z\n（太长，已截断）")


def test_runner_gets_the_hub_the_command_and_the_env(hub: Path):
    set_language(hub, "zh-CN")
    install(hub, "mail", "monthly", section("run-mail", "Mail"))
    reportstate.approve(hub, "mail", {"monthly": "run-mail"})
    since = datetime(2026, 9, 1, 9, tzinfo=TZ)
    reportstate.record_run(hub, "monthly", since, sent=True)
    runner = Runner({"run-mail": ("ok", None)})
    build(hub, "monthly", NOW, runner=runner)
    [(got_hub, command, env)] = runner.calls
    assert Path(got_hub) == hub.absolute() and command == "run-mail"
    assert env == {
        "CC_HUB_DIR": str(hub.absolute()),
        "CC_HUB_REPORT_PERIOD": "monthly",
        "CC_HUB_REPORT_SINCE": "2026-09-01T09:00:00+08:00",
        "CC_HUB_REPORT_UNTIL": "2026-10-16T09:00:00+08:00",
        "CC_HUB_LANGUAGE": "zh-CN",
    }


def test_env_language_is_en_when_unset_and_since_is_one_period_back_on_a_first_run(hub: Path):
    install(hub, "mail", "daily", section("run-mail"))
    reportstate.approve(hub, "mail", {"daily": "run-mail"})
    runner = Runner()
    build(hub, "daily", NOW, runner=runner)
    env = runner.calls[0][2]
    assert env["CC_HUB_LANGUAGE"] == "en"
    assert env["CC_HUB_REPORT_SINCE"] == "2026-10-15T09:00:00+08:00"


def test_each_section_runs_once_in_order(hub: Path):
    for app in ("b", "a"):
        install(hub, app, "daily", section(f"run-{app}", app))
        reportstate.approve(hub, app, {"daily": f"run-{app}"})
    runner = Runner({"run-a": ("A", None), "run-b": ("B", None)})
    build(hub, "daily", NOW, runner=runner)
    assert [c[1] for c in runner.calls] == ["run-a", "run-b"]  # by app name without an order


def test_instruction_section_uses_the_draft_of_its_own_period_and_app(hub: Path):
    install(hub, "plans", "daily", section(None, "Plans"))
    install(hub, "plans", "weekly", section(None, "Plans"))
    reportstate.put_draft(hub, "daily", "plans", "daily draft")
    reportstate.put_draft(hub, "weekly", "plans", "weekly draft")
    assert "daily draft" in build(hub, "daily", NOW).text
    assert "weekly draft" not in build(hub, "daily", NOW).text


def test_build_does_not_touch_notes_or_drafts(hub: Path):
    install(hub, "plans", "daily", section(None))
    reportstate.put_draft(hub, "daily", "plans", "draft")
    note(hub, "daily", "me", "hi", NOW)
    build(hub, "daily", NOW)
    assert reportstate.read_draft(hub, "daily", "plans") == "draft"
    assert len(reportstate.read_notes(hub, "daily")) == 1
    assert reportstate.last_run(reportstate.load_state(hub), "daily") is None


def test_notes_routed_here_come_with_the_period_oldest_first(hub: Path):
    periods_on(hub, "weekly", "yearly")  # daily and monthly are off; quarterly too
    note(hub, "weekly", "w", "weekly note", NOW - timedelta(days=1))
    note(hub, "daily", "d", "daily note", NOW - timedelta(days=3))
    note(hub, "monthly", "m", "monthly note", NOW - timedelta(days=2))  # routes to yearly
    note(hub, "daily", "d2", "newer daily", NOW - timedelta(hours=1))
    weekly = build(hub, "weekly", NOW)
    assert weekly.text.endswith("- d: daily note\n- w: weekly note\n- d2: newer daily")
    assert weekly.notes == 3 and weekly.included == {"daily": 2, "weekly": 1}
    yearly = build(hub, "yearly", NOW)
    assert yearly.text.endswith("- m: monthly note")
    assert yearly.included == {"monthly": 1}
    daily = build(hub, "daily", NOW)  # daily is off, but it still reports its own notes
    assert daily.included == {"daily": 2}


def test_a_period_that_is_on_keeps_its_own_notes_out_of_the_longer_report(hub: Path):
    periods_on(hub, "daily", "weekly")
    note(hub, "daily", "d", "daily note", NOW)
    assert build(hub, "weekly", NOW) == Built("", 0, 0, {})
    assert build(hub, "daily", NOW).included == {"daily": 1}


def test_a_note_with_a_damaged_time_still_goes_in(hub: Path):
    path = hub / ".cc-hub" / "reports" / "notes" / "daily.jsonl"
    lines = [
        json.dumps({"at": "not a time", "from": "x", "text": "no time"}),
        json.dumps({"from": "y", "text": "no at"}),
        json.dumps({"at": "2026-10-16T08:00:00", "from": "z", "text": "naive time"}),
    ]
    write(path, "\n".join(lines) + "\n")
    note(hub, "daily", "w", "fine", NOW)
    built = build(hub, "daily", NOW)
    assert built.notes == 4
    assert set(built.text.splitlines()[-4:]) == {
        "- x: no time", "- y: no at", "- z: naive time", "- w: fine",
    }


def test_a_note_with_blank_lines_in_the_text(hub: Path):
    note(hub, "daily", "me", "line one\n\nline two", NOW)
    assert build(hub, "daily", NOW).text.endswith("- me: line one\n\nline two")


def test_build_checks_the_period(hub: Path):
    with pytest.raises(reports.ReportError, match="not a report period"):
        build(hub, "hourly", NOW)


def test_build_prints_nothing(hub: Path, capfd: pytest.CaptureFixture[str]):
    command = py("print('SECRET-OUT'); import sys; print('SECRET-ERR', file=sys.stderr)")
    install(hub, "mail", "daily", section(command, "Mail"))
    reportstate.approve(hub, "mail", {"daily": command})
    built = build(hub, "daily", NOW)
    assert "SECRET-OUT" in built.text
    seen = capfd.readouterr()
    assert seen.out == "" and seen.err == ""


def test_build_with_the_real_runner_end_to_end(hub: Path):
    command = py("print('hello from the section')")
    install(hub, "mail", "daily", section(command, "Mail"))
    reportstate.approve(hub, "mail", {"daily": command})
    built = build(hub, "daily", NOW)
    assert built.text == "# Daily report · 2026-10-16\n\n## Mail\n\nhello from the section"


def test_real_failure_is_reported_in_the_section(hub: Path):
    command = py("import sys; print('oops: bad thing', file=sys.stderr); sys.exit(2)")
    install(hub, "mail", "daily", section(command, "Mail"))
    reportstate.approve(hub, "mail", {"daily": command})
    assert build(hub, "daily", NOW).text.endswith("Mail: this section failed: oops: bad thing")


# --- run_command ---


def test_command_output_is_utf8(hub: Path):
    out = run_command(hub, py("print('邮件 3 封')"), {})
    assert out == ("邮件 3 封", None)


def test_command_output_is_stripped_and_has_unix_newlines(hub: Path):
    out = run_command(hub, py("print(); print('a'); print('b'); print()"), {})
    assert out == ("a\nb", None)


def test_command_gets_the_env(hub: Path):
    script = (
        "import os; print(os.environ['CC_HUB_REPORT_PERIOD'], os.environ['CC_HUB_LANGUAGE'], "
        "os.environ.get('PYTHONUTF8'))"
    )
    env = {"CC_HUB_REPORT_PERIOD": "weekly", "CC_HUB_LANGUAGE": "zh-CN"}
    assert run_command(hub, py(script), env) == ("weekly zh-CN 1", None)


def test_command_inherits_the_environment(hub: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CC_HUB_TEST_INHERITED", "yes")
    out = run_command(hub, py("import os; print(os.environ['CC_HUB_TEST_INHERITED'])"), {})
    assert out == ("yes", None)


def test_command_runs_in_the_hub(hub: Path):
    out = run_command(hub, py("import os; print(os.getcwd())"), {})
    assert out[1] is None and Path(out[0]).resolve() == hub.resolve()


def test_command_has_no_stdin(hub: Path):
    out = run_command(hub, py("import sys; print(repr(sys.stdin.read()))"), {})
    assert out == ("''", None)


def test_command_timeout(hub: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reportbuild, "SECTION_TIMEOUT", 1)
    out = run_command(hub, py("import time; time.sleep(5)"), {})
    assert out == ("", "timed out after 1 s")


def test_default_limits():
    assert reportbuild.SECTION_TIMEOUT == 300 and MAX_SECTION_CHARS == 20000


def test_command_failure_gives_the_first_stderr_line(hub: Path):
    script = (
        "import sys; print(); print('  first line ', file=sys.stderr); "
        "print('second', file=sys.stderr); sys.exit(3)"
    )
    assert run_command(hub, py(script), {}) == ("", "first line")


def test_command_failure_without_stderr_gives_the_exit_code(hub: Path):
    assert run_command(hub, py("import sys; print('out'); sys.exit(4)"), {}) == ("", "exit 4")


def test_command_failure_drops_the_stdout(hub: Path):
    script = "import sys; print('partial'); print('bad', file=sys.stderr); sys.exit(1)"
    out = run_command(hub, py(script), {})
    assert out == ("", "bad")


def test_command_not_found(hub: Path):
    out, error = run_command(hub, "cc-hub-test-no-such-program --flag", {})
    assert out == "" and error == "cc-hub-test-no-such-program: command not found"


def test_command_that_cannot_be_split(hub: Path):
    out, error = run_command(hub, 'echo "unclosed', {})
    assert out == "" and error and "quotation" in error


def test_empty_command(hub: Path):
    out, error = run_command(hub, "   ", {})
    assert out == "" and error


def test_command_found_on_path_with_its_extension(
    hub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    tools = tmp_path / "tools"
    if sys.platform == "win32":  # a .cmd shim, as npm and uv installers leave
        write(tools / "cc-hub-test-shim.cmd", "@echo off\r\necho shim says %1\r\n")
    else:
        script = tools / "cc-hub-test-shim"
        write(script, "#!/bin/sh\necho shim says $1\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    assert run_command(hub, "cc-hub-test-shim hi", {}) == ("shim says hi", None)


def test_command_with_a_relative_path_is_found_from_the_hub(hub: Path):
    if sys.platform == "win32":
        write(hub / "scripts" / "report.cmd", "@echo off\r\necho from the hub\r\n")
        command = "scripts/report.cmd"
    else:
        script = hub / "scripts" / "report.sh"
        write(script, "#!/bin/sh\necho from the hub\n")
        script.chmod(0o755)
        command = "scripts/report.sh"
    assert run_command(hub, command, {}) == ("from the hub", None)


# --- a timeout stops the whole process tree ---

CHILD = (
    "import os, sys, time\n"
    "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
    "time.sleep(10)\n"
)


def hanging_command(hub: Path) -> str:
    """A command line that starts a Python child sleeping 10 s: a .cmd shim, or an sh script."""
    scripts = hub / "scripts"
    write(scripts / "child.py", CHILD)
    if sys.platform == "win32":
        write(
            scripts / "hang.cmd",
            f'@echo off\r\n"{sys.executable}" "%~dp0child.py" "%~dp0pid.txt"\r\n',
        )
        return "scripts/hang.cmd"
    script = scripts / "hang.sh"
    write(
        script,
        f'#!/bin/sh\n{shlex.quote(sys.executable)} "$(dirname "$0")/child.py" '
        '"$(dirname "$0")/pid.txt"\n',
    )
    script.chmod(0o755)
    return "scripts/hang.sh"


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, check=False,
        ).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.skipif(
    sys.platform != "win32" and shutil.which("sh") is None, reason="needs sh to wrap the child"
)
def test_command_timeout_kills_the_children_too(hub: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reportbuild, "SECTION_TIMEOUT", 1)
    command = hanging_command(hub)
    started = time.monotonic()
    out = run_command(hub, command, {})
    elapsed = time.monotonic() - started
    assert out == ("", "timed out after 1 s")
    assert elapsed < 6, f"the timeout took {elapsed:.1f} s to take effect"
    pid_file = hub / "scripts" / "pid.txt"
    if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip():
        pid = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 3
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not alive(pid), "the child of the command was left running"


def test_a_stuck_pipe_cannot_hang_a_timeout(hub: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reportbuild, "SECTION_TIMEOUT", 1)
    monkeypatch.setattr(reportbuild, "REAP_TIMEOUT", 1)
    monkeypatch.setattr(reportbuild, "_kill_tree", lambda proc: None)  # nothing frees the pipes
    started = time.monotonic()
    out = run_command(hub, py("import time; time.sleep(4)"), {})
    elapsed = time.monotonic() - started
    assert out == ("", "timed out after 1 s")
    assert elapsed < 4
