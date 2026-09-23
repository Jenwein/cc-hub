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
    del cfg["hooks"]
    save_config(hub, cfg)
    result = update_hub(hub, version="9.9.9")
    assert result.config_changed
    new = load_config(hub)
    assert new["memory"]["max_lines"] == 123
    assert new["hooks"]["blocklist_extra"] == []
    assert new["hub"]["template_version"] == "9.9.9"


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
