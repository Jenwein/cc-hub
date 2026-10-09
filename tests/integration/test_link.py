# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.link import inspect_skill_links, sync_skill_links
from cc_hub.platform import LinkError, is_link, is_windows, link_dir, remove_link

BUILT_IN = ["hub-adapt", "hub-memory"]


def add_skill(hub: Path, name: str) -> Path:
    skill = hub / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    return skill


def test_link_creates_one_directory_link_per_skill(hub: Path) -> None:
    target = hub / ".claude" / "skills"
    assert sync_skill_links(hub, target) == [(name, "linked") for name in BUILT_IN]
    for name in BUILT_IN:
        entry = target / name
        assert is_link(entry), name
        assert entry.resolve() == (hub / "skills" / name).resolve()
        assert (entry / "SKILL.md").read_text(encoding="utf-8") == (
            hub / "skills" / name / "SKILL.md"
        ).read_text(encoding="utf-8")


def test_link_is_idempotent(hub: Path) -> None:
    target = hub / ".agents" / "skills"
    sync_skill_links(hub, target)
    assert sync_skill_links(hub, target) == [(name, "existing") for name in BUILT_IN]


def test_link_adds_new_skills_and_removes_links_to_deleted_ones(hub: Path) -> None:
    target = hub / ".claude" / "skills"
    sync_skill_links(hub, target)
    mine = add_skill(hub, "mine")
    assert ("mine", "linked") in sync_skill_links(hub, target)
    shutil.rmtree(mine)
    assert ("mine", "removed") in sync_skill_links(hub, target)
    assert not os.path.lexists(target / "mine")


def test_link_skips_directories_without_skill_md(hub: Path) -> None:
    (hub / "skills" / "notes").mkdir()
    target = hub / ".claude" / "skills"
    assert [name for name, _ in sync_skill_links(hub, target)] == BUILT_IN
    assert not os.path.lexists(target / "notes")


def test_link_leaves_other_entries_alone(hub: Path) -> None:
    target = hub / ".claude" / "skills"
    (target / "hub-memory").mkdir(parents=True)
    (target / "hub-memory" / "SKILL.md").write_text("an old copy", encoding="utf-8")
    (target / "claude-only").mkdir()
    results = dict(sync_skill_links(hub, target))
    assert results == {"hub-adapt": "linked", "hub-memory": "blocked"}
    assert (target / "hub-memory" / "SKILL.md").read_text(encoding="utf-8") == "an old copy"
    assert (target / "claude-only").is_dir()
    state = inspect_skill_links(hub, target)
    assert state.blocked == ["hub-memory"] and state.missing == [] and state.dangling == []


def test_link_accepts_a_target_that_already_reaches_the_whole_skills_directory(
    hub: Path,
) -> None:
    target = hub / ".claude" / "skills"
    link_dir(hub / "skills", target)
    assert sync_skill_links(hub, target) == [(name, "existing") for name in BUILT_IN]


@pytest.mark.skipif(is_windows(), reason="POSIX symlinks")
def test_link_dir_makes_a_symlink_on_posix(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    assert link_dir(src, tmp_path / "a" / "dst") == "symlink"
    assert (tmp_path / "a" / "dst").is_symlink()


def test_link_dir_reports_a_failed_junction(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()

    def failing_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    with pytest.raises(LinkError):
        link_dir(src, tmp_path / "dst", windows=True, run=failing_run)
    assert not os.path.lexists(tmp_path / "dst")


def test_link_dir_refuses_an_existing_destination(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "dst").mkdir()
    with pytest.raises(LinkError):
        link_dir(src, tmp_path / "dst")


def test_link_cli_resolves_relative_to_hub(hub: Path) -> None:
    result = CliRunner().invoke(app, ["--hub", str(hub), "link", ".claude/skills"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [f"linked\t{name}" for name in BUILT_IN]
    assert (hub / ".claude" / "skills" / "hub-memory" / "SKILL.md").is_file()


def test_link_cli_fails_when_a_skill_is_blocked(hub: Path) -> None:
    (hub / ".claude" / "skills" / "hub-memory").mkdir(parents=True)
    result = CliRunner().invoke(app, ["--hub", str(hub), "link", ".claude/skills"])
    assert result.exit_code == 1
    assert "blocked\thub-memory" in result.output


def install_fake_app(hub: Path, app: str, skill: str) -> Path:
    """An app directory and its apps.lock entry, without going through `cc-hub app`."""
    from cc_hub.applock import load_lock, save_lock

    skill_dir = hub / "apps" / app / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    lock = load_lock(hub)
    lock.apps[app] = {"tap": "t", "commit": "0" * 40, "version": "0.1.0"}
    save_lock(hub, lock)
    return hub / "apps" / app


def test_link_includes_the_skills_of_installed_apps(hub: Path) -> None:
    install_fake_app(hub, "ledger", "ledger")
    target = hub / ".claude" / "skills"
    assert ("ledger", "linked") in sync_skill_links(hub, target)
    assert (target / "ledger" / "SKILL.md").is_file()


def test_link_ignores_app_directories_missing_from_apps_lock(hub: Path) -> None:
    stray = hub / "apps" / "stray" / "skills" / "stray"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("---\nname: stray\n---\n", encoding="utf-8")
    assert "stray" not in dict(sync_skill_links(hub, hub / ".claude" / "skills"))


def test_link_removes_links_to_a_removed_app(hub: Path) -> None:
    from cc_hub.applock import load_lock, save_lock
    from cc_hub.platform import rmtree

    app = install_fake_app(hub, "ledger", "ledger")
    target = hub / ".claude" / "skills"
    sync_skill_links(hub, target)
    rmtree(app)
    lock = load_lock(hub)
    del lock.apps["ledger"]
    save_lock(hub, lock)
    assert ("ledger", "removed") in sync_skill_links(hub, target)
    assert not os.path.lexists(target / "ledger")


def test_link_follows_an_app_that_is_itself_a_link(hub: Path, tmp_path: Path) -> None:
    from cc_hub.applock import load_lock, save_lock

    dev = tmp_path / "dev" / "notes"
    (dev / "skills" / "notes").mkdir(parents=True)
    (dev / "skills" / "notes" / "SKILL.md").write_text("---\nname: notes\n---\n", encoding="utf-8")
    link_dir(dev, hub / "apps" / "notes")
    lock = load_lock(hub)
    lock.apps["notes"] = {"link": str(dev), "version": "0.1.0"}
    save_lock(hub, lock)
    target = hub / ".claude" / "skills"
    assert ("notes", "linked") in sync_skill_links(hub, target)
    assert ("notes", "existing") in sync_skill_links(hub, target)
    remove_link(hub / "apps" / "notes")
    del lock.apps["notes"]
    save_lock(hub, lock)
    assert ("notes", "removed") in sync_skill_links(hub, target)
