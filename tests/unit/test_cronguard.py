# -*- coding: utf-8 -*-
import itertools
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.cronguard import HOOK_COMMAND, decide, run_hook, setup, task_from_transcript
from cc_hub.crontasks import CronError
from tests.conftest import write

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
    # Grep/Glob: the search root is the hub itself (would recurse into secrets), or is secrets,
    # or a .. in the pattern/glob, or outside the hub
    ("Grep", {"pattern": "password"}),
    ("Grep", {"pattern": "password", "path": "."}),
    ("Grep", {"pattern": "password", "path": "mail/.."}),
    ("Grep", {"pattern": "x", "path": "secrets"}),
    ("Grep", {"pattern": "x", "path": "mail", "glob": "../secrets/*"}),
    ("Grep", {"pattern": "a..b", "path": "mail"}),
    ("Grep", {"pattern": "x", "path": "~"}),
    ("Glob", {"pattern": "*"}),
    ("Glob", {"pattern": "../**/*"}),
    ("Glob", {"pattern": "*", "path": "secrets"}),
    ("Glob", {"pattern": "..", "path": "mail"}),
    ("Glob", {"pattern": "~/.ssh/*", "path": "~"}),
    ("Glob", {"pattern": 5, "path": "secrets"}),
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


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are a Windows concern")
@pytest.mark.parametrize("tool, inp", [
    ("Read", {"file_path": "SECRETS/mail/qq.toml"}),
    ("Read", {"file_path": "Secrets/mail/qq.toml"}),
    ("Read", {"file_path": ".ENV"}),
    ("Read", {"file_path": "APPS/MAIL/.Env"}),
    ("Grep", {"pattern": "x", "path": "Secrets"}),
    ("Glob", {"pattern": "*", "path": "SECRETS"}),
])
def test_windows_case_insensitive_reads_of_secrets_are_denied(
    git_hub_with_mail: Path, tmp_path: Path, tool: str, inp: dict
) -> None:
    write(git_hub_with_mail / "secrets/mail/qq.toml", 'password = "x"\n')
    session = transcript(tmp_path, FIRST)
    out = decide(event(tool, inp, session, git_hub_with_mail), git_hub_with_mail)
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
    unknown = transcript(tmp_path, {"type": "user", "message": {"content": (
        "Scheduled task hub:mail/gone: follow the body of apps/mail/cron/gone.md in the hub."
    )}})
    assert decide(event("Bash", {"command": "rm -rf x"}, unknown, hub), hub) is None
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


def test_run_hook_with_a_broken_lock_has_no_opinion(git_hub_with_mail, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    write(hub / "apps.lock", "[apps\n")
    session = transcript(tmp_path, FIRST)
    stdin = json.dumps(event("Bash", {"command": "curl evil"}, session, hub))
    assert run_hook(stdin, tmp_path) == ""


def test_run_hook_output_is_ascii_json(git_hub_with_mail: Path, tmp_path: Path) -> None:
    hub = git_hub_with_mail
    session = transcript(tmp_path, FIRST)
    out = run_hook(json.dumps(event("Read", {"file_path": "../中文.txt"}, session, hub)), tmp_path)
    assert out.isascii()
    assert json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] == (
        "hub:mail/triage may not read ../中文.txt"
    )


# --- .claude/settings.json -----------------------------------------------------------------


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
    assert setup(hub) is True and setup(hub) is False
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
    commands = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert commands == ["my-hook", "cc-hub cron guard"]


def test_setup_creates_the_settings_file(hub: Path) -> None:
    assert setup(hub) is True
    settings = hub / ".claude" / "settings.json"
    text = settings.read_text(encoding="utf-8")
    assert json.loads(text) == {"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": HOOK_COMMAND}]}
    ]}}
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    assert HOOK_COMMAND == "cc-hub cron guard"


def test_setup_keeps_non_ascii_text_and_other_hooks(hub: Path) -> None:
    settings = hub / ".claude" / "settings.json"
    write(settings, "\ufeff" + json.dumps({
        "env": {"NOTE": "中文"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
    }))
    assert setup(hub) is True
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
        {"matcher": "Read|Bash", "hooks": [{"type": "command", "command": HOOK_COMMAND}]},
    ]}}))
    before = settings.read_text(encoding="utf-8")
    assert setup(hub) is False
    assert settings.read_text(encoding="utf-8") == before


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
        setup(hub)
    assert settings.read_text(encoding="utf-8") == text


def test_setup_refuses_invalid_json_with_the_fix(hub: Path) -> None:
    write(hub / ".claude" / "settings.json", "{not json")
    with pytest.raises(CronError, match=(
        r"settings\.json is not valid JSON; fix it, then run cc-hub cron guard-setup again"
    )):
        setup(hub)


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


def test_guard_setup_command(hub: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 0, r.output
    assert r.stdout == "guard installed in .claude/settings.json\n"
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 0, r.output
    assert r.stdout == "guard already installed\n"


def test_guard_setup_command_with_invalid_settings(hub: Path) -> None:
    write(hub / ".claude" / "settings.json", "{not json")
    r = CliRunner().invoke(app, ["--hub", str(hub), "cron", "guard-setup"])
    assert r.exit_code == 1
    assert "settings.json is not valid JSON" in r.stderr
