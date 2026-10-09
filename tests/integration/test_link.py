# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.link import inspect_skill_links, sync_skill_links
from cc_hub.platform import LinkError, is_link, is_windows, link_dir

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
