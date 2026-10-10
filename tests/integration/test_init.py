# -*- coding: utf-8 -*-
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub import __version__, manifest
from cc_hub.cli import app
from cc_hub.commands.init import NestedGitError, enclosing_git_repo, init_hub
from cc_hub.encoding import read_text
from cc_hub.hub import load_config


def test_init_creates_all_templates_and_dirs(tmp_path: Path) -> None:
    result = init_hub(tmp_path / "h", git=False)
    assert set(result.created) == set(manifest.all_templates())
    assert result.skipped == []
    for rel in manifest.all_templates():
        assert (tmp_path / "h" / rel).is_file(), rel
    for d in manifest.USER_DIRS:
        assert (tmp_path / "h" / d).is_dir(), d
    cfg = load_config(tmp_path / "h")
    assert cfg["hub"]["template_version"] == __version__
    assert cfg["hub"]["name"] == "h"


def test_init_keeps_existing_files(tmp_path: Path) -> None:
    h = tmp_path / "h"
    init_hub(h, git=False)
    (h / "SOUL.md").write_text("mine", encoding="utf-8")
    result = init_hub(h, git=False)
    assert result.created == []
    assert "SOUL.md" in result.skipped
    assert read_text(h / "SOUL.md") == "mine"


def test_init_refuses_target_inside_git_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(NestedGitError):
        init_hub(tmp_path / "h", git=False)
    assert enclosing_git_repo(tmp_path / "deeper" / "still") == tmp_path.resolve()


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def test_init_runs_git_init_and_commits(tmp_path: Path, git_env: Path) -> None:
    target = tmp_path / "中文 hub"
    result = init_hub(target, git=True)
    assert result.git_initialized and result.committed
    assert result.git_warning is None
    assert _git(target, "log", "--format=%s").strip() == "cc-hub: init"
    tracked = set(_git(target, "ls-files").split("\n"))
    assert {
        "AGENTS.md", "hub.toml", ".gitignore", ".gitattributes", "skills/hub-adapt/SKILL.md",
    } <= tracked


def test_init_sets_a_local_identity_only_when_git_has_none(
    tmp_path: Path, git_env: Path
) -> None:
    init_hub(tmp_path / "with", git=True)
    assert _git(tmp_path / "with", "config", "--local", "--list").count("user.") == 0
    git_env.write_text("", encoding="utf-8")
    init_hub(tmp_path / "without", git=True)
    local = _git(tmp_path / "without", "config", "--local", "--list")
    assert "user.name=without (cc-hub)" in local
    assert "user.email=hub@cc-hub.invalid" in local


def test_init_rerun_commits_only_the_files_it_created(tmp_path: Path, git_env: Path) -> None:
    target = tmp_path / "h"
    init_hub(target, git=True)
    (target / "SOUL.md").unlink()
    _git(target, "commit", "-qam", "drop SOUL.md")
    (target / "MEMORY.md").write_text("mine, not committed", encoding="utf-8")
    result = init_hub(target, git=True)
    assert result.created == ["SOUL.md"]
    assert _git(target, "show", "--name-only", "--format=", "HEAD").split() == ["SOUL.md"]
    assert "MEMORY.md" in _git(target, "status", "--porcelain")


def test_init_cli_prints_table_and_next_steps(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", str(tmp_path / "h"), "--no-git"])
    assert result.exit_code == 0, result.output
    assert "AGENTS.md" in result.output
    assert "work_dir" in result.output


def test_init_cli_reports_nested_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = CliRunner().invoke(app, ["init", str(tmp_path / "h"), "--no-git"])
    assert result.exit_code == 1


def test_init_refuses_an_existing_repo_root_that_is_not_a_hub(tmp_path: Path) -> None:
    target = tmp_path / "h"
    (target / ".git").mkdir(parents=True)
    with pytest.raises(NestedGitError):
        init_hub(target, git=False)
    assert not (target / "hub.toml").exists()


def test_init_reruns_inside_an_existing_hub_repo(tmp_path: Path) -> None:
    target = tmp_path / "h"
    init_hub(target, git=False)
    (target / ".git").mkdir()
    result = init_hub(target, git=False)
    assert result.created == []
    assert "hub.toml" in result.skipped


def test_init_cli_explains_cc_hub_dir_for_a_non_default_hub(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", str(tmp_path / "h"), "--no-git"])
    assert result.exit_code == 0, result.output
    assert "CC_HUB_DIR" in result.output
    assert "projects.agent.options.env" in result.output
