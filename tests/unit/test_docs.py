# -*- coding: utf-8 -*-
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE_ROW = re.compile(r"^\| `cc-hub ([a-z-]+)", re.M)


def _command_names() -> set[str]:
    from cc_hub.cli import app

    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    return names | {g.name for g in app.registered_groups}


def test_readme_command_tables_match_the_cli() -> None:
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert set(TABLE_ROW.findall(readme)) == _command_names(), name


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
