# -*- coding: utf-8 -*-
import pytest

from cc_hub.crontasks import (
    DEFAULT_TIMEOUT_MINS,
    PLACEHOLDER_SCHEDULE,
    CronError,
    TaskDef,
    check_schedule,
    parse_task,
)


def test_prompt_task():
    d = parse_task(
        '---\nschedule: "0 3 * * *"  # nightly\ndefault: true\nsession: new_per_run\n---\nDo it.\n',
        where="x",
    )
    assert d == TaskDef("prompt", "0 3 * * *", True, "new_per_run", False, None, None, ())


def test_prompt_task_defaults():
    d = parse_task('---\nschedule: "0 3 * * *"\n---\nDo it.\n', where="x")
    assert d == TaskDef("prompt", "0 3 * * *", False, "reuse", False, None, None, ())


def test_silent_prompt_task():
    d = parse_task('---\nschedule: "0 3 * * *"\nsilent: true\n---\nDo it.\n', where="x")
    assert d.kind == "prompt" and d.silent is True


def test_exec_task_defaults_timeout():
    d = parse_task(
        '---\nschedule: "*/5 * * * *"\ndefault: true\n'
        'exec: "uv run apps/mail/scripts/mk.py poll"\n---\nWhat it does.\n',
        where="x",
    )
    assert (d.kind, d.exec, d.timeout_mins, d.session) == (
        "exec", "uv run apps/mail/scripts/mk.py poll", 10, None,
    )
    assert DEFAULT_TIMEOUT_MINS == 10


def test_exec_task_with_timeout():
    d = parse_task('---\nschedule: "*/5 * * * *"\nexec: "x"\ntimeout_mins: 5\n---\n', where="x")
    assert (d.kind, d.timeout_mins, d.allow) == ("exec", 5, ())


def test_on_demand_restricted_task():
    text = (
        '---\non_demand: true\ndefault: true\nsession: new_per_run\nsilent: true\n'
        'allow:\n  - "uv run apps/mail/scripts/mk.py bg"\n  - cc-hub memory log\n---\nBody\n'
    )
    d = parse_task(text, where="x")
    assert (d.kind, d.schedule, d.silent) == ("on_demand", None, True)
    assert d.allow == ("uv run apps/mail/scripts/mk.py bg", "cc-hub memory log")
    assert (d.exec, d.timeout_mins) == (None, None)


def test_allow_on_a_prompt_task_with_comments_and_blank_lines():
    text = (
        '---\nschedule: "0 3 * * *"\nsession: new_per_run\n'
        'allow:\n  - "a b"  # why\n\n  # a note\n  - c\ndefault: true\n---\n'
    )
    d = parse_task(text, where="x")
    assert d.allow == ("a b", "c")
    assert d.default is True  # a key after the list is still read


def test_quoted_value_keeps_hash():
    d = parse_task('---\nschedule: "0 3 * * *"\nexec: "echo a#b"\n---\n', where="x")
    assert d.exec == "echo a#b"


def test_comment_after_a_quoted_value_may_hold_quotes():
    d = parse_task('---\nschedule: "0 3 * * *"\nexec: "echo a"  # say "hi"\n---\n', where="x")
    assert d.exec == "echo a"


def test_unknown_keys_are_ignored():
    d = parse_task('---\nschedule: "0 3 * * *"\nowner: me\n---\n', where="x")
    assert d.kind == "prompt"


def test_crlf_file_parses():
    d = parse_task('---\r\nschedule: "0 3 * * *"\r\n---\r\nx\r\n', where="x")
    assert d.schedule == "0 3 * * *"


def test_no_frontmatter():
    with pytest.raises(CronError, match="^apps/a/cron/t.md: .*frontmatter"):
        parse_task("no frontmatter", where="apps/a/cron/t.md")


@pytest.mark.parametrize("head, words", [
    ('schedule: "* * * * *"\nexec: "x"\non_demand: true', "both"),
    ('on_demand: true\nschedule: "* * * * *"', "schedule"),
    ('default: true', "schedule is required"),
    ('schedule: "* * * * *"\nexec: ""', "exec"),
    ('schedule: "* * * * *"\nexec: "say "hi""', "single quotes"),
    ('schedule: "* * * * *"\nexec: "x"\nsession: reuse', "session"),
    ('schedule: "* * * * *"\nexec: "x"\ntimeout_mins: 0', "timeout_mins"),
    ('schedule: "* * * * *"\nexec: "x"\ntimeout_mins: soon', "timeout_mins"),
    ('schedule: "* * * * *"\ntimeout_mins: 5', "timeout_mins"),
    ('schedule: "* * * * *"\nexec: "x"\nallow:\n  - "x"', "allow"),
    ('on_demand: true\nsession: reuse\nallow:\n  - "x"', "new_per_run"),
    ('on_demand: true\nallow:\n  - "x"', "new_per_run"),
    ('on_demand: true\nsession: new_per_run\nallow:', "allow"),
    ('on_demand: true\nsession: new_per_run\nallow: "x"', "allow"),
    ('on_demand: true\nsession: new_per_run\nallow:\n  - ""', "allow"),
    ('schedule: "* * * * *"\nsession: sometimes', "session"),
    ('schedule: "* * * * *"\ndefault: yes', "default"),
    ('schedule: "* * * * *"\nsilent: maybe', "silent"),
    ('schedule: "61 * * * *x"', "schedule"),
    ('schedule: "* * * *"', "five fields"),
    ('schedule: "* * * * *\n', "closing"),
])
def test_definition_errors(head, words):
    with pytest.raises(CronError, match=words) as info:
        parse_task(f"---\n{head}\n---\nbody\n", where="apps/a/cron/t.md")
    assert str(info.value).startswith("apps/a/cron/t.md: ")


@pytest.mark.parametrize(
    "expr", ["0 3 * * *", "*/5 * * * *", "0 8 * * 1-5", "0 9 1,15 * *", "0 0 1 jan mon"]
)
def test_check_schedule_accepts(expr):
    assert check_schedule(expr) == expr


def test_check_schedule_strips():
    assert check_schedule("  0 3 * * *\t") == "0 3 * * *"


def test_placeholder_schedule_is_valid():
    assert check_schedule(PLACEHOLDER_SCHEDULE) == PLACEHOLDER_SCHEDULE


@pytest.mark.parametrize("expr", ["", "0 3 * *", "0 3 * * * *", "@daily", "0 3 * * * && rm"])
def test_check_schedule_rejects_the_wrong_field_count(expr):
    with pytest.raises(CronError, match="five fields"):
        check_schedule(expr)


@pytest.mark.parametrize("expr", ["0 3 * * $(rm)", "0 3 * * *;", '0 3 * * "*"', "0 3 * * 1-"])
def test_check_schedule_rejects_bad_fields(expr):
    with pytest.raises(CronError):
        check_schedule(expr)
