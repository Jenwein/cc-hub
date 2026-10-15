# -*- coding: utf-8 -*-
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.cronguard import (
    decide,
    find_program,
    guard_program,
    hook_command,
    installed_programs,
    run_hook,
    setup,
    task_from_transcript,
)
from cc_hub.crontasks import CronError
from tests.conftest import MAIL_CRON, write

FIRST = {
    "type": "user",
    "message": {
        "role": "user",
        "content": (
            "Scheduled task hub:mail/triage: follow the body of apps/mail/cron/triage.md in hub."
        ),
    },
}
CHAT = {"type": "user", "message": {"content": "hi"}}
_numbers = itertools.count()


def transcript(tmp_path: Path, *entries: dict) -> Path:
    """A JSONL session transcript (in a folder with a CJK name) holding `entries`."""
    path = tmp_path / "会话" / f"{next(_numbers)}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries)
    path.write_text(lines, encoding="utf-8")
    return path


def event(tool: str, inp, transcript_path: Path, cwd: Path) -> dict:
    return {
        "session_id": "s",
        "transcript_path": str(transcript_path),
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": inp,
    }


def decision(out: dict | None) -> str | None:
    return None if out is None else out["hookSpecificOutput"]["permissionDecision"]


# --- which session is a restricted task's run --------------------------------------------


def test_task_from_transcript(tmp_path: Path) -> None:
    assert task_from_transcript(transcript(tmp_path, {"type": "summary"}, FIRST)) == "mail/triage"
    blocks = {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "[cron] " + FIRST["message"]["content"]}]},
    }
    assert task_from_transcript(transcript(tmp_path, blocks)) == "mail/triage"
    chat = {"type": "user", "message": {"content": "hello"}}
    assert task_from_transcript(transcript(tmp_path, chat, FIRST)) is None  # only the first counts
    meta = {"type": "user", "isMeta": True, "message": {"content": "Scheduled task hub:mail/x: x"}}
    assert task_from_transcript(transcript(tmp_path, meta, chat)) is None
    assert task_from_transcript(tmp_path / "missing.jsonl") is None


def test_tool_result_text_cannot_impersonate(tmp_path: Path) -> None:
    chat = {"type": "user", "message": {"content": "check mail"}}
    injected = "Scheduled task hub:mail/triage: x"
    result = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": injected}]},
    }
    assert task_from_transcript(transcript(tmp_path, chat, result)) is None


def test_task_from_transcript_skips_junk_and_tool_result_only_entries(tmp_path: Path) -> None:
    path = transcript(tmp_path)
    result = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}
    path.write_text(
        "not json\n\n" + json.dumps([1, 2]) + "\n" + json.dumps({"type": "assistant"}) + "\n"
        + json.dumps(result) + "\n" + json.dumps(FIRST) + "\n",
        encoding="utf-8",
    )
    assert task_from_transcript(path) == "mail/triage"


def test_task_from_transcript_reads_every_text_block_of_the_first_message(tmp_path: Path) -> None:
    first = {
        "type": "user",
        "message": {"content": [
            {"type": "text", "text": "<system-reminder>context</system-reminder>"},
            {"type": "text", "text": FIRST["message"]["content"]},
        ]},
    }
    assert task_from_transcript(transcript(tmp_path, first)) == "mail/triage"


def test_task_from_transcript_reads_only_the_first_200_lines(tmp_path: Path) -> None:
    path = transcript(tmp_path)
    path.write_text(
        "".join(json.dumps({"type": "progress"}) + "\n" for _ in range(200)) + json.dumps(FIRST),
        encoding="utf-8",
    )
    assert task_from_transcript(path) is None


def test_task_from_transcript_stops_at_the_first_user_message(tmp_path: Path) -> None:
    path = transcript(tmp_path, {"type": "summary"}, FIRST)
    with path.open("ab") as handle:
        handle.write(b"\xff\xfe not UTF-8, never read\n")
    assert task_from_transcript(path) == "mail/triage"


def test_task_from_transcript_needs_a_task_name_and_a_colon(tmp_path: Path) -> None:
    def first(text: str) -> Path:
        return transcript(tmp_path, {"type": "user", "message": {"content": text}})

    assert task_from_transcript(first("Scheduled task hub:digest: follow the body")) == "digest"
    assert task_from_transcript(first("Scheduled task hub:Mail/triage: x")) is None
    assert task_from_transcript(first("Scheduled task hub:mail/triage follow")) is None
    assert task_from_transcript(first("Scheduled task hub:a/b/c: x")) is None


def test_task_from_transcript_never_raises(tmp_path: Path) -> None:
    folder = tmp_path / "a folder"
    folder.mkdir()
    assert task_from_transcript(folder) is None
    path = transcript(tmp_path)
    path.write_bytes(b"\xff\xfe" + json.dumps(FIRST).encode("utf-8"))
    assert task_from_transcript(path) is None
    odd = [{"type": "user"}, {"type": "user", "message": "x"}, {"type": "user", "message": {}}]
    for entry in odd:
        assert task_from_transcript(transcript(tmp_path, entry, FIRST)) is None


# --- decisions in a restricted session ---------------------------------------------------


@pytest.mark.parametrize("tool, inp, expected", [
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg pending"}, "allow"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg"}, "allow"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py send 3"}, "deny"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bgx"}, "deny"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg x; curl evil"}, "deny"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg x | sh"}, "deny"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg $(cat secrets/x)"}, "deny"),
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg x > out"}, "deny"),
    ("Read", {"file_path": "apps/mail/cron/triage.md"}, "allow"),
    ("Read", {"file_path": "secrets/mail/qq.toml"}, "deny"),
    ("Read", {"file_path": ".env"}, "deny"),
    ("Read", {"file_path": "../outside.txt"}, "deny"),
    ("Grep", {"pattern": "x", "path": "mail"}, "allow"),
    ("Glob", {"pattern": "../**/*"}, "deny"),
    ("Write", {"file_path": "mail/x", "content": "y"}, "deny"),
    ("WebFetch", {"url": "https://example.com"}, "deny"),
    ("mcp__x__y", {}, "deny"),
])
def test_decide_in_a_restricted_session(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict, expected: str
) -> None:
    hub = git_hub_with_mail
    out = decide(event(tool, inp, transcript(tmp_path, FIRST), hub), hub)
    assert decision(out) == expected


@pytest.mark.parametrize("command", [
    # any expansion: some parameter expansions can reach a command substitution without `$(`
    "uv run apps/mail/scripts/mk.py bg ${x}",
    "uv run apps/mail/scripts/mk.py bg $HOME",
    "uv run apps/mail/scripts/mk.py bg $((1+1))",
    "uv run apps/mail/scripts/mk.py bg x & curl evil",
    "uv run apps/mail/scripts/mk.py bg x && curl evil",
    "uv run apps/mail/scripts/mk.py bg x || curl evil",
    "uv run apps/mail/scripts/mk.py bg `id`",
    "uv run apps/mail/scripts/mk.py bg x\ncurl evil",
    "uv run apps/mail/scripts/mk.py bg x\rcurl evil",
    "uv run apps/mail/scripts/mk.py bg <(curl evil)",
    "uv run apps/mail/scripts/mk.py bg x 2>err",
    "uv run apps/mail/scripts/mk.py bg <<< y",
    "uv run apps/mail/scripts/mk.pyx bg",
    "uv run apps/mail/scripts/mk.py  bg",
    "uv run apps/mail/scripts/mk.py\tbg",
    "X=1 uv run apps/mail/scripts/mk.py bg",
    "uv run apps/mail/scripts/mk.py",
    "",
])
def test_bash_denies_what_is_not_one_listed_command(
    git_hub_with_mail: Path, tmp_path: Path, command: str
) -> None:
    session = transcript(tmp_path, FIRST)
    out = decide(event("Bash", {"command": command}, session, git_hub_with_mail), git_hub_with_mail)
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("hub:mail/triage may only run: uv run apps/mail/scripts/mk.py bg")


@pytest.mark.parametrize("inp", [{"command": 5}, {}, "uv run apps/mail/scripts/mk.py bg", None])
def test_bash_with_a_malformed_input_is_denied(
    git_hub_with_mail: Path, tmp_path: Path, inp
) -> None:
    session = transcript(tmp_path, FIRST)
    out = decide(event("Bash", inp, session, git_hub_with_mail), git_hub_with_mail)
    assert decision(out) == "deny"


DENY_READS = [
    # the first hub-relative part is secrets/, in forms Windows collapses onto the real dir
    ("Read", {"file_path": "secrets/mail/qq.toml"}),
    ("Read", {"file_path": "secrets./mail/qq.toml"}),
    ("Read", {"file_path": "secrets /mail/qq.toml"}),
    ("Read", {"file_path": "secrets::$INDEX_ALLOCATION/mail/qq.toml"}),
    ("Read", {"file_path": "mail/../secrets/mail/qq.toml"}),
    ("Read", {"file_path": "secrets"}),
    # the name is a .env file, in several forms
    ("Read", {"file_path": ".env"}),
    ("Read", {"file_path": ".env.local"}),
    ("Read", {"file_path": ".env:$DATA"}),
    ("Read", {"file_path": "apps/mail/.env"}),
    # outside the hub
    ("Read", {"file_path": "../outside.txt"}),
    ("Read", {"file_path": "~/notes.txt"}),
    ("Read", {"file_path": "~"}),
    # malformed → fail closed
    ("Read", {"file_path": 5}),
    ("Read", {"file_path": ""}),
    ("Read", {}),
    # Grep/Glob: the search root is secrets, or a .. in the pattern/glob, or outside the hub
    ("Grep", {"pattern": "x", "path": "secrets"}),
    ("Grep", {"pattern": "x", "path": "mail", "glob": "../secrets/*"}),
    ("Grep", {"pattern": "a..b", "path": "mail"}),
    ("Grep", {"pattern": "x", "path": "~"}),
    ("Glob", {"pattern": "../**/*"}),
    ("Glob", {"pattern": "*", "path": "secrets"}),
    ("Glob", {"pattern": "..", "path": "mail"}),
    ("Glob", {"pattern": "~/.ssh/*", "path": "~"}),
    ("Glob", {"pattern": 5, "path": "secrets"}),
    # a glob that is absolute, starts at a root or home, or names a drive escapes the root
    ("Glob", {"pattern": "/etc/*", "path": "apps"}),
    ("Glob", {"pattern": "\\Windows\\*", "path": "apps"}),
    ("Glob", {"pattern": "C:/Users/*/.ssh/*", "path": "apps"}),
    ("Glob", {"pattern": "c:relative/*", "path": "apps"}),
    ("Glob", {"pattern": "~/.ssh/*", "path": "apps"}),
    ("Glob", {"pattern": "~", "path": "apps"}),
    ("Grep", {"pattern": "x", "path": "apps", "glob": "/etc/*"}),
    ("Grep", {"pattern": "x", "path": "apps", "glob": "~/x"}),
    ("Grep", {"pattern": "x", "path": "apps", "glob": "D:/x/*"}),
]


@pytest.mark.parametrize("tool, inp", DENY_READS)
def test_reads_outside_the_hub_or_of_secrets_are_denied(
    git_hub_with_mail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str, inp
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    write(git_hub_with_mail / "secrets/mail/qq.toml", 'password = "x"\n')
    session = transcript(tmp_path, FIRST)
    out = decide(event(tool, inp, session, git_hub_with_mail), git_hub_with_mail)
    assert decision(out) == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"].startswith(
        "hub:mail/triage may not read "
    )


@pytest.mark.parametrize("tool, inp", [
    ("Read", {"file_path": "SECRETS/mail/qq.toml"}),
    ("Read", {"file_path": "Secrets/mail/qq.toml"}),
    ("Read", {"file_path": "ſecrets/mail/qq.toml"}),  # long s case-folds to s
    ("Read", {"file_path": ".ENV"}),
    ("Read", {"file_path": "apps/mail/.Env"}),
    ("Read", {"file_path": "APPS/MAIL/.Env.Local"}),
    ("Grep", {"pattern": "x", "path": "Secrets"}),
    ("Glob", {"pattern": "*", "path": "SECRETS"}),
])
def test_case_variants_of_secrets_are_denied_on_every_platform(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict
) -> None:
    # case-insensitive file systems (Windows, macOS APFS) map these onto the real entries
    write(git_hub_with_mail / "secrets/mail/qq.toml", 'password = "x"\n')
    session = transcript(tmp_path, FIRST)
    out = decide(event(tool, inp, session, git_hub_with_mail), git_hub_with_mail)
    assert decision(out) == "deny"


WHOLE_HUB = (
    "hub:mail/triage may not search the whole hub, which holds secrets/; "
    "pass a subfolder as path, such as apps/mail"
)


@pytest.mark.parametrize("tool, inp", [
    ("Grep", {"pattern": "password"}),
    ("Grep", {"pattern": "password", "path": "."}),
    ("Grep", {"pattern": "password", "path": "mail/.."}),
    ("Grep", {"pattern": "password", "path": "apps/.."}),
    ("Glob", {"pattern": "*"}),
    ("Glob", {"pattern": "apps/mail/**/*.md"}),
    ("Glob", {"pattern": "*", "path": "."}),
])
def test_a_search_of_the_whole_hub_says_to_pass_a_subfolder(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict
) -> None:
    hub = git_hub_with_mail
    out = decide(event(tool, inp, transcript(tmp_path, FIRST), hub), hub)
    assert decision(out) == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == WHOLE_HUB
    # the same search with the hub as an absolute path, and a hub task's example
    absolute = {**inp, "path": str(hub)}
    out = decide(event(tool, absolute, transcript(tmp_path, FIRST), hub), hub)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == WHOLE_HUB
    write(hub / "cron/digest.md", (
        '---\nschedule: "0 8 * * *"\nsession: new_per_run\n'
        'allow:\n  - "cc-hub memory recent"\n---\nDigest.\n'
    ))
    out = decide(event(tool, inp, pointer(tmp_path, "digest"), hub), hub)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == (
        "hub:digest may not search the whole hub, which holds secrets/; "
        "pass a subfolder as path, such as memory"
    )


def test_an_absolute_glob_into_the_hub_secrets_is_denied(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    pattern = (hub / "secrets").as_posix() + "/**/*"
    out = decide(event("Glob", {"pattern": pattern, "path": "apps"}, session, hub), hub)
    assert decision(out) == "deny"


@pytest.mark.parametrize("tool, inp", [
    ("Read", {"file_path": "apps/mail/cron/triage.md"}),
    ("Read", {"file_path": "mail/secrets/x"}),  # secrets not the first part
    ("Read", {"file_path": "mail/.envoy/../x.env"}),  # resolves to mail/x.env
    ("Read", {"file_path": "hub.toml"}),
    ("Grep", {"pattern": "/api", "path": "apps/mail", "glob": "*.md"}),
    ("Grep", {"pattern": "x", "path": "apps/mail/cron/triage.md"}),
    ("Grep", {"pattern": "x", "path": "apps"}),
    ("Glob", {"pattern": "*.md", "path": "apps/mail/cron"}),
    ("Glob", {"pattern": "**/*.md", "path": "apps"}),
])
def test_reads_inside_the_hub_are_allowed(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict
) -> None:
    session = transcript(tmp_path, FIRST)
    out = decide(event(tool, inp, session, git_hub_with_mail), git_hub_with_mail)
    assert decision(out) == "allow"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "allowed for hub:mail/triage"


def test_absolute_paths_in_the_hub_and_a_cwd_below_it(git_hub_with_mail, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)

    def read(path, cwd=hub):
        return decision(decide(event("Read", {"file_path": str(path)}, session, cwd), hub))

    assert read(hub / "apps" / "mail" / "cron" / "triage.md") == "allow"
    assert read(hub / "secrets" / "mail" / "qq.toml") == "deny"
    below = hub / "apps" / "mail"
    assert read("cron/triage.md", below) == "allow"
    assert read("../../.env", below) == "deny"
    assert decision(decide(event("Grep", {"pattern": "x"}, session, below), hub)) == "allow"


def test_a_link_into_secrets_is_followed(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    write(hub / "secrets/mail/qq.toml", "x\n")
    (hub / "mail").mkdir()
    try:
        os.symlink(hub / "secrets", hub / "mail" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    session = transcript(tmp_path, FIRST)
    out = decide(event("Read", {"file_path": "mail/link/mail/qq.toml"}, session, hub), hub)
    assert decision(out) == "deny"
    # when the search ROOT resolves through the link into secrets, deny
    for tool, inp in [
        ("Grep", {"pattern": "x", "path": "mail/link"}),
        ("Glob", {"pattern": "*", "path": "mail/link/mail"}),
    ]:
        assert decision(decide(event(tool, inp, session, hub), hub)) == "deny", (tool, inp)
    # a root inside the hub but not secrets is allowed
    ok = decide(event("Glob", {"pattern": "*.md", "path": "mail"}, session, hub), hub)
    assert decision(ok) == "allow"


def linked_mail(hub: Path, tmp_path: Path) -> Path:
    """Install the mail app as `cc-hub app install --link` does: apps/mail links outside the hub.

    Returns the link's target, the app's source directory."""
    from cc_hub.platform import LinkError, link_dir

    source = tmp_path / "dev" / "mail"
    for rel, text in MAIL_CRON.items():
        write(source / rel, text)
    write(source / "secrets" / "mail.toml", 'password = "x"\n')
    write(source / ".env", "TOKEN=x\n")
    write(tmp_path / "dev" / "other.txt", "not the app's\n")
    lock = hub / "apps.lock"
    old = lock.read_text(encoding="utf-8") if lock.exists() else ""
    write(lock, old + f'[apps.mail]\nlink = "{source.as_posix()}"\n')
    try:
        link_dir(source, hub / "apps" / "mail")
    except LinkError:
        pytest.skip("cannot create directory links here")
    return source


@pytest.mark.parametrize("tool, inp, expected", [
    ("Read", {"file_path": "apps/mail/cron/triage.md"}, "allow"),
    ("Grep", {"pattern": "x", "path": "apps/mail"}, "allow"),
    ("Grep", {"pattern": "x", "path": "apps/mail/cron", "glob": "*.md"}, "allow"),
    ("Glob", {"pattern": "*.md", "path": "apps/mail/cron"}, "allow"),
    ("Glob", {"pattern": "**/*.md", "path": "apps/mail"}, "allow"),
    # secrets/ and .env* of the link's target are as closed as the hub's own
    ("Read", {"file_path": "apps/mail/secrets/mail.toml"}, "deny"),
    ("Read", {"file_path": "apps/mail/SECRETS/mail.toml"}, "deny"),
    ("Grep", {"pattern": "x", "path": "apps/mail/Secrets"}, "deny"),
    ("Read", {"file_path": "apps/mail/.env"}, "deny"),
    ("Read", {"file_path": "apps/mail/.ENV.local"}, "deny"),
])
def test_a_linked_app_is_read_through_its_link(
    hub: Path, tmp_path: Path, tool: str, inp: dict, expected: str
) -> None:
    linked_mail(hub, tmp_path)
    out = decide(event(tool, inp, transcript(tmp_path, FIRST), hub), hub)
    assert decision(out) == expected, out


def test_a_linked_app_by_absolute_path_and_what_lies_beside_it(
    hub: Path, tmp_path: Path
) -> None:
    source = linked_mail(hub, tmp_path)
    session = transcript(tmp_path, FIRST)

    def read(path) -> str | None:
        return decision(decide(event("Read", {"file_path": str(path)}, session, hub), hub))

    assert read(hub / "apps" / "mail" / "cron" / "triage.md") == "allow"
    assert read(source / "cron" / "triage.md") == "allow"
    assert read(source / "secrets" / "mail.toml") == "deny"
    assert read(source / ".env") == "deny"
    assert read(tmp_path / "dev" / "other.txt") == "deny"  # beside the target, not in it
    # only the link of an app that apps.lock records as linked counts
    write(hub / "apps.lock", '[apps.mail]\ntap = "my-apps"\ncommit = "0123abc"\n')
    out = decide(event("Read", {"file_path": "apps/mail/cron/triage.md"}, session, hub), hub)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == (
        "hub:mail/triage may not read apps/mail/cron/triage.md"
    )


def test_a_link_whose_target_holds_the_hub_opens_nothing(
    hub_with_mail: Path, tmp_path: Path
) -> None:
    from cc_hub.platform import LinkError, link_dir

    hub = hub_with_mail
    beside = tmp_path / "beside.txt"
    write(beside, "x\n")
    lock = hub / "apps.lock"
    write(lock, lock.read_text(encoding="utf-8") + f'[apps.wide]\nlink = "{tmp_path.as_posix()}"\n')
    try:
        link_dir(tmp_path, hub / "apps" / "wide")
    except LinkError:
        pytest.skip("cannot create directory links here")
    session = transcript(tmp_path, FIRST)
    out = decide(event("Read", {"file_path": str(beside)}, session, hub), hub)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == (
        f"hub:mail/triage may not read {beside}"
    )


def test_a_file_written_as_env_is_denied_even_if_it_links_elsewhere(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "apps/mail/notes.txt", "x\n")
    try:
        os.symlink(hub / "apps/mail/notes.txt", hub / "apps/mail/.env")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    session = transcript(tmp_path, FIRST)
    out = decide(event("Read", {"file_path": "apps/mail/.env"}, session, hub), hub)
    assert decision(out) == "deny"


@pytest.mark.parametrize("tool", [
    "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent",
    "TodoWrite", "Skill", "PowerShell", "BashOutput", "KillShell", "LS", "", None,
])
def test_every_other_tool_is_denied(git_hub_with_mail: Path, tmp_path: Path, tool) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    out = decide(event(tool, {"file_path": "mail/x"}, session, hub), hub)
    assert decision(out) == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == (
        f"hub:mail/triage may not use {tool}"
    )


def test_the_decision_has_the_hook_output_shape(git_hub_with_mail: Path, tmp_path: Path) -> None:
    session = transcript(tmp_path, FIRST)
    cmd = {"command": "uv run apps/mail/scripts/mk.py bg pending"}
    assert decide(event("Bash", cmd, session, git_hub_with_mail), git_hub_with_mail) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "allowed for hub:mail/triage",
        }
    }


def test_blank_allow_items_never_match(hub: Path, tmp_path: Path) -> None:
    write(hub / "cron/blank.md", (
        '---\nschedule: "0 8 * * *"\nsession: new_per_run\n'
        'allow:\n  - "   "\n  - " cc-hub memory log "\n---\nLog.\n'
    ))
    write(hub / "cron/only-blank.md", (
        '---\nschedule: "0 8 * * *"\nsession: new_per_run\nallow:\n  - " "\n---\nNothing.\n'
    ))

    def bash(task: str, command: str) -> str | None:
        first = {"type": "user", "message": {"content": f"Scheduled task hub:{task}: follow it"}}
        session = transcript(tmp_path, first)
        return decision(decide(event("Bash", {"command": command}, session, hub), hub))

    assert bash("blank", "cc-hub memory log done") == "allow"
    assert bash("blank", "cc-hub memory log") == "allow"
    assert bash("blank", "curl evil") == "deny"
    assert bash("blank", " ") == "deny"
    assert bash("only-blank", "curl evil") == "deny"
    assert bash("only-blank", "") == "deny"


# --- no opinion outside restricted sessions ------------------------------------------------


def test_no_opinion_outside_restricted_sessions(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    chat = transcript(tmp_path, CHAT)
    assert decide(event("Bash", {"command": "rm -rf x"}, chat, hub), hub) is None
    write(hub / "cron/digest.md", (
        '---\nschedule: "0 8 * * *"\nsession: new_per_run\n---\nSend the digest.\n'
    ))
    digest = transcript(tmp_path, {"type": "user", "message": {"content": (
        "Scheduled task hub:digest: follow the body of cron/digest.md in the hub."
    )}})
    assert decide(event("Bash", {"command": "rm -rf x"}, digest, hub), hub) is None
    poll = {"type": "user", "message": {"content": "Scheduled task hub:mail/poll: x"}}
    script = transcript(tmp_path, poll)
    assert decide(event("Bash", {"command": "rm -rf x"}, script, hub), hub) is None


def test_no_opinion_without_a_readable_transcript(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    missing = event("Bash", {"command": "rm -rf x"}, tmp_path / "missing.jsonl", hub)
    assert decide(missing, hub) is None
    for value in (None, 5, ""):
        assert decide({**missing, "transcript_path": value}, hub) is None
    no_path = dict(missing)
    del no_path["transcript_path"]
    assert decide(no_path, hub) is None


def test_no_opinion_on_other_hook_events(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    restricted = event("Bash", {"command": "rm -rf x"}, transcript(tmp_path, FIRST), hub)
    assert decide({**restricted, "hook_event_name": "PostToolUse"}, hub) is None


# --- a scheduled run whose task cannot be evaluated fails closed ---------------------------


def pointer(tmp_path: Path, name: str) -> Path:
    return transcript(tmp_path, {"type": "user", "message": {"content": (
        f"Scheduled task hub:{name}: follow the body of its file in the hub."
    )}})


NO_TOOLS = "this run may not use tools"


@pytest.mark.parametrize("tool, inp", [
    ("Bash", {"command": "uv run apps/mail/scripts/mk.py bg pending"}),
    ("Read", {"file_path": "apps/mail/cron/triage.md"}),
    ("mcp__x__y", {}),
])
def test_a_pointer_to_a_missing_task_denies_every_tool(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict
) -> None:
    hub = git_hub_with_mail
    out = decide(event(tool, inp, pointer(tmp_path, "mail/gone"), hub), hub)
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("hub:mail/gone has no valid definition: ")
    assert "no task named mail/gone" in reason and reason.endswith(NO_TOOLS)


def test_a_pointer_to_a_broken_task_denies_every_tool(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "apps/mail/cron/triage.md", "---\non_demand: true\nschedule: \"0 1 * * *\"\n---\n")
    out = decide(event("Read", {"file_path": "hub.toml"}, transcript(tmp_path, FIRST), hub), hub)
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("hub:mail/triage has no valid definition: apps/mail/cron/triage.md: ")
    assert reason.endswith(NO_TOOLS)


def test_a_pointer_whose_tasks_cannot_be_read_denies_every_tool(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "apps.lock", "[apps\n")
    for name in ("mail/triage", "digest"):  # restricted or not: it cannot be told
        out = decide(event("Bash", {"command": "ls"}, pointer(tmp_path, name), hub), hub)
        assert decision(out) == "deny"
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith(f"hub:{name} has no valid definition: ")
        assert reason.endswith(NO_TOOLS)


def test_a_valid_task_without_allow_stays_no_opinion_when_another_is_broken(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "cron/broken.md", "---\ndefault: maybe\n---\n")
    write(hub / "cron/digest.md", '---\nschedule: "0 8 * * *"\n---\nDigest.\n')
    assert decide(event("Bash", {"command": "ls"}, pointer(tmp_path, "digest"), hub), hub) is None


# --- the hook entry point ------------------------------------------------------------------


def test_run_hook_never_raises(tmp_path: Path) -> None:
    assert run_hook("not json", tmp_path) == ""
    assert run_hook(json.dumps({"tool_name": "Bash"}), tmp_path) == ""  # no hub, no transcript
    assert run_hook("[]", tmp_path) == ""
    assert run_hook("", tmp_path) == ""
    assert run_hook(json.dumps({"cwd": 5, "transcript_path": []}), tmp_path) == ""


def test_run_hook_decides_with_a_broken_task_file_in_the_hub(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "cron/broken.md", "---\ndefault: maybe\n---\n")
    session = transcript(tmp_path, FIRST)
    denied = run_hook(json.dumps(event("Bash", {"command": "curl evil"}, session, hub)), tmp_path)
    assert decision(json.loads(denied)) == "deny"
    ok = {"command": "uv run apps/mail/scripts/mk.py bg pending"}
    allowed = run_hook(json.dumps(event("Bash", ok, session, hub)), tmp_path)
    assert decision(json.loads(allowed)) == "allow"


def test_run_hook_finds_the_hub_from_the_event_cwd(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    below = hub / "apps" / "mail"
    out = run_hook(json.dumps(event("Bash", {"command": "curl evil"}, session, below)), tmp_path)
    assert decision(json.loads(out)) == "deny"
    # without a cwd in the event, the hook's own cwd is used
    no_cwd = event("Bash", {"command": "curl evil"}, session, hub)
    del no_cwd["cwd"]
    assert decision(json.loads(run_hook(json.dumps(no_cwd), hub))) == "deny"


def test_run_hook_with_a_broken_lock_denies_a_scheduled_run(
    git_hub_with_mail, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    write(hub / "apps.lock", "[apps\n")
    session = transcript(tmp_path, FIRST)
    stdin = json.dumps(event("Bash", {"command": "curl evil"}, session, hub))
    out = json.loads(run_hook(stdin, tmp_path))
    assert decision(out) == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"].endswith(NO_TOOLS)
    # a normal chat in the same broken hub still gets no opinion
    chat = json.dumps(event("Bash", {"command": "ls"}, transcript(tmp_path, CHAT), hub))
    assert run_hook(chat, tmp_path) == ""


def test_run_hook_without_a_hub_denies_a_scheduled_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"  # no ~/.cc-hub to fall back on
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    scheduled = json.dumps(event("Bash", {"command": "ls"}, transcript(tmp_path, FIRST), nowhere))
    out = json.loads(run_hook(scheduled, tmp_path))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("hub:mail/triage has no valid definition: ")
    assert reason.endswith(NO_TOOLS)
    chat = json.dumps(event("Bash", {"command": "ls"}, transcript(tmp_path, CHAT), nowhere))
    assert run_hook(chat, tmp_path) == ""


def test_run_hook_output_is_ascii_json(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    out = run_hook(json.dumps(event("Read", {"file_path": "../中文.txt"}, session, hub)), tmp_path)
    assert out.isascii()
    assert json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] == (
        "hub:mail/triage may not read ../中文.txt"
    )


# --- .claude/settings.json -----------------------------------------------------------------


PROGRAM = "/opt/中文 tools/bin/cc-hub"
GUARD = f'"{PROGRAM}" cron guard'


def guard_commands(settings: Path) -> list[str]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]


def test_setup_merges_and_is_idempotent(hub: Path) -> None:
    settings = hub / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    existing = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]}
        ]},
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")
    assert setup(hub, PROGRAM) is True and setup(hub, PROGRAM) is False
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert guard_commands(settings) == ["my-hook", GUARD]


def test_setup_creates_the_settings_file(hub: Path) -> None:
    assert setup(hub, PROGRAM) is True
    settings = hub / ".claude" / "settings.json"
    text = settings.read_text(encoding="utf-8")
    assert json.loads(text) == {"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": GUARD}]}
    ]}}
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"


def test_setup_keeps_non_ascii_text_and_other_hooks(hub: Path) -> None:
    settings = hub / ".claude" / "settings.json"
    write(settings, "\ufeff" + json.dumps({
        "env": {"NOTE": "中文"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
    }))
    assert setup(hub, PROGRAM) is True
    text = settings.read_text(encoding="utf-8")
    assert "中文" in text
    data = json.loads(text)
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "notify"}]}]
    assert len(data["hooks"]["PreToolUse"]) == 1


def test_setup_finds_the_guard_under_any_matcher(hub: Path) -> None:
    settings = hub / ".claude" / "settings.json"
    write(settings, json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": "not a list"},
        "not an entry",
        {"matcher": "Read|Bash", "hooks": [{"type": "command", "command": GUARD}]},
    ]}}))
    before = settings.read_text(encoding="utf-8")
    assert setup(hub, PROGRAM) is False
    assert settings.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("old", [
    "cc-hub cron guard",  # the bare form, which fails open when cc-hub is not on the PATH
    '"C:/Users/x/AppData/old/cc-hub.exe" cron guard',
    "/usr/local/bin/cc-hub cron guard",
])
def test_setup_rewrites_an_older_guard_command_in_place(hub: Path, old: str) -> None:
    settings = hub / ".claude" / "settings.json"
    write(settings, json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]},
        {"matcher": "Read|Bash", "hooks": [{"type": "command", "command": old, "timeout": 9}]},
    ]}}))
    assert setup(hub, PROGRAM) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]},
        {"matcher": "Read|Bash", "hooks": [{"type": "command", "command": GUARD, "timeout": 9}]},
    ]
    assert setup(hub, PROGRAM) is False


@pytest.mark.parametrize("command, program", [
    ("cc-hub cron guard", "cc-hub"),
    ("cc-hub.exe cron guard", "cc-hub.exe"),
    ('"C:/Users/x/.local/bin/cc-hub.exe" cron guard', "C:/Users/x/.local/bin/cc-hub.exe"),
    ("C:\\Users\\x\\.local\\bin\\CC-HUB.EXE cron guard", "C:\\Users\\x\\.local\\bin\\CC-HUB.EXE"),
    ("/home/x/.local/bin/cc-hub cron guard", "/home/x/.local/bin/cc-hub"),
    ("'/opt/my tools/cc-hub' cron guard", "/opt/my tools/cc-hub"),
    (f"  {GUARD}  ", PROGRAM),
    ("cc-hub cron guard-setup", None),
    ("cc-hub cron guard --verbose", None),
    ("cc-hubx cron guard", None),
    ("/opt/cc-hub/python cron guard", None),
    ("/x/cc-hub.py cron guard", None),
    ("my-hook", None),
    ("cron guard", None),
    (5, None),
    (None, None),
])
def test_guard_program_recognises_cc_hub_or_a_path_to_it(command, program) -> None:
    assert guard_program(command) == program


def test_hook_command_quotes_an_absolute_path_with_forward_slashes(tmp_path: Path) -> None:
    exe = tmp_path / "中文 bin" / "cc-hub.exe"
    command = hook_command(str(exe))
    assert command == f'"{exe.as_posix()}" cron guard'
    assert "\\" not in command and guard_program(command) == exe.as_posix()


@pytest.mark.parametrize("program", ['/opt/a"b/cc-hub', "/opt/$x/cc-hub", "/opt/`x`/cc-hub"])
def test_hook_command_refuses_what_a_shell_would_expand(program: str) -> None:
    with pytest.raises(CronError, match="cc-hub"):
        hook_command(program)


def test_find_program_prefers_the_path_then_the_running_program(tmp_path: Path) -> None:
    on_path = tmp_path / "bin" / "cc-hub.exe"
    assert find_program(which=lambda _: str(on_path), argv0="x") == on_path.as_posix()
    running = tmp_path / "venv" / "cc-hub"
    write(running, "")
    assert find_program(which=lambda _: None, argv0=str(running)) == running.as_posix()
    # a launcher started without its extension, as Windows does
    launcher = tmp_path / "scripts" / "cc-hub.exe"
    write(launcher, "")
    found = find_program(which=lambda _: None, argv0=str(tmp_path / "scripts" / "cc-hub"))
    assert found == launcher.as_posix()


@pytest.mark.parametrize("argv0", ["", "pytest", "-c", "missing/cc-hub"])
def test_find_program_fails_without_a_cc_hub(tmp_path: Path, argv0: str) -> None:
    write(tmp_path / "pytest", "")
    arg = str(tmp_path / argv0) if argv0 not in ("", "-c") else argv0
    with pytest.raises(CronError, match="cannot find the cc-hub program"):
        find_program(which=lambda _: None, argv0=arg)


def test_installed_programs(hub: Path) -> None:
    assert installed_programs(hub) == []
    write(hub / ".claude" / "settings.json", json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]},
        {"matcher": "*", "hooks": [{"type": "command", "command": GUARD}]},
        {"matcher": "Read", "hooks": [{"type": "command", "command": "cc-hub cron guard"}]},
    ]}}))
    assert installed_programs(hub) == [PROGRAM, "cc-hub"]
    write(hub / ".claude" / "settings.json", "{not json")
    assert installed_programs(hub) == []


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    json.dumps({"hooks": []}),
    json.dumps({"hooks": {"PreToolUse": {}}}),
])
def test_setup_refuses_invalid_settings(hub: Path, text: str) -> None:
    settings = hub / ".claude" / "settings.json"
    write(settings, text)
    with pytest.raises(CronError, match=r"settings\.json"):
        setup(hub, PROGRAM)
    assert settings.read_text(encoding="utf-8") == text


def test_setup_refuses_invalid_json_with_the_fix(hub: Path) -> None:
    write(hub / ".claude" / "settings.json", "{not json")
    with pytest.raises(CronError, match=(
        r"settings\.json is not valid JSON; fix it, then run cc-hub cron guard-setup again"
    )):
        setup(hub, PROGRAM)


# --- the commands --------------------------------------------------------------------------


def test_guard_command_prints_the_decision(
    git_hub_with_mail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CC_HUB_DIR", raising=False)
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    stdin = json.dumps(event("Bash", {"command": "curl evil"}, session, hub), ensure_ascii=False)
    r = CliRunner().invoke(app, ["cron", "guard"], input=stdin.encode("utf-8"))
    assert r.exit_code == 0, r.output
    assert decision(json.loads(r.stdout)) == "deny"


def test_guard_command_is_silent_without_an_opinion(
    git_hub_with_mail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CC_HUB_DIR", raising=False)
    hub = git_hub_with_mail
    chat = json.dumps(event("Bash", {"command": "rm -rf x"}, transcript(tmp_path, CHAT), hub))
    nowhere = json.dumps(event("Bash", {"command": "x"}, tmp_path / "none.jsonl", tmp_path))
    for stdin in (chat, nowhere, "not json", "", "\udcff"):
        r = CliRunner().invoke(app, ["cron", "guard"], input=stdin.encode("utf-8", "surrogatepass"))
        assert r.exit_code == 0, r.output
        assert r.stdout == ""
        assert r.stderr == ""


def test_guard_command_ignores_hub_option(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    stdin = json.dumps(event("Bash", {"command": "curl evil"}, session, hub))
    r = CliRunner().invoke(app, ["--hub", str(tmp_path / "nowhere"), "cron", "guard"], input=stdin)
    assert r.exit_code == 0, r.output
    assert decision(json.loads(r.stdout)) == "deny"


FAST_PATH = """
import sys
sys.argv = ["cc-hub", *sys.argv[1:]]
from cc_hub.cli import main
main()
heavy = [m for m in sys.modules if m.split(".")[0] in ("typer", "click", "rich")
         or m.startswith("cc_hub.commands")]
sys.stderr.write(repr((sorted(heavy), sys.stdout.encoding)))
"""


def fast_path(args: list[str], stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    """`cc-hub <args>` through `cli.main`, in a fresh interpreter."""
    return subprocess.run(
        [sys.executable, "-c", FAST_PATH, *args], input=stdin.encode("utf-8"),
        capture_output=True, cwd=cwd, timeout=120,
    )


def test_the_guard_fast_path_answers_like_run_hook_without_loading_the_cli(
    git_hub_with_mail: Path, tmp_path: Path
) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    stdins = [
        json.dumps(event("Bash", {"command": "curl evil"}, session, hub)),
        json.dumps(event("Bash", {"command": "uv run apps/mail/scripts/mk.py bg"}, session, hub)),
        json.dumps(event("Read", {"file_path": "../中文.txt"}, session, hub), ensure_ascii=False),
        json.dumps(event("Bash", {"command": "rm -rf x"}, transcript(tmp_path, CHAT), hub)),
        "not json",
    ]
    for stdin in stdins:
        proc = fast_path(["cron", "guard"], stdin, tmp_path)
        assert proc.returncode == 0, proc.stderr
        expected = run_hook(stdin, tmp_path)
        assert proc.stdout.decode("utf-8").replace("\r\n", "\n") == (
            expected + "\n" if expected else ""
        )
        assert proc.stderr.decode("utf-8") == "([], 'utf-8')"
    assert decision(json.loads(run_hook(stdins[0], tmp_path))) == "deny"


def test_cron_guard_with_more_arguments_goes_through_the_cli(tmp_path: Path) -> None:
    proc = fast_path(["cron", "guard", "--help"], "", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "PreToolUse hook" in proc.stdout.decode("utf-8")


def test_guard_setup_command(hub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "bin" / "cc-hub.exe"
    monkeypatch.setattr("shutil.which", lambda name: str(exe) if name == "cc-hub" else None)
    command = f'"{exe.as_posix()}" cron guard'
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 0, r.output
    assert r.stdout == f"guard installed in .claude/settings.json: {command}\n"
    assert guard_commands(hub / ".claude" / "settings.json") == [command]
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 0, r.output
    assert r.stdout == f"guard already installed: {command}\n"


def test_guard_setup_command_without_a_cc_hub_program(
    hub: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("sys.argv", ["pytest"])
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 1
    assert "cannot find the cc-hub program" in r.stderr
    assert not (hub / ".claude" / "settings.json").exists()


def test_guard_setup_command_with_invalid_settings(hub: Path) -> None:
    write(hub / ".claude" / "settings.json", "{not json")
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 1
    assert "settings.json is not valid JSON" in r.stderr
