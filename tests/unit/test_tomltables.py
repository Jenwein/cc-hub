# -*- coding: utf-8 -*-
import tomllib

import pytest

from cc_hub.tomltables import TableEditError, edit_table, header_path, set_key

BASE = '[hub]\nname = "h"  # mine\n\n[memory]\nmax_lines = 200\n'


def test_header_path_parses_quoted_and_bare_parts():
    assert header_path('[report."ledger/monthly"]  # off') == ("report", "ledger/monthly")
    assert header_path("[ cron . memory-consolidate ]") == ("cron", "memory-consolidate")
    assert header_path("[report]") == ("report",)
    assert header_path("[[requires]]") is None and header_path("x = 1") is None


def test_parent_table_keeps_its_child_tables():
    text = BASE + '\n[report."ledger/monthly"]\nenabled = false\n'
    out = edit_table(text, ("report",), {"language": "zh-CN"})
    data = tomllib.loads(out)
    assert data["report"] == {"language": "zh-CN", "ledger/monthly": {"enabled": False}}
    assert out.startswith(text)


def test_replacing_parent_keys_keeps_order_list():
    text = BASE + '\n[report]\nlanguage = "en"\norder = ["mail", "plans"]\n'
    out = edit_table(text, ("report",), {"language": "zh-CN", "order": ["mail", "plans"]})
    assert tomllib.loads(out)["report"] == {"language": "zh-CN", "order": ["mail", "plans"]}


def test_remove_leaf_table_and_refuse_parent_with_children():
    text = BASE + '\n[report]\nlanguage = "en"\n\n[report."a/daily"]\nenabled = false\n'
    assert '[report."a/daily"]' not in edit_table(text, ("report", "a/daily"), None)
    with pytest.raises(TableEditError):
        edit_table(text, ("report",), None)


def test_crlf_and_comments_survive():
    text = (BASE + "# keep me\n").replace("\n", "\r\n")
    out = edit_table(text, ("report", "a/daily"), {"enabled": False})
    assert "\r\n# keep me\r\n" in out and "\n" not in out.replace("\r\n", "")


def test_invalid_toml_is_refused():
    with pytest.raises(TableEditError, match="not valid TOML"):
        edit_table("[hub\n", ("report",), {"language": "en"})


def test_missing_tables_are_appended_with_quoted_names():
    assert edit_table(BASE, ("report",), {"language": "en"}) == (
        BASE + '\n[report]\nlanguage = "en"\n'
    )
    assert edit_table(BASE, ("report", "a/daily"), {"enabled": False}) == (
        BASE + '\n[report."a/daily"]\nenabled = false\n'
    )


def test_removing_the_only_child_leaves_the_file_as_it_was():
    text = BASE + '\n[report."a/daily"]\nenabled = false\n'
    assert edit_table(text, ("report", "a/daily"), None) == BASE


def test_a_table_that_is_not_there_is_not_removed():
    assert edit_table(BASE, ("report", "a/daily"), None) == BASE


@pytest.mark.parametrize("path", [(), ("report", ""), ("report", 'a"b'), ("report", "a\nb")])
def test_unusable_paths_are_refused(path):
    with pytest.raises(TableEditError, match="not a usable table path"):
        edit_table(BASE, path, {"enabled": False})


@pytest.mark.parametrize(
    "text",
    ["report = 1\n", "[report]\nlanguage = \"en\"\n\n[report.'x']\na = 1\n"],
)
def test_tables_that_cannot_be_rewritten_by_text_are_refused(text):
    # a literal-string child header is not one the editor reads, so the child would be lost
    with pytest.raises(TableEditError, match="cannot edit in place"):
        edit_table(text, ("report",), {"language": "en"})


PARENT_THEN_CHILD = BASE + '\n[report]\nlanguage = "en"\n\n[report."a/daily"]\nenabled = false\n'
CHILD_THEN_PARENT = BASE + '\n[report."a/daily"]\nenabled = false\n\n[report]\nlanguage = "en"\n'


@pytest.mark.parametrize("text", [PARENT_THEN_CHILD, CHILD_THEN_PARENT])
def test_replacing_a_parent_in_place_keeps_a_child_table_wherever_it_is(text):
    out = edit_table(text, ("report",), {"language": "zh-CN"})
    assert out == text.replace('"en"', '"zh-CN"')
    assert tomllib.loads(out)["report"]["a/daily"] == {"enabled": False}


def test_an_array_of_tables_under_the_parent_is_a_child_too():
    text = (
        BASE + '\n[report]\nlanguage = "en"\n\n[[report.items]]\nn = 1\n\n[[report.items]]\nn = 2\n'
    )
    out = edit_table(text, ("report",), {"language": "zh-CN"})
    assert out == text.replace('"en"', '"zh-CN"')
    with pytest.raises(TableEditError, match="child tables"):
        edit_table(text, ("report",), None)


def test_an_inline_table_or_dotted_key_is_an_own_key_not_a_child():
    text = BASE + '\n[report]\nlanguage = "en"\nlook = {size = 1}\nfont.name = "x"\n'
    assert edit_table(text, ("report",), {"language": "zh-CN"}) == (
        BASE + '\n[report]\nlanguage = "zh-CN"\n'
    )
    assert edit_table(text, ("report",), None) == BASE


@pytest.mark.parametrize("text", [PARENT_THEN_CHILD, CHILD_THEN_PARENT])
def test_children_can_be_refused_instead_of_kept(text):
    with pytest.raises(TableEditError, match="child tables"):
        edit_table(text, ("report",), {"language": "zh-CN"}, allow_children=False)
    with pytest.raises(TableEditError, match="child tables"):
        edit_table(text, ("report",), None, allow_children=False)
    # the child itself has none
    out = edit_table(text, ("report", "a/daily"), {"enabled": True}, allow_children=False)
    assert "enabled = true" in out


# --- set_key: one own key of one table, everything else byte for byte ---

REPORT = (
    BASE
    + '\n[report]\n# my order, do not touch\norder = ["plans", "mail"]  # favourite\n'
    + '  language = "en"   # my words\n\n# next\n[report."a/daily"]\nenabled = false\n'
)


def test_set_key_replaces_only_the_value():
    out = set_key(REPORT, ("report",), "language", "zh-CN")
    assert out == REPORT.replace('language = "en"', 'language = "zh-CN"')
    assert tomllib.loads(out)["report"]["language"] == "zh-CN"


@pytest.mark.parametrize(
    "line, replaced",
    [
        ('language = "a # b"  # c', 'language = "zh-CN"  # c'),
        ("language = 'single'\t# c", 'language = "zh-CN"\t# c'),
        ('"language" = "en"', '"language" = "zh-CN"'),
        ("language   =   3", 'language   =   "zh-CN"'),
        ('language = ["x", "y # z"]  # list', 'language = "zh-CN"  # list'),
        ("language = {a = 1}", 'language = "zh-CN"'),
        ("\tlanguage = true  ", '\tlanguage = "zh-CN"  '),
    ],
)
def test_set_key_replaces_values_of_any_one_line_form(line, replaced):
    out = set_key(f"[report]\n{line}\n", ("report",), "language", "zh-CN")
    assert out == f"[report]\n{replaced}\n"
    assert tomllib.loads(out)["report"]["language"] == "zh-CN"


def test_set_key_writes_ints_and_bools_as_toml():
    text = '[cron."a"]\nenabled = false  # off\n'
    assert set_key(text, ("cron", "a"), "enabled", True) == '[cron."a"]\nenabled = true  # off\n'
    assert set_key(text, ("cron", "a"), "count", 3) == (
        '[cron."a"]\nenabled = false  # off\ncount = 3\n'
    )


def test_set_key_inserts_after_the_last_own_key():
    text = '[report]\norder = ["a"]\nmore = 1\n\n# next\n[report."x/daily"]\nenabled = false\n'
    assert set_key(text, ("report",), "language", "en") == (
        '[report]\norder = ["a"]\nmore = 1\nlanguage = "en"\n\n# next\n[report."x/daily"]\n'
        "enabled = false\n"
    )


def test_set_key_inserts_after_a_multi_line_last_key():
    text = '[report]\norder = [\n  "a",\n  "b",\n]\n\n[memory]\nmax_lines = 1\n'
    out = set_key(text, ("report",), "language", "en")
    assert out == (
        '[report]\norder = [\n  "a",\n  "b",\n]\nlanguage = "en"\n\n[memory]\nmax_lines = 1\n'
    )


def test_set_key_inserts_right_after_the_header_of_an_empty_table():
    text = '[report]\n\n# next\n[report."x/daily"]\nenabled = false\n'
    assert set_key(text, ("report",), "language", "en") == (
        '[report]\nlanguage = "en"\n\n# next\n[report."x/daily"]\nenabled = false\n'
    )
    assert set_key("[report]\n", ("report",), "language", "en") == '[report]\nlanguage = "en"\n'


def test_set_key_inserts_in_a_last_table_without_a_final_newline():
    assert set_key('[report]\norder = ["a"]', ("report",), "language", "en") == (
        '[report]\norder = ["a"]\nlanguage = "en"\n'
    )
    assert set_key("[report]", ("report",), "language", "en") == '[report]\nlanguage = "en"\n'


def test_set_key_does_not_take_a_comment_or_a_child_table_for_the_key():
    text = '[report]\n# language = "x"\n\n[report.look]\nlanguage = "child"\n'
    out = set_key(text, ("report",), "language", "en")
    assert out == (
        '[report]\nlanguage = "en"\n# language = "x"\n\n[report.look]\nlanguage = "child"\n'
    )
    assert tomllib.loads(out)["report"] == {"language": "en", "look": {"language": "child"}}


def test_set_key_touches_only_the_named_table():
    text = "[a]\nk = 1\n\n[b]\nk = 2\n"
    assert set_key(text, ("b",), "k", 3) == "[a]\nk = 1\n\n[b]\nk = 3\n"


def test_set_key_keeps_dotted_and_inline_own_keys():
    text = '[report]\n"mail/daily".enabled = false\nlook = {size = 1}\n'
    out = set_key(text, ("report",), "language", "en")
    assert out == text + 'language = "en"\n'


def test_set_key_appends_a_missing_table():
    assert set_key(BASE, ("report",), "language", "en") == BASE + '\n[report]\nlanguage = "en"\n'
    assert set_key(BASE, ("report", "a/daily"), "enabled", False) == (
        BASE + '\n[report."a/daily"]\nenabled = false\n'
    )
    assert set_key("", ("report",), "language", "en") == '[report]\nlanguage = "en"\n'
    no_final_newline = BASE[:-1]
    assert set_key(no_final_newline, ("report",), "language", "en") == (
        BASE + '\n[report]\nlanguage = "en"\n'
    )


def test_set_key_keeps_crlf():
    crlf = REPORT.replace("\n", "\r\n")
    out = set_key(crlf, ("report",), "language", "zh-CN")
    assert out == crlf.replace('language = "en"', 'language = "zh-CN"')
    without = crlf.replace('  language = "en"   # my words\r\n', "")
    inserted = set_key(without, ("report",), "language", "x")
    assert 'language = "x"\r\n\r\n# next' in inserted
    appended = set_key(BASE.replace("\n", "\r\n"), ("report",), "language", "en")
    assert appended.endswith('\r\n\r\n[report]\r\nlanguage = "en"\r\n')
    for result in (out, inserted, appended):
        assert "\n" not in result.replace("\r\n", "")


@pytest.mark.parametrize(
    "text",
    [
        '[report]\nlanguage = """\nen\n"""\n',
        "[report]\nlanguage = '''\nen\n'''\n",
        '[report]\nlanguage = [\n  "en",\n]\n',
        '[report]\nlanguage = ["en", # first\n  "fr"]\n',
    ],
)
def test_set_key_refuses_a_value_that_is_not_one_line(text):
    with pytest.raises(TableEditError, match="cannot edit in place"):
        set_key(text, ("report",), "language", "zh-CN")


@pytest.mark.parametrize("text", ["report = 1\n", "report.language = 'x'\n"])
def test_set_key_refuses_what_it_cannot_leave_as_intended(text):
    with pytest.raises(TableEditError, match="cannot edit in place"):
        set_key(text, ("report",), "language", "en")


def test_set_key_refuses_invalid_toml_and_unusable_arguments():
    with pytest.raises(TableEditError, match="not valid TOML"):
        set_key("[hub\n", ("report",), "language", "en")
    with pytest.raises(TableEditError, match="not a usable table path"):
        set_key(BASE, (), "language", "en")
    with pytest.raises(TableEditError, match="not a usable key"):
        set_key(BASE, ("report",), 'a"b', "en")
    with pytest.raises(TableEditError, match="not a usable key"):
        set_key(BASE, ("report",), "", "en")
    with pytest.raises(TableEditError, match="not a usable value"):
        set_key(BASE, ("report",), "language", ["en"])
