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
    r = runner.invoke(
        app,
        ["--hub", str(hub), "projects", "add", str(a), "--description", "demo"],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list", "--json"])
    assert json.loads(r.output)[0]["name"] == "proj-a"
    r = runner.invoke(app, ["--hub", str(hub), "projects", "show", "proj-a"])
    assert "demo" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "remove", "proj-a"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list"])
    assert "no projects" in r.output


def test_duplicate_check_uses_injected_home(hub: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "dev" / "x").mkdir(parents=True)
    entry = add_project(hub, home / "dev" / "x", home=home)
    assert entry["path"] == "~/dev/x"
    assert load_projects(hub)[0]["path"] == "~/dev/x"
    with pytest.raises(ProjectError):
        add_project(hub, home / "dev" / "x", home=home)


def test_projects_cli_errors_exit_1(hub: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["--hub", str(hub), "projects", "add", str(tmp_path / "missing")],
    )
    assert r.exit_code == 1
    assert "not a directory" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "show", "nope"])
    assert r.exit_code == 1
    r = runner.invoke(app, ["--hub", str(hub), "projects", "remove", "nope"])
    assert r.exit_code == 1


def test_list_and_show_print_absolute_paths(hub: Path, tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / "dev" / "x").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    (hub / "projects.toml").write_text(
        '[[project]]\nname = "x"\npath = "~/dev/x"\n', encoding="utf-8"
    )
    absolute = str((home / "dev" / "x").resolve())
    runner = CliRunner()
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list"])
    assert r.exit_code == 0 and absolute in r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "show", "x"])
    assert f"path: {absolute}" in r.output
    assert "resolved" not in r.output
    r = runner.invoke(app, ["--hub", str(hub), "projects", "list", "--json"])
    entry = json.loads(r.output)[0]
    assert entry["path"] == "~/dev/x" and entry["resolved"] == absolute
