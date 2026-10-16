# -*- coding: utf-8 -*-
import tomllib

import pytest

from cc_hub.tomltables import TableEditError, edit_table, header_path

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
    "text", ["report = 1\n", '[report]\nx = {a = 1}\n', "[report]\nsub.k = 1\n"]
)
def test_tables_that_cannot_be_rewritten_by_text_are_refused(text):
    with pytest.raises(TableEditError, match="cannot edit in place"):
        edit_table(text, ("report",), {"language": "en"})
