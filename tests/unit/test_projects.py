# -*- coding: utf-8 -*-
import json
import tomllib
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.projects import (
    ProjectError,
    add_project,
    get_project,
    load_projects,
    portable_path,
    remove_project,
)


def test_add_project_writes_entry(hub: Path, tmp_path: Path) -> None:
    proj = tmp_path / "dev" / "UnifX 项目"
    proj.mkdir(parents=True)
    entry = add_project(
        hub,
        proj,
        description="sim",
        notes="uv run pytest",
        today=date(2026, 9, 22),
        home=tmp_path / "nohome",
    )
    assert entry["name"] == "UnifX 项目"
    assert entry["path"] == str(proj.resolve())
    data = tomllib.loads((hub / "projects.toml").read_text(encoding="utf-8"))
    assert data["project"][0]["notes"] == "uv run pytest"
    assert data["project"][0]["added"] == date(2026, 9, 22)
    assert load_projects(hub) == [entry]


def test_portable_path_uses_tilde_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "dev" / "x").mkdir(parents=True)
    assert portable_path(home / "dev" / "x", home=home) == "~/dev/x"
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert portable_path(other, home=home) == str(other.resolve())


def test_add_rejects_missing_dir_duplicates_and_name_clash(hub: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    add_project(hub, a, home=tmp_path / "nohome")
    with pytest.raises(ProjectError):
        add_project(hub, tmp_path / "missing", home=tmp_path / "nohome")
    with pytest.raises(ProjectError):
        add_project(hub, a, home=tmp_path / "nohome")
    b = tmp_path / "b"
    b.mkdir()
    with pytest.raises(ProjectError):
        add_project(hub, b, name="a", home=tmp_path / "nohome")


def test_remove_and_get(hub: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    add_project(hub, a, home=tmp_path / "nohome")
    assert get_project(hub, "a")["name"] == "a"
    removed = remove_project(hub, "a")
    assert removed["name"] == "a"
    assert load_projects(hub) == []
    with pytest.raises(ProjectError):
        remove_project(hub, "a")
    with pytest.raises(ProjectError):
        get_project(hub, "a")


def test_projects_cli(hub: Path, tmp_path: Path) -> None:
    a = tmp_path / "proj-a"
    a.mkdir()
    runner = CliRunner()
    r = runner.invoke(app, ["--hub", str(hub), "projects", "add", str(a), "--description", "demo"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list", "--json"])
    assert json.loads(r.output)[0]["name"] == "proj-a"
    r = runner.invoke(app, ["--hub", str(hub), "projects", "show", "proj-a"])
    assert "demo" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "remove", "proj-a"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list"])
    assert "no projects" in r.output
