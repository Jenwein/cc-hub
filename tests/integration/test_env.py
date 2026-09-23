# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands import env as envmod

FAKE_WHICH = lambda name: f"/fake/bin/{name}" if name in ("git", "uv", "cc-hub", "bash") else None  # noqa: E731
FAKE_DAEMON = lambda name: f"/usr/bin/{name}" if name == "git" else None  # noqa: E731
FAKE_VERSION = lambda exe: "1.2.3" if exe else ""  # noqa: E731


def test_probe_has_all_sections(hub: Path, tmp_path: Path) -> None:
    data = envmod.probe(
        hub, tools=["git", "uv", "node"], home=tmp_path / "home",
        which=FAKE_WHICH, which_daemon=FAKE_DAEMON, version_of=FAKE_VERSION,
        now=datetime(2026, 9, 22, 10, 0, 0),
    )
    expected_keys = {
        "generated_at", "hub", "system", "shells", "tools",
        "agents", "paths", "resources"
    }
    assert set(data) >= expected_keys
    assert data["tools"]["git"] == {"path": "/fake/bin/git", "version": "1.2.3"}
    assert data["tools"]["node"] == {"path": None, "version": ""}
    assert data["paths"]["cc-hub"] == {"path": "/fake/bin/cc-hub", "daemon_visible": False}
    assert data["paths"]["codex"] == {"path": None, "daemon_visible": False}
    assert data["shells"]["bash"] == "/fake/bin/bash"
    assert "default" in data["shells"]
    assert data["generated_at"].startswith("2026-09-22T10:00:00")
    assert data["resources"]["cpus"] >= 1
    assert data["agents"]["claude_home"] is False


def test_render_env_md_lists_sections_and_absolute_paths(
    hub: Path, tmp_path: Path
) -> None:
    data = envmod.probe(
        hub, tools=["git"], home=tmp_path / "home", which=FAKE_WHICH,
        which_daemon=FAKE_DAEMON, version_of=FAKE_VERSION
    )
    md = envmod.render_env_md(data)
    sections = (
        "## System", "## Shell", "## Tools",
        "## Agents & bridge", "## Paths", "## Resources"
    )
    for section in sections:
        assert section in md
    assert "/fake/bin/cc-hub" in md
    assert "not visible to daemons" in md


def test_write_env_creates_both_files(hub: Path, tmp_path: Path) -> None:
    envmod.write_env(hub, tools=["git"], home=tmp_path / "home", which=FAKE_WHICH,
                     which_daemon=FAKE_DAEMON, version_of=FAKE_VERSION)
    assert (hub / "ENV.md").is_file()
    data = json.loads((hub / "env.json").read_text(encoding="utf-8"))
    assert data["hub"] == str(hub)


def test_version_of_handles_missing_binary() -> None:
    assert envmod.version_of("/definitely/not/here") == ""


def test_probe_resolves_python_alias_to_python3(hub: Path, tmp_path: Path) -> None:
    which = lambda name: "/fake/bin/python3" if name == "python3" else None  # noqa: E731
    data = envmod.probe(
        hub, tools=["python"], home=tmp_path / "home", which=which,
        which_daemon=FAKE_DAEMON, version_of=FAKE_VERSION,
    )
    assert data["paths"]["python"]["path"] == "/fake/bin/python3"
    assert data["tools"]["python"]["path"] == "/fake/bin/python3"


def test_env_cli_json(hub: Path) -> None:
    result = CliRunner().invoke(app, ["--hub", str(hub), "env", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["hub"] == str(hub)
    assert (hub / "ENV.md").is_file()
