# -*- coding: utf-8 -*-
"""cc-hub hook: pre/post tool-use hooks. Same JSON protocol for Claude Code and Codex."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import typer

from cc_hub.blocklist import is_protected_path, match_command, normalize
from cc_hub.encoding import append_text, decode_bytes
from cc_hub.hub import HubNotFound, find_hub, load_config

COMMAND_KEYS = ("command", "cmd")
PATH_KEYS = ("file_path", "path", "filePath")


def extract_command(tool_input: dict) -> str | None:
    for key in COMMAND_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list) and value:
            return " ".join(str(v) for v in value)
    return None


def extract_path(tool_input: dict) -> str | None:
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def evaluate(payload: dict, hub: Path, *, extra: Iterable[str] = ()) -> tuple[bool, str]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False, ""
    command = extract_command(tool_input)
    if command:
        rule = match_command(command, extra)
        if rule:
            return True, f"cc-hub blocked this command (rule {rule}): {normalize(command)[:200]}"
    path = extract_path(tool_input)
    if path and is_protected_path(path, hub):
        return True, f"cc-hub blocked access to a protected path (secrets/ or .env): {path}"
    return False, ""


def default_exe() -> str:
    found = shutil.which("cc-hub")
    return found if found else f"{sys.executable} -m cc_hub"


def snippet(exe: str | None = None, *, matcher: bool = True) -> dict:
    exe = exe or default_exe()
    pre: dict = {}
    post: dict = {}
    if matcher:
        pre["matcher"] = "Bash|PowerShell|Read"
        post["matcher"] = "Bash|PowerShell"
    pre["hooks"] = [{"type": "command", "command": f"{exe} hook pre-tool-use"}]
    post["hooks"] = [{"type": "command", "command": f"{exe} hook post-tool-use", "async": True}]
    return {"hooks": {"PreToolUse": [pre], "PostToolUse": [post]}}


def audit_record(payload: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    response = payload.get("tool_response")
    record: dict = {
        "ts": now.isoformat(timespec="seconds"),
        "session_id": payload.get("session_id"),
        "tool": payload.get("tool_name"),
        "cwd": payload.get("cwd"),
    }
    command = extract_command(tool_input)
    if command:
        record["command"] = normalize(command)[:500]
    path = extract_path(tool_input)
    if path:
        record["path"] = path
    exit_code = None
    if isinstance(response, dict):
        exit_code = response.get("exit_code", response.get("exitCode"))
        record["success"] = not response.get("is_error", False) and exit_code in (None, 0)
    else:
        record["success"] = not payload.get("error")
    if exit_code is not None:
        record["exit_code"] = exit_code
    return record


def append_audit(hub: Path, record: dict) -> Path:
    path = Path(hub) / "logs" / f"{record['ts'][:10]}.jsonl"
    append_text(path, json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_payload(stream=None) -> dict:
    stream = stream or sys.stdin
    raw = stream.buffer.read() if hasattr(stream, "buffer") else stream.read().encode("utf-8")
    data = json.loads(decode_bytes(raw))
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data


def _try_hub(ctx: typer.Context) -> Path | None:
    try:
        return find_hub((ctx.obj or {}).get("hub"))
    except HubNotFound:
        return None


def _extra(hub: Path | None) -> list[str]:
    if hub is None:
        return []
    try:
        return [str(p) for p in load_config(hub).get("hooks", {}).get("blocklist_extra", [])]
    except Exception:  # noqa: BLE001 - a broken hub.toml must not disable the built-in rules
        return []


hook_app = typer.Typer(
    no_args_is_help=True, help="Hooks invoked by the agent runtime around tool calls."
)


@hook_app.command("pre-tool-use")
def pre_tool_use(ctx: typer.Context) -> None:
    """Read the tool-call JSON from stdin; exit 2 to block catastrophic commands."""
    hub = _try_hub(ctx)
    try:
        payload = read_payload()
    except (ValueError, OSError) as exc:
        typer.echo(f"cc-hub hook: could not parse payload ({exc}); allowing", err=True)
        raise typer.Exit(code=0) from exc
    blocked, reason = evaluate(payload, hub or Path.cwd(), extra=_extra(hub))
    if blocked:
        typer.echo(reason, err=True)
        raise typer.Exit(code=2)


@hook_app.command("post-tool-use")
def post_tool_use(ctx: typer.Context) -> None:
    """Append one JSON line per tool call to logs/YYYY-MM-DD.jsonl. Never fails."""
    try:
        hub = _try_hub(ctx)
        if hub is None:
            return
        append_audit(hub, audit_record(read_payload()))
    except Exception as exc:  # noqa: BLE001 - logging must never block the agent
        typer.echo(f"cc-hub hook: audit skipped ({exc})", err=True)


@hook_app.command("test")
def test_cmd(
    ctx: typer.Context, command: str = typer.Argument(..., help="Command to check.")
) -> None:
    """Check a command against the blocklist without running it."""
    rule = match_command(command, _extra(_try_hub(ctx)))
    if rule:
        typer.echo(f"BLOCKED by rule {rule}")
        raise typer.Exit(code=2)
    typer.echo("allowed")


@hook_app.command("snippet")
def snippet_cmd(
    exe: str | None = typer.Option(
        None, "--exe", help="Absolute path to cc-hub (default: auto-detect)."
    ),
    no_matcher: bool = typer.Option(
        False, "--no-matcher", help="Match every tool; filter inside the hook."
    ),
) -> None:
    """Print the hooks JSON to merge into the agent's hook configuration."""
    from cc_hub.console import echo_json

    echo_json(snippet(exe, matcher=not no_matcher))


def register(app: typer.Typer) -> None:
    app.add_typer(hook_app, name="hook")
