# -*- coding: utf-8 -*-
"""The restricted-task guard: a Claude Code PreToolUse hook (`cc-hub cron guard`).

A restricted scheduled task declares an ``allow`` list of command prefixes; its unattended
agent run may only execute those commands and may only read inside the hub (and inside the
directories its linked apps point to). Because the hub's sessions run in
``bypassPermissions`` mode, enforcement is a PreToolUse hook that runs before every tool call
of every session. The hook recognises a scheduled run by the pointer prompt in the first user
message of the transcript; a session without one gets no opinion.

Nothing here may raise or print a traceback. Without a pointer prompt any failure means
"no opinion" (``run_hook`` returns ``""``). With one, a task that cannot be evaluated denies
every tool, and a valid task without ``allow`` gets no opinion.

This module is imported on the hook's fast path (``cli.main``), so it must not import typer,
rich or the command modules.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import sys
from pathlib import Path

from cc_hub.applock import load_lock
from cc_hub.crontasks import TASK_NAME, UNSAFE_EXEC_CHARS, CronError, discover
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import find_hub

GUARD_SUFFIX = " cron guard"  # a hook command is `"<path to cc-hub>" cron guard`
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
        with Path(path).open("rb") as handle:
            # read and decode line by line, and stop at the deciding entry: a transcript grows
            # with every tool call, and its lines can be large
            for raw in itertools.islice(handle, _TRANSCRIPT_LINES):
                text = _deciding_text(raw.decode("utf-8"))
                if text is not _SKIP:
                    match = POINTER.search(text)
                    return match.group("name") if match else None
    except (OSError, UnicodeError, ValueError):
        return None
    return None


def _deciding_text(line: str):
    """The text of the first real user message if `line` is it, else ``_SKIP``."""
    line = line.strip()
    if not line:
        return _SKIP
    try:
        entry = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return _SKIP
    if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isMeta"):
        return _SKIP
    return _entry_text(entry)


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
        joined = os.path.join(str(base), os.path.expanduser(raw))
        written = os.path.normpath(joined)
        resolved = os.path.realpath(joined)
        hub_real = os.path.realpath(str(hub))
    except (OSError, ValueError):
        return denied
    # the path as written and the path it resolves to: either one naming secrets/ or a .env*
    # file is enough to deny
    if _closed(written, [str(hub), hub_real]) or _closed(resolved, [hub_real]):
        return denied
    if _below(resolved, hub_real) is None:
        roots = _link_roots(hub, hub_real)
        if not any(_below(resolved, root) is not None for root in roots):
            return denied  # outside the hub and outside every linked app
        if _closed(resolved, roots):
            return denied
    # a recursive tool rooted at the hub itself would reach secrets/; make it name a subtree
    if search and _below(resolved, hub_real) == []:
        app, slash, _ = name.partition("/")
        example = f"apps/{app}" if slash else "memory"
        return _out(
            "deny",
            f"hub:{name} may not search the whole hub, which holds secrets/; "
            f"pass a subfolder as path, such as {example}",
        )
    return _out("allow", f"allowed for hub:{name}")


def _below(path: str, root: str) -> list[str] | None:
    """The parts of `path` below `root` ([] for `root` itself), or None if it is not inside."""
    nc_path, nc_root = os.path.normcase(path), os.path.normcase(root).rstrip("\\/")
    if nc_path.rstrip("\\/") == nc_root:
        return []
    if not nc_path.startswith(nc_root + os.sep):
        return None
    return [part for part in re.split(r"[\\/]", nc_path[len(nc_root) + 1:]) if part]


def _closed(path: str, roots: list[str]) -> bool:
    """Whether `path` is a .env* file or lies in the secrets/ folder of one of `roots`."""
    if _norm_part(os.path.basename(path)).startswith(".env"):
        return True
    for root in roots:
        parts = _below(path, root)
        if parts and _norm_part(parts[0]) == "secrets":
            return True
    return False


def _link_roots(hub: Path, hub_real: str) -> list[str]:
    """The resolved targets of the `apps/<app>` links of apps that apps.lock records as linked
    (`cc-hub app install --link`). A target that holds the hub, or lies inside it, is left out:
    it would open the hub's surroundings, or adds nothing."""
    try:
        apps = load_lock(hub).apps
    except Exception:
        return []
    roots = []
    for app, entry in apps.items():
        if not TASK_NAME.fullmatch(app) or "link" not in entry:
            continue
        try:
            target = os.path.realpath(os.path.join(hub_real, "apps", app))
        except (OSError, ValueError):
            continue
        if _below(target, hub_real) is None and _below(hub_real, target) is None:
            roots.append(target)
    return roots


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


def hook_main() -> None:
    """``cc-hub cron guard``: read the hook event on stdin, print the decision if there is one.

    ``cli.main`` calls this directly, without importing typer or the command modules, because
    the hook runs before every tool call of every session. Never raises.
    """
    decision = run_hook(_read_stdin(), Path.cwd())
    if decision:
        try:
            sys.stdout.write(decision + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def _read_stdin() -> str:
    """The hook's JSON from stdin, decoded as UTF-8; never raises."""
    try:
        return sys.stdin.buffer.read().decode("utf-8", "replace")
    except Exception:
        try:
            return sys.stdin.read()
        except Exception:
            return ""


# --- .claude/settings.json -----------------------------------------------------------------


def guard_program(command: object) -> str | None:
    """The program of a hook command that runs the guard, or None if it does not run it.

    A guard command is ``<program> cron guard`` whose program is ``cc-hub`` or a path to it
    (``cc-hub.exe`` on Windows), bare or quoted; the program is returned without its quotes.
    """
    if not isinstance(command, str):
        return None
    command = command.strip()
    if not command.endswith(GUARD_SUFFIX):
        return None
    program = command[: -len(GUARD_SUFFIX)].strip()
    if len(program) >= 2 and program[0] == program[-1] and program[0] in "\"'":
        program = program[1:-1]
    name = re.split(r"[\\/]", program)[-1].casefold()
    return program if name in ("cc-hub", "cc-hub.exe") else None


def hook_command(program: str) -> str:
    """The hook command that runs the guard with the cc-hub at ``program``.

    The path gets forward slashes and double quotes, which Git Bash, sh and cmd all read the
    same way, so the hook does not depend on the PATH Claude Code runs it with.
    """
    path = Path(program).as_posix()
    if any(char in path for char in UNSAFE_EXEC_CHARS):
        raise CronError(
            f"the path of the cc-hub program, {path}, holds a character a shell would expand "
            '(", $, a backtick or a backslash); install cc-hub in another directory, '
            "then run cc-hub cron guard-setup again"
        )
    return f'"{path}"{GUARD_SUFFIX}'


def find_program(*, which=None, argv0: str | None = None) -> str:
    """The absolute path of cc-hub, with forward slashes: the one on the PATH, else the running
    program. CronError if neither is a cc-hub."""
    found = (which or shutil.which)("cc-hub")
    if not found:
        arg = sys.argv[0] if argv0 is None else argv0
        path = os.path.abspath(arg) if arg and arg != "-c" else ""
        for candidate in (path, path + ".exe") if path else ():
            if guard_program(f"{candidate}{GUARD_SUFFIX}") and os.path.isfile(candidate):
                found = candidate
                break
    if not found:
        raise CronError(
            "cannot find the cc-hub program: it is not on the PATH and this is not it; "
            "put cc-hub on the PATH, then run cc-hub cron guard-setup again"
        )
    return Path(os.path.abspath(found)).as_posix()


def guard_hooks(settings: object) -> list[dict]:
    """The hooks in parsed ``.claude/settings.json`` data that run the guard, under any
    matcher."""
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    entries = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        return []
    return [
        hook
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
        for hook in entry["hooks"]
        if isinstance(hook, dict) and guard_program(hook.get("command")) is not None
    ]


def installed_programs(hub: Path) -> list[str]:
    """The programs the guard hooks of the hub's ``.claude/settings.json`` run; [] when there
    is none, or the file cannot be read."""
    try:
        data = json.loads(read_text(Path(hub) / SETTINGS_REL).lstrip("\ufeff"))
    except (OSError, ValueError):
        return []
    return [guard_program(hook["command"]) for hook in guard_hooks(data)]


def _invalid(detail: str) -> CronError:
    return CronError(f"{SETTINGS_REL} {detail}; fix it, then run cc-hub cron guard-setup again")


def setup(hub: Path, program: str | None = None) -> bool:
    """Make ``.claude/settings.json`` run the guard with the cc-hub at ``program`` (default:
    ``find_program()``), merging; True if the file changed.

    A guard hook that is already there, with the bare ``cc-hub`` or another path, gets the new
    command in place; otherwise a hook is added.
    """
    command = hook_command(find_program() if program is None else program)
    settings = Path(hub) / SETTINGS_REL
    data: dict = {}
    if settings.exists():
        raw = read_text(settings).lstrip("\ufeff")
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
    found = guard_hooks(data)
    if found and all(hook["command"] == command for hook in found):
        return False
    for hook in found:
        hook["command"] = command
    if not found:
        pretool.append({"matcher": "*", "hooks": [{"type": "command", "command": command}]})
    write_text(settings, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True
