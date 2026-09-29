# -*- coding: utf-8 -*-
from pathlib import Path

from typer.testing import CliRunner

from cc_hub import __version__, manifest
from cc_hub.cli import app
from cc_hub.commands.update import merge_defaults, update_hub
from cc_hub.encoding import read_text
from cc_hub.hub import load_config, save_config


def test_merge_defaults_adds_missing_keys_only() -> None:
    current = {
        "hub": {"name": "x"},
        "memory": {"max_lines": 123},
    }
    defaults = {
        "hub": {"name": "hub", "template_version": "1"},
        "memory": {"max_lines": 200, "recent_days": 2},
        "env": {"tools": []},
    }
    merged = merge_defaults(current, defaults)
    assert merged["memory"] == {"max_lines": 123, "recent_days": 2}
    assert merged["hub"] == {"name": "x", "template_version": "1"}
    assert merged["env"] == {"tools": []}
    assert current["memory"] == {"max_lines": 123}


def test_update_overwrites_framework_files_and_backs_them_up(
    hub: Path,
) -> None:
    (hub / "AGENTS.md").write_text("custom agents", encoding="utf-8")
    (hub / "SOUL.md").write_text("my soul", encoding="utf-8")
    result = update_hub(hub, version="9.9.9")
    assert "AGENTS.md" in result.updated
    assert (
        read_text(hub / "AGENTS.md")
        == manifest.render("AGENTS.md", name="hub", version="9.9.9")
    )
    assert read_text(hub / "SOUL.md") == "my soul"
    backup = hub / ".cc-hub" / "backups" / __version__ / "AGENTS.md"
    assert read_text(backup) == "custom agents"
    assert result.backup_dir == backup.parent
    assert load_config(hub)["hub"]["template_version"] == "9.9.9"


def test_update_skips_unchanged_files(hub: Path) -> None:
    result = update_hub(hub)
    assert result.updated == []
    assert set(result.skipped) == set(manifest.FRAMEWORK_OWNED)
    assert result.backup_dir is None


def test_update_does_not_recreate_deleted_bootstrap(hub: Path) -> None:
    (hub / "BOOTSTRAP.md").unlink()
    result = update_hub(hub, version="9.9.9")
    assert not (hub / "BOOTSTRAP.md").exists()
    assert "BOOTSTRAP.md" in result.absent
    assert "BOOTSTRAP.md" not in result.skipped


def test_update_merges_hub_toml_keeping_user_values(hub: Path) -> None:
    cfg = load_config(hub)
    cfg["memory"]["max_lines"] = 123
    del cfg["env"]
    save_config(hub, cfg)
    result = update_hub(hub, version="9.9.9")
    assert result.config_changed
    new = load_config(hub)
    assert new["memory"]["max_lines"] == 123
    assert "claude" in new["env"]["tools"]
    assert new["hub"]["template_version"] == "9.9.9"


def _seed_retired_jobs_skill(hub: Path) -> Path:
    old = hub / "skills" / "hub-jobs" / "SKILL.md"
    old.parent.mkdir(parents=True)
    old.write_text("old jobs skill", encoding="utf-8")
    return old


def test_update_removes_retired_framework_files_after_backup(hub: Path) -> None:
    old = _seed_retired_jobs_skill(hub)
    result = update_hub(hub, version="9.9.9")
    assert result.retired == ["skills/hub-jobs/SKILL.md"]
    assert not old.exists()
    assert not old.parent.exists()
    backup = hub / ".cc-hub" / "backups" / __version__ / "skills" / "hub-jobs" / "SKILL.md"
    assert read_text(backup) == "old jobs skill"
    assert result.backup_dir == hub / ".cc-hub" / "backups" / __version__


def test_update_dry_run_reports_retired_files_without_removing(hub: Path) -> None:
    old = _seed_retired_jobs_skill(hub)
    result = update_hub(hub, dry_run=True, version="9.9.9")
    assert result.retired == ["skills/hub-jobs/SKILL.md"]
    assert old.is_file()


def test_update_keeps_user_files_next_to_a_retired_one(hub: Path) -> None:
    old = _seed_retired_jobs_skill(hub)
    mine = old.parent / "notes.md"
    mine.write_text("mine", encoding="utf-8")
    update_hub(hub, version="9.9.9")
    assert not old.exists()
    assert read_text(mine) == "mine"


def test_update_cli_lists_retired_files(hub: Path) -> None:
    _seed_retired_jobs_skill(hub)
    result = CliRunner().invoke(app, ["--hub", str(hub), "update"])
    assert result.exit_code == 0, result.output
    line = next(line for line in result.output.splitlines() if "hub-jobs" in line)
    assert "removed (retired)" in line


def test_dry_run_changes_nothing(hub: Path) -> None:
    (hub / "AGENTS.md").write_text("custom", encoding="utf-8")
    result = update_hub(hub, dry_run=True, version="9.9.9")
    assert "AGENTS.md" in result.updated
    assert read_text(hub / "AGENTS.md") == "custom"
    assert load_config(hub)["hub"]["template_version"] == __version__
    assert not (hub / ".cc-hub").exists()


def test_update_cli(hub: Path) -> None:
    (hub / "AGENTS.md").write_text("custom", encoding="utf-8")
    result = CliRunner().invoke(app, ["--hub", str(hub), "update"])
    assert result.exit_code == 0, result.output
    assert "AGENTS.md" in result.output


def test_update_cli_dry_run_reports_deleted_one_time_file_as_absent(hub: Path) -> None:
    (hub / "BOOTSTRAP.md").unlink()
    result = CliRunner().invoke(app, ["--hub", str(hub), "update", "--dry-run"])
    assert result.exit_code == 0, result.output
    line = next(line for line in result.output.splitlines() if "BOOTSTRAP.md" in line)
    assert "not present (one-time)" in line
    assert "unchanged" not in line


def test_update_edits_hub_toml_in_place(hub: Path) -> None:
    import tomllib

    text = read_text(hub / "hub.toml")
    text = text.replace("[memory]\n", "# tuned for a small model\n[memory]\n")
    text = text.replace("recent_days = 2\n", "")
    text = text.replace("max_lines = 200", "max_lines = 120  # keep it short")
    (hub / "hub.toml").write_text(text, encoding="utf-8")
    update_hub(hub, version="9.9.9")
    new = read_text(hub / "hub.toml")
    assert "# tuned for a small model\n[memory]\n" in new
    assert "max_lines = 120  # keep it short" in new
    data = tomllib.loads(new)
    assert data["memory"] == {"max_lines": 120, "recent_days": 2}
    assert data["hub"]["template_version"] == "9.9.9"
    tools_line = next(line for line in new.splitlines() if line.startswith("tools"))
    assert tools_line.endswith('"cc-connect"]')  # the one-line list is not reflowed


def test_update_adds_a_missing_table(hub: Path) -> None:
    import tomllib

    text = read_text(hub / "hub.toml")
    start = text.index("[env]")
    (hub / "hub.toml").write_text("# my hub\n" + text[:start], encoding="utf-8")
    update_hub(hub, version="9.9.9")
    new = read_text(hub / "hub.toml")
    assert new.startswith("# my hub\n")
    assert "claude" in tomllib.loads(new)["env"]["tools"]
