# -*- coding: utf-8 -*-
"""cc-hub link: point an agent's discovery path at a hub directory."""

from __future__ import annotations

from pathlib import Path

import typer

from cc_hub.platform import LinkError, link_dir


def register(app: typer.Typer) -> None:
    @app.command("link")
    def link_cmd(
        ctx: typer.Context,
        src: Path = typer.Argument(
            ..., help="Source directory, relative to the hub or absolute."
        ),
        dst: Path = typer.Argument(
            ..., help="Destination path, relative to the hub or absolute."
        ),
    ) -> None:
        """Symlink, junction or copy SRC to DST (platform decides) and print which was used."""
        from cc_hub.console import fail, resolve_hub

        hub = resolve_hub(ctx)
        src_path = src if src.is_absolute() else hub / src
        dst_path = dst if dst.is_absolute() else hub / dst
        try:
            typer.echo(link_dir(src_path, dst_path))
        except LinkError as exc:
            fail(exc)
