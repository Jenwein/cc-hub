# -*- coding: utf-8 -*-
import pytest

from cc_hub.apps import (
    AppError,
    AppManifest,
    AppPlan,
    Requirement,
    check_entry_path,
    check_name,
    inside,
    normalize_data_dir,
    overlaps,
    parse_cron,
    parse_manifest,
    version_tuple,
)
from cc_hub.commands.app import overview
from cc_hub.crontasks import TaskDef

GOOD = """
[app]
name = "ledger"
version = "0.1.0"
description = "Bookkeeping"
min_hub = "0.4"
issues = "https://github.com/you/my-apps/issues"

[data]
dirs = ["ledger", "reports/ledger"]

[[requires]]
name = "beancount"
bin = "bean-check"
install = "uv tool install beancount"

[[requires]]
name = "hledger"
bin = "hledger"

[requires.install]
linux = "sudo apt install hledger"
macos = "brew install hledger"
"""

HEAD = '[app]\nname = "ledger"\nversion = "1"\ndescription = "d"\n'


def test_parse_manifest_reads_every_field() -> None:
    m = parse_manifest(GOOD, dirname="ledger")
    assert (m.name, m.version, m.description, m.min_hub) == (
        "ledger", "0.1.0", "Bookkeeping", "0.4",
    )
    assert m.issues == "https://github.com/you/my-apps/issues"
    assert m.data_dirs == ["ledger", "reports/ledger"]
    assert m.requires[0] == Requirement("beancount", "bean-check", "uv tool install beancount")
    assert m.requires[0].install_line("windows") == "uv tool install beancount"
    assert m.requires[1].install_line("linux") == "sudo apt install hledger"
    assert m.requires[1].install_line("windows") is None


@pytest.mark.parametrize(
    "text, message",
    [
        ("[app\n", "app.toml"),
        ('[app]\nname = "ledger"\nversion = "1"\n', "description is required"),
        (HEAD.replace('"ledger"', '"other"'), "directory name"),
        (HEAD + 'min_hub = "next"\n', "version"),
        (HEAD + '[[requires]]\nname = "x"\n', "name and bin"),
        (HEAD + '[data]\ndirs = ["a", "a/b"]\n', "overlap"),
        (HEAD + '[data]\ndirs = ["memory"]\n', "belongs to the hub"),
        # Top-level keys must come before the [app] header, or they land inside [app].
        ("data = 1\n" + HEAD, r"\[data\] must be a table"),
        (HEAD + "[[data]]\nx = 1\n", r"\[data\] must be a table"),
        ("requires = 5\n" + HEAD, r"\[\[requires\]\] must be a list of tables"),
        (HEAD + '[[requires]]\nname = ""\nbin = "x"\n', "name must not be empty"),
        (HEAD + '[[requires]]\nname = "x"\nbin = ""\n', "bin must not be empty"),
        (HEAD + '[[requires]]\nname = "x"\nbin = "x"\ninstall = ""\n',
         "install must be a non-empty string or a table"),
        (HEAD + '[[requires]]\nname = "x"\nbin = "x"\n[requires.install]\nlinux = 5\n',
         "install.linux must be a non-empty string"),
        (HEAD + '[[requires]]\nname = "x"\nbin = "x"\n[requires.install]\nbeos = "y"\n',
         "install keys must be linux, macos or windows"),
    ],
)
def test_parse_manifest_rejects(text: str, message: str) -> None:
    with pytest.raises(AppError, match=message):
        parse_manifest(text, dirname="ledger")


def test_names() -> None:
    assert check_name("hub-apps", "tap name") == "hub-apps"
    for bad in ("Ledger", "-x", "a_b", "x" * 65, ""):
        with pytest.raises(AppError):
            check_name(bad, "app name")
    with pytest.raises(AppError, match="hub-"):
        check_name("hub-ledger", "skill name", skill=True)


def test_versions() -> None:
    assert version_tuple("0.4") == (0, 4, 0)
    assert version_tuple("1.2.3") > version_tuple("1.2")


@pytest.mark.parametrize(
    "raw",
    ["memory", "Skills/x", ".secret", "apps", "apps.lock", "USER.md", "/abs", "a/../b",
     "a\\b", "C:/x", "secrets/k", "", "memory.", "memory ", "ledger/con", "ledger/nul.txt",
     "led\x01ger",
     # 8.3 short names reach .git, .cc-hub and .claude on NTFS
     "GIT~1", "ledger/GIT~1", "CC-HUB~1", "a~b",
     # hidden parts at any depth, spaces and non-ASCII characters
     "ledger/.hidden", "ledger/.git", "data dir", "ledger/my data", "账本", "ledger/账本"],
)
def test_data_dir_rejects(raw: str) -> None:
    with pytest.raises(AppError):
        normalize_data_dir(raw)


@pytest.mark.parametrize("raw", ["ledger/2026", "reports/ledger", "a.b/c-d_e", "Ledger"])
def test_data_dir_accepts(raw: str) -> None:
    assert normalize_data_dir(raw) == raw


def test_data_dir_relations() -> None:
    assert normalize_data_dir("ledger/2026") == "ledger/2026"
    assert normalize_data_dir("console/nulled") == "console/nulled"
    assert overlaps("ledger", "Ledger/x") and not overlaps("ledger", "ledgers")
    assert inside("ledger/main.beancount", "ledger") and not inside("ledger", "ledger")


def test_entry_paths() -> None:
    for good in ("skills/ledger/SKILL.md", "seed/ledger/main.beancount", "ledger/2026",
                 "reports/ledger", "a.b/c-d_e"):
        check_entry_path(good)
    for bad in ("../x", "a/./b", ".git/config", "a\\b", "c:x",
                ".GIT/config", ".git./x", "a/b ", "a/CON", "a/\x07b",
                "skills/GIT~1/x", "a~b", "seed/CC-HUB~1/x"):
        with pytest.raises(AppError):
            check_entry_path(bad)


def test_parse_cron() -> None:
    text = (
        '---\nschedule: "0 9 1 * *"  # monthly\ndefault: true\nsession: new_per_run\n---\n'
        "Summarise.\n"
    )
    assert parse_cron(text, where="x") == TaskDef(
        "prompt", "0 9 1 * *", True, "new_per_run", False, None, None, ()
    )
    with pytest.raises(AppError):
        parse_cron("no frontmatter", where="x")
    with pytest.raises(AppError, match="^apps/a/cron/t.md: .*schedule is required"):
        parse_cron("---\ndefault: true\n---\nbody\n", where="apps/a/cron/t.md")


def test_parse_cron_rejects_an_exec_a_shell_would_expand() -> None:
    text = '---\nschedule: "0 9 * * *"\nexec: "echo $(whoami)"\n---\nbody\n'
    with pytest.raises(AppError, match="^apps/a/cron/t.md: exec must not contain"):
        parse_cron(text, where="apps/a/cron/t.md")


class _Source:
    def describe(self) -> str:
        return "my-apps@abc1234"


def test_overview_lists_each_kind_of_task() -> None:
    crons = {
        "nightly": TaskDef("prompt", "0 3 * * *", True, "reuse", False, None, None, ()),
        "quiet": TaskDef("prompt", "0 4 * * *", False, "new_per_run", True, None, None, ()),
        "poll": TaskDef("exec", "*/5 * * * *", True, None, False, "uv run x poll", 10, ()),
        "triage": TaskDef(
            "on_demand", None, True, "new_per_run", True, None, None, ("uv run x bg", "cc-hub log"),
        ),
    }
    plan = AppPlan(
        AppManifest("mail", "0.1.0", "Mail"), _Source(), [], crons, [], [], False, False
    )
    lines = overview(plan)
    assert lines[lines.index("scheduled tasks:") + 1 :][:4] == [
        "  hub:mail/nightly: 0 3 * * * (default, reuse)",
        "  hub:mail/poll: */5 * * * * runs `uv run x poll` (default, script, silent)",
        "  hub:mail/quiet: 0 4 * * * (optional, new_per_run, silent)",
        "  hub:mail/triage: on demand (default, new_per_run) allow: uv run x bg, cc-hub log",
    ]
