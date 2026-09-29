# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ("init", "doctor", "update", "env", "memory", "hosts", "projects", "link")
REMOVED = ("jobs", "hook")
REMOVED_SUBCOMMANDS = ("hosts run", "hosts check", "hosts push", "hosts pull",
                       "memory stats", "hosts list|check", "log|search|recent|stats")


def test_readme_mentions_every_command() -> None:
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        for cmd in COMMANDS:
            assert f"cc-hub {cmd}" in readme, (name, cmd)
        for cmd in REMOVED:
            assert f"cc-hub {cmd}" not in readme, (name, cmd)
        for sub in REMOVED_SUBCOMMANDS:
            assert sub not in readme.replace("\\|", "|"), (name, sub)


def test_cli_has_no_removed_commands() -> None:
    from cc_hub.cli import app

    names = {c.name for c in app.registered_commands} | {
        g.name for g in app.registered_groups
    }
    assert set(COMMANDS) <= names
    assert not set(REMOVED) & names


def test_docs_exist_and_are_utf8_lf() -> None:
    for name in ("install.md", "cc-connect.md", "windows.md", "codex-sandbox.md", "acceptance.md"):
        raw = (ROOT / "docs" / name).read_bytes()
        assert raw and b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf"), name
    cc_connect_text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    assert "projects.agent.options.env" in cc_connect_text
    codex_sandbox_text = (ROOT / "docs" / "codex-sandbox.md").read_text(encoding="utf-8")
    assert "writable_roots" in codex_sandbox_text
    assert "## 0.1.0" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_docs_explain_cc_hub_dir() -> None:
    cc_connect_text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    assert "CC_HUB_DIR" in cc_connect_text
    assert "CC_HUB_DIR" in (ROOT / "docs" / "install.md").read_text(encoding="utf-8")


def test_changelog_records_known_limitations() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "### Known limitations" in text
    assert "Codex hook payload" in text
    assert "windows-latest" in text


def test_every_python_file_declares_utf8() -> None:
    for path in sorted(ROOT.glob("src/**/*.py")) + sorted(ROOT.glob("tests/**/*.py")):
        first = path.read_text(encoding="utf-8").splitlines()[:1]
        assert first == ["# -*- coding: utf-8 -*-"], path
