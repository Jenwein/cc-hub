# -*- coding: utf-8 -*-
"""Shared CLI helpers: hub resolution from the typer context, JSON output, rich console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console

from cc_hub.hub import HubNotFound, find_hub

console = Console()


def resolve_hub(ctx: typer.Context) -> Path:
    explicit = (ctx.obj or {}).get("hub") if ctx is not None else None
    try:
        return find_hub(explicit)
    except HubNotFound as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def echo_json(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def fail(exc: Exception | str) -> NoReturn:
    """Print an error to stderr and exit 1."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1)


def warn(*messages: str | None) -> None:
    """Print each non-empty message to stderr as a warning."""
    for message in messages:
        if message:
            typer.echo(f"warning: {message}", err=True)
