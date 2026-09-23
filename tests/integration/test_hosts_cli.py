# -*- coding: utf-8 -*-
import base64
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.platform import is_windows

FAKE_SSH = """#!/usr/bin/env python3
import json, sys
print(json.dumps(sys.argv[1:]))
"""


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("ssh", "scp"):
        exe = bin_dir / name
        exe.write_text(FAKE_SSH, encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


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


@pytest.mark.skipif(is_windows(), reason="fake ssh script needs a POSIX shebang")
def test_hosts_run_invokes_ssh_with_wrapped_command(hosts_hub: Path, fake_ssh: Path) -> None:
    args = ["--hub", str(hosts_hub), "hosts", "run", "nas", "--", "echo", "hi"]
    r = CliRunner().invoke(app, args)
    assert r.exit_code == 0, r.output
    argv = json.loads(r.output)
    assert argv[argv.index("-p") + 1] == "2222"
    assert argv[argv.index("--") + 1] == "user@nas.local"
    assert argv[-2] == "user@nas.local"
    assert argv[-1].startswith('bash -c "$(printf %s ')
    prefix, suffix = 'bash -c "$(printf %s ', ' | base64 -d)"'
    b64 = argv[-1][len(prefix) : -len(suffix)]
    assert base64.b64decode(b64).decode("utf-8") == "echo hi"


@pytest.mark.skipif(is_windows(), reason="fake ssh script needs a POSIX shebang")
def test_hosts_run_timeout_after_name_and_single_string_command(
    hosts_hub: Path, fake_ssh: Path
) -> None:
    args = ["--hub", str(hosts_hub), "hosts", "run", "nas", "--timeout", "5", "--", "cd /x && make"]
    r = CliRunner().invoke(app, args)
    assert r.exit_code == 0, r.output
    argv = json.loads(r.output)
    prefix, suffix = 'bash -c "$(printf %s ', ' | base64 -d)"'
    b64 = argv[-1][len(prefix) : -len(suffix)]
    assert base64.b64decode(b64).decode("utf-8") == "cd /x && make"


@pytest.mark.skipif(is_windows(), reason="fake ssh script needs a POSIX shebang")
def test_hosts_check_and_push(hosts_hub: Path, fake_ssh: Path, tmp_path: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hosts_hub), "hosts", "check", "nas"])
    assert r.exit_code == 0 and "ok" in r.output
    local = tmp_path / "f.txt"
    local.write_text("x", encoding="utf-8")
    args = ["--hub", str(hosts_hub), "hosts", "push", "nas", str(local), "/srv/f.txt"]
    r = CliRunner().invoke(app, args)
    assert r.exit_code == 0
    argv = json.loads(r.output)
    assert argv[-1] == "user@nas.local:/srv/f.txt"


def test_hosts_run_unknown_host(hosts_hub: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hosts_hub), "hosts", "run", "nope", "--", "ls"])
    assert r.exit_code == 1
