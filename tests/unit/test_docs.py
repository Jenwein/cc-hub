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


DOCS = ("install.md", "cc-connect.md", "windows.md", "acceptance.md", "backup.md", "apps.md")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def test_docs_exist_and_are_utf8_lf() -> None:
    for name in DOCS:
        raw = (ROOT / "docs" / name).read_bytes()
        assert raw and b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf"), name
    cc_connect_text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    assert "projects.agent.options.env" in cc_connect_text
    assert "## 0.1.0" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_relative_links_resolve() -> None:
    pages = [ROOT / "README.md", ROOT / "README.zh-CN.md"]
    pages += [ROOT / "docs" / name for name in DOCS]
    for page in pages:
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            assert (page.parent / target).exists(), (page.name, target)


def test_cc_connect_doc_explains_the_instructions_block() -> None:
    from cc_hub.commands.update import CC_CONNECT_MARKER

    text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    assert "/cron setup" in text
    assert CC_CONNECT_MARKER in text


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


def test_backup_doc_covers_a_private_remote() -> None:
    text = (ROOT / "docs" / "backup.md").read_text(encoding="utf-8")
    for phrase in ("private", "deploy key", "git -C ~/.cc-hub remote add origin", "rejected"):
        assert phrase in text, phrase
    assert "backup.md" in (ROOT / "docs" / "install.md").read_text(encoding="utf-8")


def test_apps_doc_covers_writing_and_publishing() -> None:
    text = (ROOT / "docs" / "apps.md").read_text(encoding="utf-8")
    for phrase in ("app.toml", "SETUP.md", "--link", "cc-hub-tap", "cc-hub tap add",
                   "cc-hub app install", "--yes"):
        assert phrase in text, phrase
    assert "cc-hub app sync" in (ROOT / "docs" / "backup.md").read_text(encoding="utf-8")
    for readme in ("README.md", "README.zh-CN.md"):
        assert "apps.lock" in (ROOT / readme).read_text(encoding="utf-8"), readme
