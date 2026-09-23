# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.platform import COPY_MARKER, LinkError, is_windows, link_dir


def make_src(tmp_path: Path) -> Path:
    src = tmp_path / "skills"
    (src / "hub-x").mkdir(parents=True)
    (src / "hub-x" / "SKILL.md").write_text("---\nname: hub-x\n---\n", encoding="utf-8")
    return src


@pytest.mark.skipif(is_windows(), reason="symlink path is unix-only")
def test_symlink_on_unix_and_existing_on_rerun(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    dst = tmp_path / ".claude" / "skills"
    assert link_dir(src, dst) == "symlink"
    assert dst.is_symlink() and (dst / "hub-x" / "SKILL.md").is_file()
    assert link_dir(src, dst) == "existing"


def test_copy_fallback_when_junction_fails(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    dst = tmp_path / ".agents" / "skills"

    def failing_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    assert link_dir(src, dst, windows=True, run=failing_run) == "copy"
    assert (dst / "hub-x" / "SKILL.md").is_file()
    assert (dst / COPY_MARKER).is_file()
    # a second run refreshes the copy instead of failing
    (src / "hub-x" / "SKILL.md").write_text("changed", encoding="utf-8")
    assert link_dir(src, dst, windows=True, run=failing_run) == "copy"
    assert (dst / "hub-x" / "SKILL.md").read_text(encoding="utf-8") == "changed"


def test_refuses_to_replace_foreign_directory(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    dst = tmp_path / "foreign"
    (dst / "keep").mkdir(parents=True)
    with pytest.raises(LinkError):
        link_dir(src, dst, windows=True, run=lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert (dst / "keep").is_dir()


def test_missing_source_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LinkError):
        link_dir(tmp_path / "nope", tmp_path / "dst")


def test_link_cli_resolves_relative_to_hub(hub: Path) -> None:
    result = CliRunner().invoke(app, ["--hub", str(hub), "link", "skills", ".claude/skills"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() in {"symlink", "junction", "copy"}
    assert (hub / ".claude" / "skills" / "hub-memory" / "SKILL.md").is_file()
