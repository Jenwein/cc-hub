# -*- coding: utf-8 -*-
import tomllib
from pathlib import Path

import pytest

from cc_hub.cronoverrides import apply, load, save
from cc_hub.crontasks import CronError

BASE = '[hub]\nname = "h"  # mine\n\n[memory]\nmax_lines = 200\n'


def test_add_section_keeps_the_rest():
    out = apply(BASE, "plans/morning", {"schedule": "0 7 * * *"})
    assert out.startswith(BASE)
    assert '[cron."plans/morning"]\nschedule = "0 7 * * *"\n' in out
    assert tomllib.loads(out)["cron"]["plans/morning"] == {"schedule": "0 7 * * *"}


def test_replace_and_remove_touch_only_that_section():
    one = apply(BASE, "a", {"schedule": "0 1 * * *"})
    two = apply(one, "ledger/prices", {"enabled": False})
    three = apply(two, "a", {"schedule": "0 2 * * *", "enabled": True})
    assert tomllib.loads(three)["cron"] == {
        "a": {"schedule": "0 2 * * *", "enabled": True},
        "ledger/prices": {"enabled": False},
    }
    without_a = apply(three, "a", None)
    assert without_a.startswith(BASE) and '[cron."a"]' not in without_a
    assert tomllib.loads(apply(without_a, "ledger/prices", None)).get("cron", {}) == {}


def test_bare_key_header_is_recognised():
    text = BASE + '\n[cron.memory-consolidate]\nschedule = "30 2 * * *"\n'
    assert "30 2" not in apply(text, "memory-consolidate", {"schedule": "0 4 * * *"})


def test_crlf_file_is_edited_in_place():
    out = apply(BASE.replace("\n", "\r\n"), "a", {"schedule": "0 1 * * *"})
    assert tomllib.loads(out)["cron"]["a"]["schedule"] == "0 1 * * *"
    assert out.startswith(BASE.replace("\n", "\r\n"))
    assert "\n" not in out.replace("\r\n", "")


def test_hand_written_dotted_cron_table_is_refused():
    text = BASE + '\n[cron]\n"a".schedule = "0 1 * * *"\n'
    with pytest.raises(CronError, match="by hand"):
        apply(text, "a", {"schedule": "0 2 * * *"})


def test_removing_a_dotted_override_is_refused_rather_than_ignored():
    text = BASE + '\n[cron]\n"a".schedule = "0 1 * * *"\n'
    with pytest.raises(CronError, match="by hand"):
        apply(text, "a", None)


def test_literal_string_header_is_refused():
    text = BASE + "\n[cron.'a']\nenabled = false\n"
    with pytest.raises(CronError, match="by hand"):
        apply(text, "a", {"enabled": True})


def test_replace_keeps_the_header_comment_and_the_next_table():
    text = (
        BASE + '\n[cron."a"]  # off for now\nenabled = false\n\n[tail]\nx = 1\n'
    )
    out = apply(text, "a", {"enabled": True})
    assert '[cron."a"]  # off for now\nenabled = true\n\n[tail]\nx = 1\n' in out
    assert out.startswith(BASE)
    assert tomllib.loads(out)["tail"] == {"x": 1}


def test_remove_from_the_middle_leaves_neighbours_untouched():
    text = (
        BASE + '\n[cron."a"]\nschedule = "0 1 * * *"\n\n[tail]\nx = 1\n'
    )
    assert apply(text, "a", None) == BASE + "\n[tail]\nx = 1\n"


NOTE_BEFORE_TAIL = (
    BASE + '\n[cron."a"]\nenabled = false\n\n# tuned for a small model\n[tail]\nx = 1\n'
)


def test_replace_keeps_a_comment_that_follows_the_table():
    out = apply(NOTE_BEFORE_TAIL, "a", {"enabled": True})
    assert out == NOTE_BEFORE_TAIL.replace("enabled = false", "enabled = true")


def test_remove_keeps_a_comment_that_follows_the_table():
    out = apply(NOTE_BEFORE_TAIL, "a", None)
    assert out == BASE + "\n# tuned for a small model\n[tail]\nx = 1\n"


@pytest.mark.parametrize("gap", ["", "\n"])
def test_a_comment_at_the_end_of_the_file_is_kept(gap):
    text = BASE + f'\n[cron."a"]\nenabled = false\n{gap}# end of file note\n'
    replaced = apply(text, "a", {"enabled": True})
    assert replaced == text.replace("enabled = false", "enabled = true")
    removed = apply(text, "a", None)
    assert removed == BASE + f"{gap}# end of file note\n"
    assert tomllib.loads(removed).get("cron", {}) == {}


def test_a_comment_between_the_keys_goes_with_the_replaced_body():
    text = BASE + '\n[cron."a"]\nschedule = "0 1 * * *"\n# between\nenabled = false\n'
    assert apply(text, "a", {"enabled": True}) == BASE + '\n[cron."a"]\nenabled = true\n'


def test_removing_the_last_table_takes_the_blank_lines_after_it():
    text = BASE + '\n[cron."a"]\nenabled = false\n\n\n'
    assert apply(text, "a", None) == BASE


def test_removing_an_absent_override_changes_nothing():
    assert apply(BASE, "nope", None) == BASE


def test_add_after_a_file_without_a_final_newline():
    out = apply(BASE.rstrip("\n"), "a", {"enabled": False})
    assert out == BASE + '\n[cron."a"]\nenabled = false\n'


def test_add_to_an_empty_file():
    assert apply("", "a", {"enabled": False}) == '[cron."a"]\nenabled = false\n'


def test_schedule_is_checked_and_written_single_spaced():
    with pytest.raises(CronError, match="five fields"):
        apply(BASE, "a", {"schedule": "0 7 * *"})
    out = apply(BASE, "a", {"schedule": " 0  7 * * * "})
    assert tomllib.loads(out)["cron"]["a"] == {"schedule": "0 7 * * *"}


@pytest.mark.parametrize(
    "values",
    [{"enabled": "yes"}, {"enabled": 1}, {"schedule": 7}, {"colour": "red"}],
)
def test_other_values_are_refused(values):
    with pytest.raises(CronError):
        apply(BASE, "a", values)


@pytest.mark.parametrize("name", ["", 'we"ird', "back\\slash", "new\nline"])
def test_unusable_task_names_are_refused(name):
    with pytest.raises(CronError):
        apply(BASE, name, {"enabled": False})


def test_text_that_is_not_toml_is_refused():
    with pytest.raises(CronError, match="not valid TOML"):
        apply("[hub\n", "a", {"enabled": False})


def test_load_without_a_cron_table_is_empty(hub: Path):
    assert load(hub) == {}


def test_save_then_load_round_trips(hub: Path):
    save(hub, "plans/morning", {"schedule": "0 7 * * *"})
    save(hub, "ledger/prices", {"enabled": False})
    assert load(hub) == {
        "plans/morning": {"schedule": "0 7 * * *"},
        "ledger/prices": {"enabled": False},
    }
    save(hub, "plans/morning", None)
    assert load(hub) == {"ledger/prices": {"enabled": False}}
    save(hub, "ledger/prices", None)
    assert load(hub) == {}


def test_load_refuses_a_cron_value_that_is_not_a_table_per_task(hub: Path):
    path = hub / "hub.toml"
    path.write_text(path.read_text(encoding="utf-8") + "\n[cron]\nenabled = false\n",
                    encoding="utf-8", newline="\n")
    with pytest.raises(CronError):
        load(hub)


def test_save_keeps_crlf_and_every_other_byte(tmp_path: Path):
    from cc_hub.commands.init import init_hub

    target = tmp_path / "中文 hub"
    init_hub(target, git=False)
    path = target / "hub.toml"
    original = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(original)
    save(target, "a", {"schedule": "0 1 * * *"})
    after = path.read_bytes()
    assert after.startswith(original)
    assert after[len(original):] == b'\r\n[cron."a"]\r\nschedule = "0 1 * * *"\r\n'
    save(target, "a", None)
    assert path.read_bytes() == original
    assert load(target) == {}
