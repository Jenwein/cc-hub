# -*- coding: utf-8 -*-
"""The restricted-task guard: a Claude Code PreToolUse hook (`cc-hub cron guard`).

A restricted scheduled task declares an ``allow`` list of command prefixes; its unattended
agent run may only execute those commands and may only read inside the hub. Because the hub's
sessions run in ``bypassPermissions`` mode, enforcement is a PreToolUse hook that runs before
every tool call of every session. The hook recognises a scheduled run by the pointer prompt
in the first user message of the transcript; a session without one gets no opinion.

Nothing here may raise or print a traceback. Without a pointer prompt any failure means
"no opinion" (``run_hook`` returns ``""``). With one, a task that cannot be evaluated denies
every tool, and a valid task without ``allow`` gets no opinion.
"""

from __future__ import annotations

import itertools
import json
import os
import re
from pathlib import Path

from cc_hub.crontasks import CronError, discover
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import find_hub

HOOK_COMMAND = "cc-hub cron guard"
SETTINGS_REL = ".claude/settings.json"

# the pointer prompt a restricted task's session opens with (crontasks.pointer_prompt)
POINTER = re.compile(r"Scheduled task hub:(?P<name>[a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?):")
# a shell would act on any of these inside a command, chaining or expanding past the prefix;
# bare ``$`` (not only ``$(``) is rejected because several parameter expansions can reach a
# command substitution without ``$(``, and ``\r`` because it is not caught by ``\n``
UNSAFE_BASH = re.compile(r"[;&|`$<>\n\r]")
DRIVE = re.compile(r"[A-Za-z]:")
_TRANSCRIPT_LINES = 200
_SKIP = object()  # an entry that is not the deciding user message (e.g. only tool_result blocks)


def _entry_text(entry: dict):
    """The deciding text of a user entry, or ``_SKIP`` if it is not the deciding message."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
        # content that is only tool_result (foreign data) is skipped, never the decider
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return _SKIP
    return ""


def task_from_transcript(path: Path) -> str | None:
    """The restricted-task name from the first real user message of the transcript, or None.

    Only the first user message (not meta, not a tool-result-only entry) counts, so foreign
    content arriving later in tool results cannot impersonate a task's pointer prompt.
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            lines = list(itertools.islice(handle, _TRANSCRIPT_LINES))
    except (OSError, UnicodeError, ValueError):
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isMeta"):
            continue
        text = _entry_text(entry)
        if text is _SKIP:
            continue
        match = POINTER.search(text)
        return match.group("name") if match else None
    return None


def _out(decision: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def _norm_part(part: str) -> str:
    """A path component normalised for comparison on every platform: case-folded (Windows and
    macOS file systems are case-insensitive, and `realpath` on POSIX does not correct case),
    without the trailing dots/spaces and ``name::stream`` suffix that Windows collapses onto
    the real entry."""
    return part.rstrip(" .").split(":", 1)[0].casefold()


def _rooted(value: str) -> bool:
    """Whether a glob names its own starting point (absolute, root, home or a drive letter),
    so the search no longer starts at the checked path."""
    return (
        value.startswith(("/", "\\", "~"))
        or DRIVE.match(value) is not None
        or os.path.isabs(value)
    )


def _bash(name: str, allow: list[str], tool_input) -> dict:
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    only = f"hub:{name} may only run: {', '.join(allow)}"
    if not isinstance(command, str):
        return _out("deny", only)
    if UNSAFE_BASH.search(command):
        return _out("deny", only)
    if any(command == prefix or command.startswith(prefix + " ") for prefix in allow):
        return _out("allow", f"allowed for hub:{name}")
    return _out("deny", only)


def _read(name: str, tool: str, tool_input, hub: Path, cwd) -> dict:
    inp = tool_input if isinstance(tool_input, dict) else {}
    search = tool in ("Grep", "Glob")
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path(hub)

    if search:
        # a .. in the pattern or the file filter could climb out; a non-string one is junk; a
        # path glob (Glob's pattern, Grep's glob) that is rooted escapes the checked path.
        # Grep's pattern is a regex, not a path, so only the .. rule applies to it.
        path_glob = "pattern" if tool == "Glob" else "glob"
        for key in ("pattern", "glob"):
            value = inp.get(key)
            if value is None:
                continue
            if (
                not isinstance(value, str)
                or ".." in value
                or (key == path_glob and _rooted(value))
            ):
                return _out("deny", f"hub:{name} may not read {value}")
        raw = inp.get("path")
        if raw is None:
            raw = str(base)
    else:
        raw = inp.get("file_path")
    if not isinstance(raw, str) or not raw:
        return _out("deny", f"hub:{name} may not read {raw}")

    denied = _out("deny", f"hub:{name} may not read {raw}")
    try:
        resolved = os.path.realpath(os.path.join(str(base), os.path.expanduser(raw)))
        hub_real = os.path.realpath(str(hub))
    except (OSError, ValueError):
        return denied
    nc_resolved = os.path.normcase(resolved)
    nc_hub = os.path.normcase(hub_real)
    if nc_resolved != nc_hub and not nc_resolved.startswith(nc_hub + os.sep):
        return denied  # outside the hub
    rel = os.path.relpath(resolved, hub_real)
    parts = [] if rel in (".", "") else rel.replace("\\", "/").split("/")
    if parts and _norm_part(parts[0]) == "secrets":
        return denied
    if _norm_part(os.path.basename(resolved)).startswith(".env"):
        return denied
    # a recursive tool rooted at the hub itself would reach secrets/; make it name a subtree
    if search and nc_resolved == nc_hub:
        return denied
    return _out("allow", f"allowed for hub:{name}")


def _no_tools(name: str, problem: str) -> dict:
    problem = " ".join(str(problem).split()) or "unknown"
    return _out(
        "deny", f"hub:{name} has no valid definition: {problem}; this run may not use tools"
    )


def decide(event: dict, hub: Path | None) -> dict | None:
    """The hook's decision for one tool call, or None for no opinion (normal permission flow).

    ``hub`` is None when no hub could be found. A session without a pointer prompt always gets
    no opinion. A pointer prompt only comes from a scheduled run, so when its task cannot be
    evaluated (no hub, unreadable tasks, no such task, a broken definition) every tool is
    denied; a valid task without ``allow`` gets no opinion.
    """
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return None
    transcript = event.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return None
    name = task_from_transcript(Path(transcript))
    if name is None:
        return None
    try:
        return _decide_for(name, event, hub)
    except Exception as exc:  # inside a recognised scheduled run: fail closed
        return _no_tools(name, f"the guard could not check it ({exc})")


def _decide_for(name: str, event: dict, hub: Path | None) -> dict | None:
    if hub is None:
        return _no_tools(name, "no hub found")
    try:
        tasks = discover(hub)
    except Exception as exc:
        return _no_tools(name, f"cannot read the hub's tasks: {exc}")
    task = next((t for t in tasks if t.name == name), None)
    if task is None:
        return _no_tools(name, f"no task named {name}")
    if task.definition is None:
        return _no_tools(name, task.error or "the definition cannot be read")
    if not task.definition.allow:
        return None  # a valid task that is not restricted
    allow = [prefix.strip() for prefix in task.definition.allow if prefix.strip()]

    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if tool == "Bash":
        return _bash(name, allow, tool_input)
    if tool in ("Read", "Grep", "Glob"):
        return _read(name, tool, tool_input, hub, event.get("cwd"))
    return _out("deny", f"hub:{name} may not use {tool}")


def run_hook(stdin_text: str, cwd: Path) -> str:
    """The hook entry point: JSON to print on stdout, or ``""`` for no opinion. Never raises."""
    try:
        event = json.loads(stdin_text)
        if not isinstance(event, dict):
            return ""
        event_cwd = event.get("cwd")
        base = Path(event_cwd) if isinstance(event_cwd, str) and event_cwd else Path(cwd)
        try:
            hub: Path | None = find_hub(cwd=base, env={})
        except Exception:
            hub = None  # decide still fails closed for a scheduled run, and ignores a chat
        decision = decide(event, hub)
        return "" if decision is None else json.dumps(decision)
    except Exception:
        return ""


def _invalid(detail: str) -> CronError:
    return CronError(f"{SETTINGS_REL} {detail}; fix it, then run cc-hub cron guard-setup again")


def setup(hub: Path) -> bool:
    """Add the guard hook to ``.claude/settings.json`` (merging, idempotent). True if changed."""
    settings = Path(hub) / ".claude" / "settings.json"
    data: dict = {}
    if settings.exists():
        raw = read_text(settings).lstrip("﻿")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise _invalid("is not valid JSON") from None
        if not isinstance(data, dict):
            raise _invalid("must be a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise _invalid('has a "hooks" that is not a JSON object')
    pretool = hooks.setdefault("PreToolUse", [])
    if not isinstance(pretool, list):
        raise _invalid('has a "hooks.PreToolUse" that is not a list')
    for entry in pretool:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        if isinstance(inner, list) and any(
            isinstance(h, dict) and h.get("command") == HOOK_COMMAND for h in inner
        ):
            return False
    pretool.append({"matcher": "*", "hooks": [{"type": "command", "command": HOOK_COMMAND}]})
    write_text(settings, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True
