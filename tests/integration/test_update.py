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
        "extra": {"items": []},
    }
    merged = merge_defaults(current, defaults)
    assert merged["memory"] == {"max_lines": 123, "recent_days": 2}
    assert merged["hub"] == {"name": "x", "template_version": "1"}
    assert merged["extra"] == {"items": []}
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
    del cfg["memory"]["recent_days"]
    save_config(hub, cfg)
    result = update_hub(hub, version="9.9.9")
    assert result.config_changed
    new = load_config(hub)
    assert new["memory"] == {"max_lines": 123, "recent_days": 2}
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


def test_update_adds_a_missing_table(hub: Path) -> None:
    import tomllib

    text = read_text(hub / "hub.toml")
    start = text.index("[memory]")
    (hub / "hub.toml").write_text("# my hub\n" + text[:start], encoding="utf-8")
    update_hub(hub, version="9.9.9")
    new = read_text(hub / "hub.toml")
    assert new.startswith("# my hub\n")
    assert tomllib.loads(new)["memory"] == {"max_lines": 200, "recent_days": 2}


CC_BLOCK = "\n<!-- cc-connect-instructions -->\nYou are running inside cc-connect.\n"


def test_update_keeps_what_follows_the_tail_marker(hub: Path) -> None:
    agents = hub / "AGENTS.md"
    original = "stale framework line\n" + read_text(agents) + CC_BLOCK + "\n- my note\n"
    agents.write_text(original, encoding="utf-8")
    result = update_hub(hub, version="9.9.9")
    assert "AGENTS.md" in result.updated
    expected = manifest.render("AGENTS.md", name="hub", version="9.9.9")
    assert read_text(agents) == expected + CC_BLOCK + "\n- my note\n"
    assert read_text(hub / ".cc-hub" / "backups" / __version__ / "AGENTS.md") == original


def test_update_leaves_agents_md_alone_when_only_the_tail_was_added(hub: Path) -> None:
    agents = hub / "AGENTS.md"
    agents.write_text(read_text(agents) + CC_BLOCK, encoding="utf-8", newline="\n")
    result = update_hub(hub)
    assert "AGENTS.md" in result.skipped
    assert read_text(agents).endswith(CC_BLOCK)


def test_update_keeps_the_cc_connect_block_when_the_tail_marker_is_missing(hub: Path) -> None:
    agents = hub / "AGENTS.md"
    agents.write_text("# Older instructions\n" + CC_BLOCK, encoding="utf-8")
    update_hub(hub, version="9.9.9")
    expected = manifest.render("AGENTS.md", name="hub", version="9.9.9") + CC_BLOCK
    assert read_text(agents) == expected


def test_update_removes_every_retired_file(hub: Path) -> None:
    for rel in manifest.RETIRED:
        path = hub / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"old {rel}", encoding="utf-8")
    result = update_hub(hub, version="9.9.9")
    assert result.retired == list(manifest.RETIRED)
    backups = hub / ".cc-hub" / "backups" / __version__
    for rel in manifest.RETIRED:
        assert not (hub / rel).exists(), rel
        assert read_text(backups / rel) == f"old {rel}"


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def test_update_commits_only_what_it_changed(git_hub: Path) -> None:
    (git_hub / "AGENTS.md").write_text("custom agents", encoding="utf-8")
    _git(git_hub, "commit", "-qam", "user edit")
    (git_hub / "SOUL.md").write_text("draft soul", encoding="utf-8")
    result = update_hub(git_hub, version="9.9.9")
    assert result.git_warning is None
    assert _git(git_hub, "log", "-1", "--format=%s").strip() == (
        f"cc-hub: update {__version__} -> 9.9.9"
    )
    committed = set(_git(git_hub, "show", "--name-only", "--format=", "HEAD").split())
    assert committed == {"AGENTS.md", "hub.toml"}
    assert " M SOUL.md" in _git(git_hub, "status", "--porcelain")


def test_update_makes_the_first_commit_of_a_hub_without_one(hub: Path, git_env: Path) -> None:
    _git(hub, "init", "-q")
    update_hub(hub, version="9.9.9")
    assert _git(hub, "log", "--format=%s").split("\n")[:2] == [
        "cc-hub: update " + __version__ + " -> 9.9.9",
        "cc-hub: init",
    ]


def test_update_sets_an_identity_when_git_has_none(hub: Path, git_env: Path) -> None:
    git_env.write_text("", encoding="utf-8")
    _git(hub, "init", "-q")
    result = update_hub(hub, version="9.9.9")
    assert result.git_warning is None
    assert _git(hub, "log", "--format=%s").split("\n")[:2] == [
        "cc-hub: update " + __version__ + " -> 9.9.9",
        "cc-hub: init",
    ]
    assert _git(hub, "config", "--local", "user.email").strip() == "hub@cc-hub.invalid"


def test_update_dry_run_does_not_commit(git_hub: Path) -> None:
    before = _git(git_hub, "rev-parse", "HEAD")
    update_hub(git_hub, version="9.9.9", dry_run=True)
    assert _git(git_hub, "rev-parse", "HEAD") == before


def test_a_clone_with_autocrlf_keeps_lf_line_endings(git_hub: Path, tmp_path: Path) -> None:
    import subprocess

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "-c", "core.autocrlf=true", str(git_hub), str(clone)], check=True
    )
    for rel in ("AGENTS.md", "skills/hub-apps/SKILL.md", "hub.toml"):
        assert b"\r\n" not in (clone / rel).read_bytes(), rel


def test_update_adds_and_commits_a_missing_gitattributes(git_hub: Path) -> None:
    (git_hub / ".gitattributes").unlink()
    _git(git_hub, "commit", "-qam", "drop .gitattributes")
    result = update_hub(git_hub)
    assert result.updated == [".gitattributes"]
    assert (git_hub / ".gitattributes").read_bytes() == (
        b"# hub files keep the line endings they were written with\n* -text\n"
    )
    assert _git(git_hub, "show", "--name-only", "--format=", "HEAD").split() == [".gitattributes"]


def test_update_rewrites_framework_files_that_have_crlf_endings(hub: Path) -> None:
    rels = ("AGENTS.md", "skills/hub-apps/SKILL.md", ".gitignore")
    for rel in rels:
        path = hub / rel
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = update_hub(hub)
    assert set(rels) <= set(result.updated)
    backups = hub / ".cc-hub" / "backups" / __version__
    for rel in rels:
        assert b"\r" not in (hub / rel).read_bytes(), rel
        assert b"\r\n" in (backups / rel).read_bytes(), rel
    assert update_hub(hub).updated == []


def test_update_repairs_crlf_in_agents_md_and_keeps_its_tail(hub: Path) -> None:
    agents = hub / "AGENTS.md"
    mine = read_text(agents) + CC_BLOCK + "\n- my note\n"
    agents.write_bytes(mine.replace("\n", "\r\n").encode("utf-8"))
    result = update_hub(hub)
    assert "AGENTS.md" in result.updated
    assert agents.read_bytes() == (
        manifest.render("AGENTS.md", name="hub") + CC_BLOCK + "\n- my note\n"
    ).encode("utf-8")
