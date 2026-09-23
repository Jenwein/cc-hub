# -*- coding: utf-8 -*-
"""cc-hub hosts: run commands and copy files on registered remote machines over ssh."""

from __future__ import annotations

import shlex
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

import typer

from cc_hub.encoding import bash_wrapper, decode_bytes, powershell_wrapper, read_text

SHELLS = ("bash", "pwsh", "powershell")


class HostError(Exception):
    pass


def load_hosts(hub: Path) -> list[dict]:
    path = Path(hub) / "hosts.toml"
    if not path.is_file():
        return []
    return list(tomllib.loads(read_text(path)).get("host", []))


def get_host(hub: Path, name: str) -> dict:
    for host in load_hosts(hub):
        if host.get("name") == name:
            if host.get("shell", "bash") not in SHELLS:
                raise HostError(f"host {name}: shell must be one of {', '.join(SHELLS)}")
            if not host.get("target"):
                raise HostError(f"host {name}: target is required")
            return host
    raise HostError(f"no host named '{name}' in hosts.toml")


def build_remote_command(host: dict, command: str) -> str:
    shell = host.get("shell", "bash")
    if shell == "bash":
        return bash_wrapper(command)
    return powershell_wrapper(command, exe=shell)


def _common_opts(host: dict, hub: Path, *, port_flag: str) -> list[str]:
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if host.get("port"):
        opts += [port_flag, str(host["port"])]
    if host.get("key"):
        key = Path(str(host["key"])).expanduser()
        if not key.is_absolute():
            key = Path(hub) / key
        opts += ["-i", str(key)]
    return opts


def ssh_argv(host: dict, hub: Path, remote_command: str | None) -> list[str]:
    # "--" marks end-of-options so a target like "-oProxyCommand=..." in
    # hosts.toml is taken as a positional hostname, never as an ssh flag.
    argv = ["ssh", *_common_opts(host, hub, port_flag="-p"), "--", str(host["target"])]
    if remote_command:
        argv.append(remote_command)
    return argv


def scp_argv(host: dict, hub: Path, src: str, dst: str, *, upload: bool) -> list[str]:
    # Same "--" end-of-options guard as ssh_argv, ahead of the src/dst pair.
    target = str(host["target"])
    pair = [src, f"{target}:{dst}"] if upload else [f"{target}:{src}", dst]
    return ["scp", *_common_opts(host, hub, port_flag="-P"), "--", *pair]


def run_ssh(
    argv: list[str], *, timeout: float | None = None, run: Callable = subprocess.run
) -> tuple[int, str, str]:
    try:
        proc = run(argv, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise HostError(f"{argv[0]} not found; install OpenSSH client") from exc
    except subprocess.TimeoutExpired as exc:
        raise HostError(f"{argv[0]} timed out after {timeout}s") from exc
    return proc.returncode, decode_bytes(proc.stdout or b""), decode_bytes(proc.stderr or b"")


def run_remote(
    hub: Path,
    name: str,
    command: str,
    *,
    timeout: float | None = None,
    run: Callable = subprocess.run,
) -> tuple[int, str, str]:
    host = get_host(hub, name)
    remote_command = build_remote_command(host, command)
    return run_ssh(ssh_argv(host, hub, remote_command), timeout=timeout, run=run)


def check_host(hub: Path, name: str, *, run: Callable = subprocess.run) -> tuple[int, str, str]:
    host = get_host(hub, name)
    return run_ssh(ssh_argv(host, hub, "exit 0"), timeout=30, run=run)


def join_command(parts: list[str]) -> str:
    """One argument is taken verbatim (may contain && and quotes); several are shell-joined."""
    return parts[0] if len(parts) == 1 else shlex.join(parts)


hosts_app = typer.Typer(
    no_args_is_help=True, help="Remote hosts over ssh (keys only, no passwords)."
)
_RAW = {"ignore_unknown_options": True}


def _emit(code: int, out: str, err: str) -> None:
    if out:
        typer.echo(out, nl=False)
    if err:
        typer.echo(err, err=True, nl=False)
    raise typer.Exit(code=code)


@hosts_app.command("list")
def list_cmd(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """List registered hosts."""
    from cc_hub.console import echo_json, resolve_hub

    hosts = load_hosts(resolve_hub(ctx))
    if as_json:
        echo_json(hosts)
        return
    if not hosts:
        typer.echo("no hosts registered; add a [[host]] block to hosts.toml")
        return
    for h in hosts:
        notes = f"  {h.get('notes')}" if h.get("notes") else ""
        typer.echo(f"{h.get('name')}\t{h.get('target')}\t{h.get('shell', 'bash')}{notes}")


@hosts_app.command("check")
def check_cmd(ctx: typer.Context, name: str) -> None:
    """Verify key-based login works."""
    from cc_hub.console import fail, resolve_hub

    try:
        code, _, err = check_host(resolve_hub(ctx), name)
    except HostError as exc:
        fail(exc)
    typer.echo("ok" if code == 0 else f"failed ({code}): {err.strip()}")
    raise typer.Exit(code=code)


@hosts_app.command("run", context_settings=_RAW)
def run_cmd(
    ctx: typer.Context,
    name: str,
    command: list[str] = typer.Argument(..., help="Remote command; put -- before it."),
    timeout: float | None = typer.Option(None, "--timeout", help="Seconds."),
) -> None:
    """Run a command on the host; output and exit code are passed through."""
    from cc_hub.console import fail, resolve_hub

    # click may leave a leaked "--" sentinel in the variadic argument even
    # with ignore_unknown_options; strip it defensively before joining.
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        fail("no remote command given")
    try:
        code, out, err = run_remote(resolve_hub(ctx), name, join_command(command), timeout=timeout)
    except HostError as exc:
        fail(exc)
    _emit(code, out, err)


@hosts_app.command("push")
def push_cmd(ctx: typer.Context, name: str, local: Path, remote: str) -> None:
    """Copy a local file to the host (scp)."""
    from cc_hub.console import fail, resolve_hub

    hub = resolve_hub(ctx)
    try:
        host = get_host(hub, name)
        code, out, err = run_ssh(scp_argv(host, hub, str(local), remote, upload=True))
    except HostError as exc:
        fail(exc)
    _emit(code, out, err)


@hosts_app.command("pull")
def pull_cmd(ctx: typer.Context, name: str, remote: str, local: Path) -> None:
    """Copy a file from the host (scp)."""
    from cc_hub.console import fail, resolve_hub

    hub = resolve_hub(ctx)
    try:
        host = get_host(hub, name)
        code, out, err = run_ssh(scp_argv(host, hub, remote, str(local), upload=False))
    except HostError as exc:
        fail(exc)
    _emit(code, out, err)


def register(app: typer.Typer) -> None:
    app.add_typer(hosts_app, name="hosts")
