# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.hook import audit_record, evaluate, snippet

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_evaluate_blocks_claude_bash_fixture(hub: Path) -> None:
    blocked, reason = evaluate(load("claude_pretooluse_bash.json"), hub)
    assert blocked and "rm-root" in reason


def test_evaluate_blocks_codex_shell_fixture(hub: Path) -> None:
    blocked, reason = evaluate(load("codex_pretooluse_shell.json"), hub)
    assert blocked and "pipe-to-shell" in reason


def test_evaluate_blocks_codex_list_command_rm_root(hub: Path) -> None:
    payload = {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "rm -rf /"]}}
    blocked, reason = evaluate(payload, hub)
    assert blocked and "rm-root" in reason


def test_evaluate_blocks_protected_read(hub: Path) -> None:
    payload = load("claude_pretooluse_read.json")
    payload["tool_input"]["file_path"] = str(hub / "secrets" / "token.txt")
    blocked, reason = evaluate(payload, hub)
    assert blocked and "protected" in reason


def test_evaluate_blocks_a_protected_path_named_by_a_command(hub: Path) -> None:
    blocked, reason = evaluate({"tool_input": {"command": "cat secrets/key"}}, hub)
    assert blocked and "protected path in command" in reason
    assert evaluate({"tool_input": {"command": "cat .env.example"}}, hub) == (False, "")
    assert evaluate({"tool_input": {"command": "echo hello"}}, hub) == (False, "")
    assert evaluate({"tool_input": {"command": "ls -la /"}}, hub) == (False, "")


def test_evaluate_allows_harmless_and_unknown_shapes(hub: Path) -> None:
    assert evaluate({"tool_name": "Bash", "tool_input": {"command": "ls"}}, hub) == (False, "")
    assert evaluate({"tool_name": "Edit", "tool_input": {"old_string": "a"}}, hub) == (False, "")
    assert evaluate({"tool_input": "not a dict"}, hub) == (False, "")


def test_cli_pre_tool_use_exit_codes(hub: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["--hub", str(hub), "hook", "pre-tool-use"],
        input=json.dumps(load("claude_pretooluse_bash.json")),
    )
    assert r.exit_code == 2
    assert "rm-root" in r.output
    r = runner.invoke(
        app,
        ["--hub", str(hub), "hook", "pre-tool-use"],
        input='{"tool_name": "Bash", "tool_input": {"command": "ls"}}',
    )
    assert r.exit_code == 0
    r = runner.invoke(
        app, ["--hub", str(hub), "hook", "pre-tool-use"], input="this is not json"
    )
    assert r.exit_code == 0


def test_cli_pre_tool_use_fails_open_on_nul_byte_path(hub: Path) -> None:
    payload = r'{"tool_name": "Read", "tool_input": {"file_path": "/tmp/foo\u0000bar"}}'
    r = CliRunner().invoke(app, ["--hub", str(hub), "hook", "pre-tool-use"], input=payload)
    assert r.exit_code == 0


def test_cli_pre_tool_use_uses_blocklist_extra(hub: Path) -> None:
    cfg = hub / "hub.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            "blocklist_extra = []", 'blocklist_extra = ["terraform\\\\s+destroy"]'
        ),
        encoding="utf-8",
    )
    r = CliRunner().invoke(
        app,
        ["--hub", str(hub), "hook", "pre-tool-use"],
        input='{"tool_input": {"command": "terraform destroy"}}',
    )
    assert r.exit_code == 2


def test_cli_string_blocklist_extra_does_not_block_everything(hub: Path) -> None:
    cfg = hub / "hub.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            "blocklist_extra = []", 'blocklist_extra = "terraform destroy"'
        ),
        encoding="utf-8",
    )
    r = CliRunner().invoke(app, ["--hub", str(hub), "hook", "test", "ls"])
    assert r.exit_code == 0, r.output


def test_cli_post_tool_use_appends_jsonl_and_never_fails(hub: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["--hub", str(hub), "hook", "post-tool-use"],
        input=json.dumps(load("claude_posttooluse_bash.json")),
    )
    assert r.exit_code == 0
    logs = list((hub / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    record = json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "Bash" and record["command"] == "ls -la" and record["success"] is True
    r = runner.invoke(app, ["--hub", str(hub), "hook", "post-tool-use"], input="garbage")
    assert r.exit_code == 0


def test_audit_record_shape() -> None:
    rec = audit_record(load("claude_posttooluse_bash.json"), now=datetime(2026, 9, 22, 10, 0, 0))
    assert rec["ts"].startswith("2026-09-22T10:00:00")
    assert rec["session_id"] == "abc123"
    assert rec["cwd"] == "/home/u/.cc-hub"


def test_hook_test_command(hub: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["--hub", str(hub), "hook", "test", "rm -rf /"])
    assert r.exit_code == 2 and "rm-root" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "hook", "test", "ls"])
    assert r.exit_code == 0 and "allowed" in r.output


def test_snippet_shape() -> None:
    data = snippet("/opt/bin/cc-hub")
    pre = data["hooks"]["PreToolUse"][0]
    post = data["hooks"]["PostToolUse"][0]
    assert pre["matcher"] == "Bash|PowerShell|Read"
    assert pre["hooks"][0] == {"type": "command", "command": "/opt/bin/cc-hub hook pre-tool-use"}
    assert post["hooks"][0]["async"] is True
    assert "matcher" not in snippet("/x", matcher=False)["hooks"]["PreToolUse"][0]
    r = CliRunner().invoke(app, ["hook", "snippet", "--exe", "/opt/bin/cc-hub"])
    assert json.loads(r.output)["hooks"]["PostToolUse"][0]["hooks"][0]["command"].endswith(
        "post-tool-use"
    )


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX quoting")
def test_snippet_quotes_an_exe_path_with_spaces() -> None:
    command = snippet("/opt/my tools/cc-hub")["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.startswith("'/opt/my tools/cc-hub'")
    assert command.endswith(" hook pre-tool-use")


def test_snippet_quotes_an_exe_path_with_spaces_on_windows(monkeypatch) -> None:
    from cc_hub.commands import hook as hook_mod

    monkeypatch.setattr(hook_mod, "is_windows", lambda: True)
    command = snippet(r"C:\Program Files\cc-hub.exe")["hooks"]["PreToolUse"][0]["hooks"][0][
        "command"
    ]
    assert command.startswith('"C:\\Program Files\\cc-hub.exe"')
