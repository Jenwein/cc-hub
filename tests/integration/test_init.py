# -*- coding: utf-8 -*-
import shutil
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
    for d in manifest.USER_DIRS + manifest.DERIVED_DIRS:
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


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_init_runs_git_init(tmp_path: Path) -> None:
    result = init_hub(tmp_path / "h", git=True)
    assert result.git_initialized
    assert (tmp_path / "h" / ".git").is_dir()


def test_init_cli_prints_table_and_next_steps(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", str(tmp_path / "h"), "--no-git"])
    assert result.exit_code == 0, result.output
    assert "AGENTS.md" in result.output
    assert "work_dir" in result.output


def test_init_cli_reports_nested_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = CliRunner().invoke(app, ["init", str(tmp_path / "h"), "--no-git"])
    assert result.exit_code == 1
