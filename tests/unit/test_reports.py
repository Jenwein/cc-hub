# -*- coding: utf-8 -*-
import tomllib

import pytest

from cc_hub import cronoverrides
from cc_hub.reports import (
    LANGUAGE_RULE,
    PERIODS,
    ReportConfig,
    ReportError,
    Section,
    SectionDef,
    discover_sections,
    drop_app_sections,
    enabled_sections,
    load_config,
    note_target,
    ordered,
    parse_section,
    periods_on,
    save_language,
    save_section,
    section_keys_of,
)
from tests.conftest import fake_app, write

BASE = '[hub]\nname = "h"  # mine\n\n[memory]\nmax_lines = 200\n'
REPORT_CRON = '---\nschedule: "0 8 * * *"\ndefault: false\nsession: new_per_run\n---\nx\n'


def put(hub, text):
    write(hub / "hub.toml", text)


def get(hub):
    return (hub / "hub.toml").read_bytes().decode("utf-8")


def keys(hub, period):
    return [s.key for s in enabled_sections(hub, period)]


def test_periods_run_from_short_to_long():
    assert PERIODS == ("daily", "weekly", "monthly", "quarterly", "yearly")


def test_language_rule():
    assert all(LANGUAGE_RULE.match(t) for t in ("en", "zh-CN", "zh-Hans-CN", "yue", "pt-BR"))
    bad = ("", "??", "e", "english", "zh_CN", "zh-", "-zh")
    assert not any(LANGUAGE_RULE.match(t) for t in bad)


# --- section files ---


def test_parse_section():
    d = parse_section('---\ncommand: "uv run x.py report daily"\ntitle: Mail  # shown\n---\nbody\n',
                      where="f")
    assert d == SectionDef("uv run x.py report daily", "Mail")
    plans = parse_section("---\ntitle: Plans\n---\nList them.\n", where="f")
    assert plans == SectionDef(None, "Plans")
    assert parse_section("---\n---\n", where="f") == SectionDef(None, None)


def test_parse_section_ignores_other_keys():
    d = parse_section("---\nschedule: nope\ncolor: red\n---\n", where="f")
    assert d == SectionDef(None, None)


def test_parse_section_empty_command_is_an_error():
    for head in ("command:", 'command: ""', "command:   ", "command: # nothing"):
        with pytest.raises(ReportError, match="^f: command is empty$"):
            parse_section(f"---\n{head}\n---\n", where="f")


def test_parse_section_without_frontmatter_is_a_report_error():
    with pytest.raises(ReportError, match="^f: needs a frontmatter block"):
        parse_section("just text\n", where="f")


def test_discover_command_and_instruction_sections(hub):
    fake_app(hub, "mail", {
        "reports/daily.md": '---\ncommand: "uv run apps/mail/x.py report daily"\n---\n'})
    fake_app(hub, "plans", {"reports/daily.md": "---\ntitle: Plans\n---\nList today's items.\n",
                            "reports/hourly.md": "---\n---\n"})
    by_key = {s.key: s for s in discover_sections(hub)}
    assert by_key["mail/daily"].kind == "command"
    assert by_key["mail/daily"].command == "uv run apps/mail/x.py report daily"
    assert by_key["mail/daily"].title == "mail"
    assert by_key["plans/daily"].kind == "instruction" and by_key["plans/daily"].title == "Plans"
    assert by_key["plans/daily"].command is None
    assert "hourly is not a report period" in by_key["plans/hourly"].error
    assert by_key["plans/hourly"].kind is None and by_key["plans/hourly"].definition is None


def test_discover_sets_app_period_and_file(hub):
    fake_app(hub, "plans", {"reports/weekly.md": "---\n---\n"})
    (section,) = discover_sections(hub)
    assert (section.app, section.period, section.file) == (
        "plans", "weekly", "apps/plans/reports/weekly.md")
    assert section.error is None and section.definition == SectionDef(None, None)


def test_discover_orders_by_app_then_file_and_skips_readme(hub):
    fake_app(hub, "zed", {"reports/daily.md": "---\n---\n"})
    fake_app(hub, "alpha", {"reports/yearly.md": "---\n---\n", "reports/daily.md": "---\n---\n",
                            "reports/README.md": "How to write a section.\n"})
    fake_app(hub, "bare", {"app.toml": "x\n"})  # no reports directory
    assert [s.key for s in discover_sections(hub)] == ["alpha/daily", "alpha/yearly", "zed/daily"]


def test_discover_without_apps_is_empty(hub):
    assert discover_sections(hub) == []


def test_discover_reports_bad_files_as_errors_not_exceptions(hub):
    fake_app(hub, "a", {"reports/daily.md": "---\ncommand:\n---\n",
                        "reports/weekly.md": "no frontmatter here\n"})
    fake_app(hub, "b", {})
    (hub / "apps" / "b" / "reports").mkdir(parents=True)
    (hub / "apps" / "b" / "reports" / "daily.md").write_bytes(b"---\ntitle: \xff\xfe\n---\n")
    (hub / "apps" / "b" / "reports" / "monthly.md").mkdir()  # a directory is not a section
    by_key = {s.key: s for s in discover_sections(hub)}
    assert sorted(by_key) == ["a/daily", "a/weekly", "b/daily"]
    assert by_key["a/daily"].error == "apps/a/reports/daily.md: command is empty"
    assert "apps/a/reports/weekly.md: needs a frontmatter block" in by_key["a/weekly"].error
    assert by_key["b/daily"].error == "apps/b/reports/daily.md: is not UTF-8"
    assert all(s.definition is None and s.kind is None for s in by_key.values())


def test_discover_does_not_follow_an_unusable_app_name(hub):
    write(hub / "apps.lock", '[apps."../x"]\nlink = "~/x"\n')
    write(hub / "apps" / ".." / "x" / "reports" / "daily.md", "---\n---\n")
    sections = discover_sections(hub)
    assert len(sections) == 1 and sections[0].error and "../x" in sections[0].error
    assert enabled_sections(hub, "daily") == []


# --- hub.toml: [report] ---


def test_load_config_reads_language_order_and_off(hub):
    put(hub, BASE + '\n[report]\nlanguage = "zh-CN"\norder = ["plans"]\n\n'
             '[report."mail/daily"]\nenabled = false\n')
    cfg = load_config(hub)
    assert (cfg.language, cfg.order, cfg.off) == ("zh-CN", ["plans"], {"mail/daily"})


def test_load_config_defaults(hub):
    assert load_config(hub) == ReportConfig(None, [], set())
    put(hub, BASE + "\n[report]\n")
    assert load_config(hub) == ReportConfig(None, [], set())


def test_enabled_true_is_not_off(hub):
    put(hub, BASE + '\n[report."mail/daily"]\nenabled = true\n\n[report."mail/weekly"]\n')
    assert load_config(hub).off == set()


@pytest.mark.parametrize(
    "toml, message",
    [
        ('[report]\norder = "x"', r"hub\.toml: \[report\] order must be a list of app names"),
        ("[report]\norder = [1]", r"\[report\] order must be a list of app names"),
        ('[report]\nlanguage = "??"', r"\[report\] language"),
        ("[report]\nlanguage = 3", r"\[report\] language"),
        ("[report]\ncolour = 1", r"\[report\] colour"),
        ('[report."a/daily"]\nx = 1', r'\[report\."a/daily"\].*\bx\b'),
        ('[report."a/daily"]\nenabled = "no"', r'\[report\."a/daily"\].*enabled'),
        ('[report."a/hourly"]\nenabled = false', r"a/hourly"),
        ('[report."a"]\nenabled = false', r'\[report\."a"\]'),
        ('[report."a/daily".more]\nenabled = false', r"more"),
    ],
)
def test_bad_report_settings_are_errors(hub, toml, message):
    put(hub, BASE + "\n" + toml + "\n")
    with pytest.raises(ReportError, match=message):
        load_config(hub)


def test_report_that_is_not_a_table_is_an_error(hub):
    put(hub, "report = 1\n" + BASE)
    with pytest.raises(ReportError, match=r"\[report\] must be a table"):
        load_config(hub)


def test_invalid_toml_is_a_report_error(hub):
    put(hub, "[report\n")
    with pytest.raises(ReportError, match="hub.toml is not valid TOML"):
        load_config(hub)


def test_ordered_puts_listed_apps_first_then_the_rest_by_name():
    secs = [Section(a, "daily", f"{a}.md", None, None) for a in ("mail", "plans", "zz")]
    assert [s.app for s in ordered(secs, [])] == ["mail", "plans", "zz"]
    assert [s.app for s in ordered(secs, ["zz"])] == ["zz", "mail", "plans"]
    assert [s.app for s in ordered(secs, ["plans", "nope", "zz", "plans"])] == [
        "plans", "zz", "mail"]


def test_enabled_sections_honour_off_and_order(hub):
    for app in ("mail", "plans", "zz"):
        fake_app(hub, app, {"reports/daily.md": "---\n---\n", "reports/weekly.md": "---\n---\n"})
    fake_app(hub, "bad", {"reports/daily.md": "---\ncommand:\n---\n"})
    put(hub, BASE + '\n[report]\norder = ["zz"]\n')
    assert keys(hub, "daily") == ["zz/daily", "mail/daily", "plans/daily"]
    assert keys(hub, "weekly") == ["zz/weekly", "mail/weekly", "plans/weekly"]
    put(hub, BASE + '\n[report]\norder = ["zz"]\n\n[report."mail/daily"]\nenabled = false\n')
    assert keys(hub, "daily") == ["zz/daily", "plans/daily"]
    assert keys(hub, "weekly") == ["zz/weekly", "mail/weekly", "plans/weekly"]


def test_unknown_period_is_an_error(hub):
    with pytest.raises(ReportError, match="hourly is not a report period"):
        enabled_sections(hub, "hourly")
    with pytest.raises(ReportError, match="hourly is not a report period"):
        note_target(hub, "hourly")


# --- writing ---


def test_save_language_and_section_round_trip(hub):
    original = get(hub)
    save_language(hub, "zh-CN")
    assert load_config(hub).language == "zh-CN"
    assert get(hub).startswith(original)
    with_language = get(hub)

    save_section(hub, "mail/daily", False)
    assert load_config(hub).off == {"mail/daily"}
    assert tomllib.loads(get(hub))["report"]["mail/daily"] == {"enabled": False}
    assert get(hub).startswith(with_language)
    save_section(hub, "mail/weekly", False)
    assert load_config(hub).off == {"mail/daily", "mail/weekly"}

    save_section(hub, "mail/daily", True)
    save_section(hub, "mail/weekly", True)
    assert load_config(hub) == ReportConfig("zh-CN", [], set())
    assert 'mail/' not in get(hub)
    assert get(hub).startswith(original)


def test_save_section_on_when_nothing_is_set_changes_nothing(hub):
    before = get(hub)
    save_section(hub, "mail/daily", True)
    assert get(hub) == before


def test_save_language_keeps_order_other_keys_and_sections(hub):
    text = (BASE + '\n[report]\norder = ["plans", "mail"]\nlanguage = "en"\n\n'
            '# mute mail\n[report."mail/daily"]\nenabled = false\n\n[cron."a"]\nenabled = true\n')
    put(hub, text)
    save_language(hub, "zh-CN")
    cfg = load_config(hub)
    assert (cfg.language, cfg.order, cfg.off) == ("zh-CN", ["plans", "mail"], {"mail/daily"})
    out = get(hub)
    assert out == text.replace('language = "en"', 'language = "zh-CN"')
    assert tomllib.loads(out)["cron"] == {"a": {"enabled": True}}


def test_save_language_leaves_comments_and_the_order_line_alone(hub):
    text = (BASE + '\n[report]\n# my order, do not touch\norder = ["plans","mail"]  # favourite\n\n'
            '# mute mail\n[report."mail/daily"]\nenabled = false\n')
    put(hub, text)
    save_language(hub, "zh-CN")
    inserted = text.replace("favourite\n", 'favourite\nlanguage = "zh-CN"\n')
    assert get(hub) == inserted
    save_language(hub, "en")  # a changed value keeps the line, a later comment on it included
    assert get(hub) == inserted.replace("zh-CN", "en")
    put(hub, text.replace("favourite\n", 'favourite\nlanguage = "ja"  # my words\n'))
    save_language(hub, "zh-CN")
    assert get(hub) == text.replace("favourite\n", 'favourite\nlanguage = "zh-CN"  # my words\n')


def test_save_language_on_a_report_table_with_no_keys_or_no_table(hub):
    put(hub, BASE + "\n[report]\n# only a comment\n")
    save_language(hub, "en")
    assert get(hub) == BASE + '\n[report]\nlanguage = "en"\n# only a comment\n'
    put(hub, BASE)
    save_language(hub, "en")
    assert get(hub) == BASE + '\n[report]\nlanguage = "en"\n'


def test_save_section_keeps_language_and_order(hub):
    put(hub, BASE + '\n[report]\nlanguage = "en"\norder = ["plans"]\n')
    save_section(hub, "plans/daily", False)
    save_section(hub, "plans/daily", True)
    assert load_config(hub) == ReportConfig("en", ["plans"], set())


def test_save_rejects_bad_names(hub):
    before = get(hub)
    for tag in ("", "??", "english", "zh_CN"):
        with pytest.raises(ReportError, match="language"):
            save_language(hub, tag)
    for key in ("mail", "mail/hourly", "/daily", "mail/", 'ma"il/daily', "a/b/daily"):
        with pytest.raises(ReportError, match="<app>/<period>|not a report"):
            save_section(hub, key, False)
    assert get(hub) == before


def test_report_tables_edit_in_place_with_crlf(hub):
    raw = (BASE + "# mine\n\n[report]\norder = [\"plans\"]\n").replace("\n", "\r\n")
    (hub / "hub.toml").write_bytes(raw.encode())
    save_language(hub, "zh-CN")
    out = (hub / "hub.toml").read_bytes().decode()
    assert "# mine\r\n" in out and "\n" not in out.replace("\r\n", "")
    assert load_config(hub).order == ["plans"] and load_config(hub).language == "zh-CN"
    save_section(hub, "plans/daily", False)
    out = (hub / "hub.toml").read_bytes().decode()
    assert "\n" not in out.replace("\r\n", "") and load_config(hub).off == {"plans/daily"}


def test_a_dotted_own_key_survives_save_language_and_blocks_save_section(hub):
    text = BASE + '\n[report]\n"mail/daily".enabled = false\n'
    put(hub, text)
    save_language(hub, "en")
    assert get(hub) == text + 'language = "en"\n'
    assert load_config(hub).off == {"mail/daily"}
    with pytest.raises(ReportError, match="hub.toml"):
        save_section(hub, "mail/daily", True)
    assert get(hub) == text + 'language = "en"\n'


def test_invalid_toml_is_not_written_over(hub):
    put(hub, "[report\n")
    with pytest.raises(ReportError, match="hub.toml"):
        save_language(hub, "en")
    with pytest.raises(ReportError, match="hub.toml"):
        save_section(hub, "mail/daily", False)
    assert get(hub) == "[report\n"


def test_section_with_child_tables_is_not_removed(hub):
    text = BASE + '\n[report."mail/daily"]\nenabled = false\n\n[report."mail/daily".more]\nx = 1\n'
    put(hub, text)
    with pytest.raises(ReportError, match="child tables"):
        save_section(hub, "mail/daily", True)
    assert get(hub) == text


def test_section_keys_of(hub):
    off = '[report."{}"]\nenabled = false\n'
    put(hub, BASE + '\n[report]\nlanguage = "en"\n\n'
             + "\n".join(off.format(k) for k in ("mail/daily", "mail/weekly", "mailer/daily")))
    assert section_keys_of(hub, "mail") == ["mail/daily", "mail/weekly"]
    assert section_keys_of(hub, "plans") == []
    put(hub, BASE)
    assert section_keys_of(hub, "mail") == []


def test_drop_app_sections_removes_every_table_of_the_app_and_nothing_else(hub):
    text = (BASE + '\n[report]\nlanguage = "en"\n\n[report."mail/daily"]\nenabled = false\n\n'
            '[report."mail/weekly"]\nenabled = false\n\n[report."mailer/daily"]\n'
            'enabled = false\n\n[cron."a"]\nenabled = true\n')
    put(hub, text)
    assert drop_app_sections(hub, "mail") is True
    assert get(hub) == (BASE + '\n[report]\nlanguage = "en"\n\n[report."mailer/daily"]\n'
                        'enabled = false\n\n[cron."a"]\nenabled = true\n')
    assert load_config(hub) == ReportConfig("en", [], {"mailer/daily"})


def test_drop_app_sections_changes_nothing_when_the_app_has_none(hub):
    text = BASE + '\n[report."mailer/daily"]\nenabled = false\n# mine\n'
    put(hub, text)
    assert drop_app_sections(hub, "mail") is False
    assert get(hub) == text
    put(hub, BASE)
    assert drop_app_sections(hub, "mail") is False
    assert get(hub) == BASE


def test_drop_app_sections_keeps_crlf_endings(hub):
    raw = BASE + '\n[report."mail/daily"]\nenabled = false\n\n[cron."a"]\nenabled = true\n'
    (hub / "hub.toml").write_bytes(raw.replace("\n", "\r\n").encode())
    assert drop_app_sections(hub, "mail") is True
    out = (hub / "hub.toml").read_bytes().decode()
    assert "mail" not in out and "\r\n" in out and "\n" not in out.replace("\r\n", "")


@pytest.mark.parametrize("bad", ["mail/daily", "mail/weekly"])
def test_drop_app_sections_is_all_or_nothing(hub, bad):
    tables = [f'[report."{key}"]\nenabled = false\n' for key in ("mail/daily", "mail/weekly")]
    tables = [t + f'\n[report."{bad}".more]\nx = 1\n' if f'"{bad}"' in t else t for t in tables]
    text = BASE + "\n" + "\n".join(tables)
    put(hub, text)
    with pytest.raises(ReportError, match=rf'^hub\.toml: \[report\."{bad}"\] has child tables'):
        drop_app_sections(hub, "mail")
    assert get(hub) == text  # the clean table next to it is still there, too


def test_drop_app_sections_refuses_a_table_it_cannot_edit_in_place(hub):
    text = (BASE + '\n[report]\n"mail/daily".enabled = false\n\n'
            '[report."mail/weekly"]\nenabled = false\n')
    put(hub, text)
    with pytest.raises(
        ReportError, match=r'^hub\.toml: cannot edit \[report\."mail/daily"\] in place'
    ):
        drop_app_sections(hub, "mail")
    assert get(hub) == text


def test_drop_app_sections_does_not_write_over_invalid_toml(hub):
    put(hub, "[report\n")
    with pytest.raises(ReportError, match="hub.toml"):
        drop_app_sections(hub, "mail")
    assert get(hub) == "[report\n"


# --- reports and the cron tasks behind them ---


def test_periods_on_and_note_target(hub):
    for p in ("daily", "weekly"):  # the real files arrive in Task 7
        write(hub / f"cron/report-{p}.md", REPORT_CRON)
    assert note_target(hub, "daily") is None
    cronoverrides.save(hub, "report-weekly", {"enabled": True})
    assert periods_on(hub)["weekly"] and not periods_on(hub)["daily"]
    assert note_target(hub, "daily") == "weekly" and note_target(hub, "monthly") is None
    assert note_target(hub, "weekly") == "weekly"


def test_periods_on_lists_every_period(hub):
    assert periods_on(hub) == dict.fromkeys(PERIODS, False)


def test_a_report_task_with_an_error_is_not_on(hub):
    write(hub / "cron/report-daily.md", '---\nschedule: "nonsense"\ndefault: true\n---\nx\n')
    write(hub / "cron/report-weekly.md", REPORT_CRON.replace("default: false", "default: true"))
    assert periods_on(hub)["daily"] is False and periods_on(hub)["weekly"] is True
    assert note_target(hub, "daily") == "weekly"


def test_an_app_task_named_like_a_report_task_is_not_one(hub):
    fake_app(hub, "report-daily", {"cron/x.md": REPORT_CRON.replace("false", "true")})
    assert periods_on(hub)["daily"] is False


def test_periods_on_wraps_cron_errors(hub):
    put(hub, "[cron\n")
    with pytest.raises(ReportError, match="hub.toml"):
        periods_on(hub)
