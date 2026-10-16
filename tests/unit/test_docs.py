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


def test_cc_connect_doc_registers_pointer_prompts() -> None:
    text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    section = text.split("## Scheduled tasks", 1)[1].split("\n## ", 1)[0]
    for phrase in ("cc-hub cron list --json", "hub:<name>", "Scheduled task hub:memory-consolidate",
                   "cc-hub cron set", "cc-hub cron reset"):
        assert phrase in section, phrase
    assert '--prompt "<body>"' not in text


def test_changelog_has_0_6_0() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## 0.6.0", 1)[1].split("\n## ", 1)[0]
    removed = section.split("### Removed", 1)[1].split("\n### ", 1)[0]
    for phrase in ("cc-hub cron wake", "cc-hub cron guard-setup", "`exec`", "`on_demand`",
                   "`allow`", "`silent`", "AGENTS.md"):
        assert phrase in removed, phrase
    assert "## 0.5.0" in text  # the earlier entry stays as it was


def test_readmes_explain_the_cron_examples() -> None:
    examples = (
        'cc-hub cron set plans/morning "0 7 * * *"',
        "cc-hub cron set ledger/prices --off",
        "cc-hub cron reset plans/morning",
    )
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert "| `cc-hub cron list\\|set\\|reset` |" in readme, name
        for example in examples:
            assert example in readme, (name, example)
        assert "`<…>`" in readme and "`[…]`" in readme, name


def test_apps_doc_covers_scheduled_tasks() -> None:
    text = (ROOT / "docs" / "apps.md").read_text(encoding="utf-8")
    for phrase in ("schedule:", "default:", "session:", "hub:<app>/<task>", "cc-hub cron set",
                   "cc-hub cron reset", "cc-hub cron list"):
        assert phrase in text, phrase


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
    assert "cc-hub app update <app>" in text
    backup = (ROOT / "docs" / "backup.md").read_text(encoding="utf-8")
    assert "cc-hub app sync" in backup
    restore = backup.split("## Restore on another machine", 1)[1].split("\n## ", 1)[0]
    assert "core.sshCommand" in restore
    # the clone itself needs the key, so the key goes into the clone command
    assert 'git clone -c core.sshCommand="ssh -i ~/.ssh/cc-hub-backup' in restore
    assert "repository-local git identity" in restore
    for readme in ("README.md", "README.zh-CN.md"):
        assert "apps.lock" in (ROOT / readme).read_text(encoding="utf-8"), readme


def test_readmes_explain_the_report_examples() -> None:
    examples = (
        "cc-hub cron set report-daily --on",
        'cc-hub cron set report-weekly "0 20 * * 5"',
        "cc-hub report language zh-CN",
        "cc-hub report section ledger monthly --off",
    )
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        subcommands = "list|plan|put|send|note|section|language|approve".replace("|", "\\|")
        assert f"| `cc-hub report {subcommands}` |" in readme, name
        lines = [line.strip() for line in readme.splitlines()]
        for example in examples:
            found = [line for line in lines if line.startswith(example)]
            assert found, (name, example)
            assert " # " in found[0], (name, example)  # each example says what it does
        assert "reports/" in readme, name


def _section(text: str, heading: str) -> str:
    return " ".join(text.split(heading, 1)[1].split("\n## ", 1)[0].split())


def test_apps_doc_covers_reports() -> None:
    from cc_hub import manifest

    section = _section((ROOT / "docs" / "apps.md").read_text(encoding="utf-8"), "\n## Reports")
    for phrase in ("`reports/<period>.md`", "`command`", "`title`", "forward slashes",
                   "`CC_HUB_DIR`", "`CC_HUB_REPORT_PERIOD`", "`CC_HUB_REPORT_SINCE`",
                   "`CC_HUB_REPORT_UNTIL`", "`CC_HUB_LANGUAGE`", "cc-hub report note",
                   "once the user has approved it on that machine",
                   "Empty output means no section", 'min_hub = "0.7.0"'):
        assert phrase in section, phrase
    # the command rules are the same in the guide the agent reads
    authoring = _section(manifest.render("skills/hub-apps/authoring.md"), "\n## Reports")
    for text in (section, authoring):
        for phrase in ("not run through a shell", "no pipes", "`$VAR`", "in double quotes if it",
                       "starts a comment", "20000 characters", "300 seconds"):
            assert phrase in text, phrase
    apps_doc = (ROOT / "docs" / "apps.md").read_text(encoding="utf-8")
    assert "reports/<period>.md" in apps_doc.split("## Write an app", 1)[1].split("\n## ", 1)[0]
    assert "never runs anything an app provides" not in apps_doc  # report commands: an exception


def test_cc_connect_doc_covers_reports() -> None:
    text = (ROOT / "docs" / "cc-connect.md").read_text(encoding="utf-8")
    section = _section(text, "\n## Reports")
    for phrase in ("cc-connect send -p <project> -s <session> --stdin", "CC_PROJECT",
                   "CC_SESSION_KEY", "PATH", "--silent", "NO_REPLY", "approved"):
        assert phrase in section, phrase
    registrations = [ln for ln in text.splitlines() if ln.strip().startswith("cc-connect cron add")]
    assert registrations and all(ln.endswith(" --silent") for ln in registrations)


def test_changelog_has_0_7_0() -> None:
    from cc_hub import __version__

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.split("\n## ", 1)[1].startswith(__version__)  # the newest entry is this version
    section = text.split("## 0.7.0", 1)[1].split("\n## ", 1)[0]
    parts = {name: " ".join(body.split())
             for name, body in (p.split("\n", 1) for p in section.split("\n### ")[1:])}
    assert list(parts) == ["Added", "Changed", "Migration notes"]
    for phrase in ("cc-hub report", "report-daily", "reports/<period>.md", "min_hub",
                   "`doctor` check `reports`"):
        assert phrase in parts["Added"], phrase
    for phrase in ("--silent", "memory-consolidate", "fingerprint", "reserved", "`app install`",
                   "`app update`", "`app remove`", "`--yes` drops", "approvals"):
        assert phrase in parts["Changed"], phrase
    for phrase in ("cc-hub update", "hub-adapt", "Nothing changes until"):
        assert phrase in parts["Migration notes"], phrase
    assert "## 0.6.0" in text  # the earlier entry stays as it was


def test_design_spec_states_the_report_exceptions() -> None:
    spec = (ROOT / "docs" / "superpowers" / "specs" / "2026-09-22-cc-hub-design.md").read_text(
        encoding="utf-8"
    )
    assert (ROOT / "docs" / "superpowers" / "specs" / "2026-10-16-reports-design.md").is_file()
    assert "2026-10-16-reports-design.md" in spec
    lines = spec.splitlines()
    for principle, exception in (("只搬文件，不执行", "批准"),
                                 ("从不执行应用提供的字符串", "报告"),
                                 ("自己不调用 cc-connect", "cc-connect send")):
        found = [ln for ln in lines if principle in ln]
        assert found and all(exception in ln for ln in found), principle
    assert "--silent" in spec
    assert "├── reports/" in spec  # in the hub layout
    assert "| reports |" in spec  # in the doctor table
    assert "`reports`" in spec.split("**数据目录**", 1)[1].split("\n", 1)[0]  # a reserved name
    assert "report list|plan|put|send|note|section|language|approve" in spec
