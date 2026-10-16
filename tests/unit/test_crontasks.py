# -*- coding: utf-8 -*-
import pytest

from cc_hub.cronoverrides import save
from cc_hub.crontasks import (
    CronError,
    Task,
    TaskDef,
    check_schedule,
    discover,
    parse_task,
    pointer_prompt,
    registration_command,
    rows,
)
from tests.conftest import PLANS_CRON, fake_app, write

REPORT_TASKS = (
    "report-daily", "report-monthly", "report-quarterly", "report-weekly", "report-yearly",
)


def test_task():
    d = parse_task(
        '---\nschedule: "0 3 * * *"  # nightly\ndefault: true\nsession: new_per_run\n---\nDo it.\n',
        where="x",
    )
    assert d == TaskDef("0 3 * * *", True, "new_per_run")


def test_task_defaults():
    d = parse_task('---\nschedule: "0 3 * * *"\n---\nDo it.\n', where="x")
    assert d == TaskDef("0 3 * * *", False, "reuse")


def test_unquoted_schedule_ends_at_a_comment():
    d = parse_task("---\nschedule: 0 3 * * *  # nightly\n---\n", where="x")
    assert d.schedule == "0 3 * * *"


def test_schedule_is_single_spaced():
    d = parse_task('---\nschedule: "0  3 * *  *"\n---\n', where="x")
    assert d.schedule == "0 3 * * *"


def test_comments_and_blank_lines_in_the_frontmatter():
    d = parse_task(
        '---\n# when\nschedule: "0 3 * * *"\n\n  # a note\ndefault: true\n---\n', where="x"
    )
    assert d == TaskDef("0 3 * * *", True, "reuse")


def test_unknown_keys_are_ignored():
    d = parse_task('---\nschedule: "0 3 * * *"\nowner: me\n---\n', where="x")
    assert d == TaskDef("0 3 * * *", False, "reuse")


def test_crlf_file_parses():
    d = parse_task('---\r\nschedule: "0 3 * * *"\r\n---\r\nx\r\n', where="x")
    assert d.schedule == "0 3 * * *"


def test_no_frontmatter():
    with pytest.raises(CronError, match="^apps/a/cron/t.md: .*frontmatter"):
        parse_task("no frontmatter", where="apps/a/cron/t.md")


@pytest.mark.parametrize("head, words", [
    ('default: true', "schedule is required"),
    ('schedule: ""', "schedule is required"),
    ('schedule: "* * * * *"\nsession: sometimes', "session"),
    ('schedule: "* * * * *"\ndefault: yes', "default"),
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


def test_rows_register_a_pointer_prompt(hub):
    fake_app(hub, "plans", PLANS_CRON)
    by = {r["name"]: r for r in rows(hub)}
    mc = by["memory-consolidate"]
    assert mc["prompt"] == (
        "Scheduled task hub:memory-consolidate: follow the body of cron/memory-consolidate.md "
        "in the hub."
    )
    assert mc["command"] == (
        'cc-connect cron add --cron "0 3 * * *" --prompt "' + mc["prompt"]
        + '" --session-mode new_per_run --desc "hub:memory-consolidate" --silent'
    )
    review = by["plans/review"]
    assert review["prompt"] == (
        "Scheduled task hub:plans/review: follow the body of apps/plans/cron/review.md in the hub."
    )
    assert review["command"] == (
        'cc-connect cron add --cron "0 18 * * 5" --prompt "' + review["prompt"]
        + '" --session-mode reuse --desc "hub:plans/review" --silent'
    )


def test_row_fields(hub):
    fake_app(hub, "plans", PLANS_CRON)
    by = {r["name"]: r for r in rows(hub)}
    keys = {
        "name", "source", "file", "default", "file_schedule", "schedule", "overridden",
        "enabled", "session", "desc", "prompt", "command", "error",
    }
    assert all(set(r) == keys for r in by.values())

    mc = by["memory-consolidate"]
    assert (mc["source"], mc["file"], mc["desc"]) == (
        "hub", "cron/memory-consolidate.md", "hub:memory-consolidate",
    )
    assert (mc["default"], mc["enabled"], mc["overridden"], mc["session"], mc["error"]) == (
        True, True, False, "new_per_run", None,
    )

    morning = by["plans/morning"]
    assert (morning["source"], morning["file"]) == ("plans", "apps/plans/cron/morning.md")
    assert (morning["file_schedule"], morning["schedule"]) == ("0 8 * * *", "0 8 * * *")

    review = by["plans/review"]
    assert (review["default"], review["enabled"], review["session"]) == (False, False, "reuse")
    assert review["command"] is not None  # what turning it on would register


def test_rows_are_sorted_by_name(hub):
    fake_app(hub, "plans", PLANS_CRON)
    names = [r["name"] for r in rows(hub)]
    assert names == sorted(names) == [
        "memory-consolidate", "plans/morning", "plans/review", *REPORT_TASKS,
    ]


def test_readme_is_not_a_task(hub):
    assert (hub / "cron" / "README.md").is_file()
    assert "README" not in {r["name"] for r in rows(hub)}


def test_overrides_change_schedule_and_enabled(hub):
    save(hub, "memory-consolidate", {"schedule": "30 2 * * *"})
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert (r["file_schedule"], r["schedule"], r["overridden"], r["enabled"]) == (
        "0 3 * * *", "30 2 * * *", True, True,
    )
    assert r["command"].startswith('cc-connect cron add --cron "30 2 * * *" --prompt')
    save(hub, "memory-consolidate", {"enabled": False})
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert (r["schedule"], r["overridden"], r["enabled"]) == ("0 3 * * *", False, False)


def test_override_changes_the_schedule_of_an_app_task(hub):
    fake_app(hub, "plans", PLANS_CRON)
    save(hub, "plans/morning", {"schedule": "0 7 * * *"})
    r = next(r for r in rows(hub) if r["name"] == "plans/morning")
    assert (r["file_schedule"], r["schedule"], r["overridden"]) == (
        "0 8 * * *", "0 7 * * *", True,
    )
    assert r["command"].startswith('cc-connect cron add --cron "0 7 * * *" --prompt')


def test_enabled_true_turns_on_a_default_false_task(hub):
    write(hub / "cron/optional.md", '---\nschedule: "0 8 * * *"\ndefault: false\n---\nHi.\n')
    assert next(r for r in rows(hub) if r["name"] == "optional")["enabled"] is False
    save(hub, "optional", {"enabled": True})
    assert next(r for r in rows(hub) if r["name"] == "optional")["enabled"] is True


def test_bad_override_makes_an_error_row_not_a_command(hub):
    hub_toml = hub / "hub.toml"
    hub_toml.write_text(
        hub_toml.read_text(encoding="utf-8")
        + '\n[cron."memory-consolidate"]\nschedule = "0 3 * * *\\" --prompt \\"rm -rf ~"\n',
        encoding="utf-8", newline="\n",
    )
    r = next(r for r in rows(hub) if r["name"] == "memory-consolidate")
    assert r["error"] and "hub.toml" in r["error"]
    assert (r["enabled"], r["command"]) == (False, None)


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
    assert (bad["source"], bad["file"], bad["file_schedule"], bad["enabled"]) == (
        "hub", "cron/broken.md", None, False,
    )
    assert (bad["command"], bad["prompt"]) == (None, None)
    # a good task next to a bad one is still listed
    assert next(r for r in rows(hub) if r["name"] == "memory-consolidate")["error"] is None


def test_bad_app_task_is_an_error_row(hub):
    fake_app(hub, "plans", {
        "cron/ok.md": '---\nschedule: "0 8 * * *"\n---\nHi.\n',
        "cron/Odd Name.md": '---\nschedule: "0 8 * * *"\n---\n',
        "cron/broken.md": '---\nschedule: "every day"\n---\n',
    })
    by = {r["name"]: r for r in rows(hub)}
    assert by["plans/ok"]["error"] is None
    assert "task name" in by["plans/Odd Name"]["error"]
    assert by["plans/broken"]["error"].startswith("apps/plans/cron/broken.md: schedule")


def test_unreadable_task_file_is_an_error_row(hub):
    path = hub / "cron" / "latin.md"
    path.write_bytes(b'---\nschedule: "0 8 * * *"\n---\n\xe9\n')
    r = next(r for r in rows(hub) if r["name"] == "latin")
    assert "UTF-8" in r["error"]


def test_apps_without_cron_files_or_directory_add_no_rows(hub):
    fake_app(hub, "plans", {"app.toml": "x"})
    lock = hub / "apps.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8") + '[apps.ghost]\nlink = "~/gone"\n',
        encoding="utf-8", newline="\n",
    )
    assert [r["name"] for r in rows(hub)] == ["memory-consolidate", *REPORT_TASKS]


def test_app_name_that_is_not_a_valid_name_is_an_error_row(hub):
    write(hub / "apps.lock", '[apps."../x\\" y"]\nlink = "~/x"\n')
    errs = [r for r in rows(hub) if r["error"]]
    assert len(errs) == 1 and errs[0]["file"] == "apps.lock" and errs[0]["command"] is None


def test_discover_returns_tasks_with_definitions(hub):
    fake_app(hub, "plans", PLANS_CRON)
    tasks = discover(hub)
    assert all(isinstance(t, Task) for t in tasks)
    by = {t.name: t for t in tasks}
    morning = by["plans/morning"]
    assert morning.definition == TaskDef("0 8 * * *", True, "new_per_run")
    assert (morning.source, morning.file, morning.error) == (
        "plans", "apps/plans/cron/morning.md", None,
    )


def test_registration_command_defaults_to_the_file_time(hub):
    task = next(t for t in discover(hub) if t.name == "memory-consolidate")
    assert registration_command(task, None) == registration_command(task, "0 3 * * *")


def test_registration_command_of_a_broken_task_is_none(hub):
    write(hub / "cron/broken.md", "---\ndefault: true\n---\n")
    task = next(t for t in discover(hub) if t.name == "broken")
    assert registration_command(task, None) is None


def test_task_name_rule_matches_the_app_name_rule():
    from cc_hub.apps import NAME
    from cc_hub.crontasks import TASK_NAME

    assert TASK_NAME.pattern == NAME.pattern
