# -*- coding: utf-8 -*-
"""cc-hub hosts: the registry of remote machines; the agent connects with ssh itself."""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer

from cc_hub.encoding import read_text


def load_hosts(hub: Path) -> list[dict]:
    path = Path(hub) / "hosts.toml"
    if not path.is_file():
        return []
    return list(tomllib.loads(read_text(path)).get("host", []))


hosts_app = typer.Typer(
    no_args_is_help=True, help="Registered remote hosts (reach them with ssh)."
)


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


def register(app: typer.Typer) -> None:
    app.add_typer(hosts_app, name="hosts")
