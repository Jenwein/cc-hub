# -*- coding: utf-8 -*-
import base64
from pathlib import Path

import pytest

from cc_hub.commands.hosts import (
    HostError,
    build_remote_command,
    get_host,
    join_command,
    load_hosts,
    run_remote,
    scp_argv,
    ssh_argv,
)

HOSTS_TOML = """
[[host]]
name = "nas"
target = "user@nas.local"
port = 2222
shell = "bash"
key = "secrets/nas_key"

[[host]]
name = "winbox"
target = "win.local"
shell = "pwsh"

[[host]]
name = "broken"
target = "x"
shell = "fish"
"""

CMD = 'echo "你好 world" && ls -la "/tmp/a b"'


@pytest.fixture
def hosts_hub(hub: Path) -> Path:
    (hub / "hosts.toml").write_text(HOSTS_TOML, encoding="utf-8")
    return hub


def test_load_and_get(hosts_hub: Path) -> None:
    assert [h["name"] for h in load_hosts(hosts_hub)] == ["nas", "winbox", "broken"]
    assert get_host(hosts_hub, "nas")["port"] == 2222
    with pytest.raises(HostError):
        get_host(hosts_hub, "missing")
    with pytest.raises(HostError):
        get_host(hosts_hub, "broken")


def test_bash_payload_roundtrip(hosts_hub: Path) -> None:
    remote = build_remote_command(get_host(hosts_hub, "nas"), CMD)
    b64 = remote[len('bash -c "$(printf %s ') : -len(' | base64 -d)"')]
    assert base64.b64decode(b64).decode("utf-8") == CMD


def test_pwsh_payload_is_utf16le(hosts_hub: Path) -> None:
    remote = build_remote_command(get_host(hosts_hub, "winbox"), CMD)
    assert remote.startswith("pwsh -NoProfile -EncodedCommand ")
    assert base64.b64decode(remote.split()[-1]).decode("utf-16-le") == CMD


def test_ssh_argv_includes_port_key_and_batchmode(hosts_hub: Path) -> None:
    argv = ssh_argv(get_host(hosts_hub, "nas"), hosts_hub, "exit 0")
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "ConnectTimeout=15" in argv
    assert argv[argv.index("-p") + 1] == "2222"
    assert argv[argv.index("-i") + 1] == str(hosts_hub / "secrets" / "nas_key")
    assert argv[argv.index("--") + 1] == "user@nas.local"
    assert argv[-2] == "user@nas.local"
    assert argv[-1] == "exit 0"
    plain = ssh_argv(get_host(hosts_hub, "winbox"), hosts_hub, None)
    assert "-p" not in plain and "-i" not in plain
    assert plain[-2] == "--" and plain[-1] == "win.local"


def test_scp_argv_upload_and_download(hosts_hub: Path) -> None:
    host = get_host(hosts_hub, "nas")
    up = scp_argv(host, hosts_hub, "/tmp/a.txt", "/srv/a.txt", upload=True)
    assert up[0] == "scp" and up[up.index("-P") + 1] == "2222"
    assert "ConnectTimeout=15" in up
    assert up[-3] == "--"
    assert up[-2:] == ["/tmp/a.txt", "user@nas.local:/srv/a.txt"]
    down = scp_argv(host, hosts_hub, "/srv/a.txt", "/tmp/a.txt", upload=False)
    assert down[-3] == "--"
    assert down[-2:] == ["user@nas.local:/srv/a.txt", "/tmp/a.txt"]


def test_run_remote_passes_argv_and_decodes_output(hosts_hub: Path) -> None:
    captured = {}

    class Proc:
        returncode = 7
        # A longer sample than "输出" alone, so charset-normalizer's GBK
        # detection is unambiguous (mirrors test_decode_bytes_detects_gbk).
        stdout = "命令输出：一些中文结果内容".encode("gbk") + b"\n"
        stderr = b""

    def fake_run(argv, capture_output, timeout):
        captured["argv"] = argv
        captured["timeout"] = timeout
        return Proc()

    code, out, err = run_remote(hosts_hub, "nas", "dir", timeout=5, run=fake_run)
    assert code == 7 and "出" in out and err == ""
    assert captured["timeout"] == 5
    assert captured["argv"][-1].startswith('bash -c "$(printf %s ')


def test_join_command() -> None:
    assert join_command(["cd /x && make"]) == "cd /x && make"
    assert join_command(["ls", "-la", "/tmp/a b"]) == "ls -la '/tmp/a b'"
