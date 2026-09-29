# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.hosts import load_hosts


@pytest.fixture
def hosts_hub(hub: Path) -> Path:
    (hub / "hosts.toml").write_text(
        '[[host]]\nname = "nas"\ntarget = "user@nas.local"\nport = 2222\nshell = "bash"\n',
        encoding="utf-8",
    )
    return hub


def test_hosts_list(hosts_hub: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hosts_hub), "hosts", "list"])
    assert r.exit_code == 0 and "nas" in r.output and "user@nas.local" in r.output
    r = CliRunner().invoke(app, ["--hub", str(hosts_hub), "hosts", "list", "--json"])
    assert json.loads(r.output)[0]["name"] == "nas"


def test_load_hosts_without_file_is_empty(tmp_path: Path) -> None:
    assert load_hosts(tmp_path) == []


def test_hosts_and_memory_keep_only_their_routing_commands() -> None:
    from cc_hub.commands.hosts import hosts_app
    from cc_hub.commands.memory import memory_app

    assert {c.name for c in hosts_app.registered_commands} == {"list"}
    assert {c.name for c in memory_app.registered_commands} == {"log", "search", "recent"}
