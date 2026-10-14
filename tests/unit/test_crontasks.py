# -*- coding: utf-8 -*-
import pytest

from cc_hub.cronoverrides import save
from cc_hub.crontasks import (
    DEFAULT_TIMEOUT_MINS,
    PLACEHOLDER_SCHEDULE,
    CronError,
    Task,
    TaskDef,
    check_schedule,
    discover,
    parse_task,
    pointer_prompt,
    registration_commands,
    rows,
)
from tests.conftest import MAIL_CRON, fake_app, write


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


def test_pointer_prompt():
    assert pointer_prompt("plans/morning", "apps/plans/cron/morning.md") == (
        "Scheduled task hub:plans/morning: follow the body of apps/plans/cron/morning.md "
        "in the hub."
    )


def test_rows_for_each_kind(hub):
    fake_app(hub, "mail", MAIL_CRON)
    by = {r["name"]: r for r in rows(hub)}
    mc = by["memory-consolidate"]
    assert mc["prompt"] == (
        "Scheduled task hub:memory-consolidate: follow the body of cron/memory-consolidate.md "
        "in the hub."
    )
    assert mc["commands"] == [
        'cc-connect cron add --cron "0 3 * * *" --prompt "' + mc["prompt"]
        + '" --session-mode new_per_run --desc "hub:memory-consolidate"'
    ]
    poll = by["mail/poll"]
    assert poll["prompt"] is None and poll["commands"] == [
        'cc-connect cron add --cron "*/5 * * * *" --exec "uv run apps/mail/scripts/mk.py poll" '
        '--timeout-mins 10 --desc "hub:mail/poll"',
        "cc-connect cron edit <id> mute true",
    ]
    triage = by["mail/triage"]
    assert triage["schedule"] is None and triage["allow"] == ["uv run apps/mail/scripts/mk.py bg"]
    assert triage["commands"] == [
        'cc-connect cron add --cron "0 0 1 1 *" --prompt "' + triage["prompt"]
        + '" --session-mode new_per_run --silent --desc "hub:mail/triage"',
        "cc-connect cron edit <id> enabled false",
    ]


def test_row_fields_of_each_kind(hub):
    fake_app(hub, "mail", MAIL_CRON)
    by = {r["name"]: r for r in rows(hub)}
    keys = {
        "name", "source", "file", "kind", "default", "file_schedule", "schedule", "overridden",
        "enabled", "session", "silent", "exec", "timeout_mins", "allow", "desc", "prompt",
        "commands", "error",
    }
    assert all(set(r) == keys for r in by.values())

    mc = by["memory-consolidate"]
    assert (mc["source"], mc["file"], mc["kind"], mc["desc"]) == (
        "hub", "cron/memory-consolidate.md", "prompt", "hub:memory-consolidate",
    )
    assert (mc["default"], mc["enabled"], mc["overridden"], mc["session"]) == (
        True, True, False, "new_per_run",
    )
    assert (mc["silent"], mc["exec"], mc["timeout_mins"], mc["allow"], mc["error"]) == (
        False, None, None, [], None,
    )

    poll = by["mail/poll"]
    assert (poll["source"], poll["file"], poll["kind"]) == (
        "mail", "apps/mail/cron/poll.md", "exec",
    )
    assert (poll["exec"], poll["timeout_mins"], poll["session"]) == (
        "uv run apps/mail/scripts/mk.py poll", 10, None,
    )
    assert (poll["file_schedule"], poll["schedule"]) == ("*/5 * * * *", "*/5 * * * *")

    triage = by["mail/triage"]
    assert triage["kind"] == "on_demand" and triage["file_schedule"] is None
    assert triage["session"] == "new_per_run"
    assert triage["silent"] is True  # an on-demand task is always registered silent


def test_rows_are_sorted_by_name(hub):
    fake_app(hub, "mail", MAIL_CRON)
    names = [r["name"] for r in rows(hub)]
    assert names == sorted(names) == ["mail/poll", "mail/triage", "memory-consolidate"]


def test_readme_is_not_a_task(hub):
    assert (hub / "cron" / "README.md").is_file()
    assert "README" not in {r["name"] for r in rows(hub)}


def test_silent_prompt_task_registers_silent(hub):
    write(hub / "cron/quiet.md", '---\nschedule: "0 8 * * *"\nsilent: true\n---\nHi.\n')
    r = next(r for r in rows(hub) if r["name"] == "quiet")
    assert r["silent"] is True and r["commands"] == [
        'cc-connect cron add --cron "0 8 * * *" --prompt "' + r["prompt"]
        + '" --session-mode reuse --silent --desc "hub:quiet"'
    ]


def test_on_demand_task_is_silent_whatever_it_declares(hub):
    write(hub / "cron/wakeful.md", "---\non_demand: true\nsilent: false\n---\nHi.\n")
    r = next(r for r in rows(hub) if r["name"] == "wakeful")
    assert r["silent"] is True and "--silent" in r["commands"][0]
    assert r["default"] is False and r["enabled"] is False


def test_overrides_change_schedule_and_enabled(hub):
    save(hub, "memory-consolidate", {"schedule": "30 2 * * *"})
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert (r["file_schedule"], r["schedule"], r["overridden"], r["enabled"]) == (
        "0 3 * * *", "30 2 * * *", True, True,
    )
    assert r["commands"][0].startswith('cc-connect cron add --cron "30 2 * * *" --prompt')
    save(hub, "memory-consolidate", {"enabled": False})
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert (r["schedule"], r["overridden"], r["enabled"]) == ("0 3 * * *", False, False)


def test_override_changes_the_schedule_of_a_script_task(hub):
    fake_app(hub, "mail", MAIL_CRON)
    save(hub, "mail/poll", {"schedule": "0 8 * * *"})
    r = next(r for r in rows(hub) if r["name"] == "mail/poll")
    assert (r["file_schedule"], r["schedule"], r["overridden"]) == (
        "*/5 * * * *", "0 8 * * *", True,
    )
    assert r["commands"][0].startswith('cc-connect cron add --cron "0 8 * * *" --exec')


def test_enabled_true_turns_on_a_default_false_task(hub):
    write(hub / "cron/optional.md", '---\nschedule: "0 8 * * *"\ndefault: false\n---\nHi.\n')
    assert next(r for r in rows(hub) if r["name"] == "optional")["enabled"] is False
    save(hub, "optional", {"enabled": True})
    assert next(r for r in rows(hub) if r["name"] == "optional")["enabled"] is True


def test_on_demand_task_ignores_a_schedule_override(hub):
    fake_app(hub, "mail", MAIL_CRON)
    save(hub, "mail/triage", {"schedule": "0 8 * * *"})
    r = next(r for r in rows(hub) if r["name"] == "mail/triage")
    assert (r["schedule"], r["overridden"]) == (None, False)
    assert '--cron "0 0 1 1 *"' in r["commands"][0]


def test_bad_override_makes_an_error_row_not_a_command(hub):
    hub_toml = hub / "hub.toml"
    hub_toml.write_text(
        hub_toml.read_text(encoding="utf-8")
        + '\n[cron."memory-consolidate"]\nschedule = "0 3 * * *\\" --exec \\"rm -rf ~"\n',
        encoding="utf-8", newline="\n",
    )
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert r["error"] and "hub.toml" in r["error"]
    assert (r["enabled"], r["commands"]) == (False, [])


def test_override_with_a_wrong_type_makes_an_error_row(hub):
    hub_toml = hub / "hub.toml"
    hub_toml.write_text(
        hub_toml.read_text(encoding="utf-8")
        + '\n[cron."memory-consolidate"]\nenabled = "no"\n',
        encoding="utf-8", newline="\n",
    )
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert r["error"] and "enabled" in r["error"] and r["enabled"] is False


def test_bad_hub_task_is_an_error_row(hub):
    write(hub / "cron/Bad Name.md", "no frontmatter")
    write(hub / "cron/broken.md", "---\ndefault: true\n---\n")
    errs = {r["name"]: r["error"] for r in rows(hub) if r["error"]}
    assert set(errs) == {"Bad Name", "broken"} and "schedule is required" in errs["broken"]
    assert errs["broken"].startswith("cron/broken.md: ")
    bad = next(r for r in rows(hub) if r["name"] == "broken")
    assert (bad["source"], bad["file"], bad["kind"], bad["enabled"]) == (
        "hub", "cron/broken.md", None, False,
    )
    assert (bad["commands"], bad["prompt"], bad["allow"]) == ([], None, [])
    # a good task next to a bad one is still listed
    assert next(r for r in rows(hub) if r["name"] == "memory-consolidate")["error"] is None


def test_bad_app_task_is_an_error_row(hub):
    fake_app(hub, "mail", {
        "cron/ok.md": '---\nschedule: "0 8 * * *"\n---\nHi.\n',
        "cron/Odd Name.md": '---\nschedule: "0 8 * * *"\n---\n',
        "cron/broken.md": '---\nschedule: "every day"\n---\n',
    })
    by = {r["name"]: r for r in rows(hub)}
    assert by["mail/ok"]["error"] is None
    assert "task name" in by["mail/Odd Name"]["error"]
    assert by["mail/broken"]["error"].startswith("apps/mail/cron/broken.md: schedule")


def test_unreadable_task_file_is_an_error_row(hub):
    path = hub / "cron" / "latin.md"
    path.write_bytes(b'---\nschedule: "0 8 * * *"\n---\n\xe9\n')
    r = next(r for r in rows(hub) if r["name"] == "latin")
    assert "UTF-8" in r["error"]


def test_apps_without_cron_files_or_directory_add_no_rows(hub):
    fake_app(hub, "mail", {"app.toml": "x"})
    lock = hub / "apps.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8") + '[apps.ghost]\nlink = "~/gone"\n',
        encoding="utf-8", newline="\n",
    )
    assert [r["name"] for r in rows(hub)] == ["memory-consolidate"]


def test_app_name_that_is_not_a_valid_name_is_an_error_row(hub):
    write(hub / "apps.lock", '[apps."../x\\" y"]\nlink = "~/x"\n')
    errs = [r for r in rows(hub) if r["error"]]
    assert len(errs) == 1 and errs[0]["file"] == "apps.lock" and errs[0]["commands"] == []


def test_discover_returns_tasks_with_definitions(hub):
    fake_app(hub, "mail", MAIL_CRON)
    tasks = discover(hub)
    assert all(isinstance(t, Task) for t in tasks)
    by = {t.name: t for t in tasks}
    assert by["mail/poll"].definition.kind == "exec" and by["mail/poll"].error is None
    assert (by["mail/poll"].source, by["mail/poll"].file) == ("mail", "apps/mail/cron/poll.md")


def test_registration_commands_default_to_the_file_time(hub):
    task = next(t for t in discover(hub) if t.name == "memory-consolidate")
    assert registration_commands(task, None) == registration_commands(task, "0 3 * * *")


def test_task_name_rule_matches_the_app_name_rule():
    from cc_hub.apps import NAME
    from cc_hub.crontasks import TASK_NAME

    assert TASK_NAME.pattern == NAME.pattern
