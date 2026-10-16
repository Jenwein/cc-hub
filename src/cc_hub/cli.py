# -*- coding: utf-8 -*-
"""Command-line entry point.

`cc-hub cron guard` is a PreToolUse hook entry point that never decides anything; settings
files may still call it before every tool call, so `main` answers it without importing typer,
rich or the command modules. Everything else goes to the typer application in
`cc_hub.commands.root`.
"""

from __future__ import annotations

import sys

from cc_hub.encoding import configure_stdio

HOOK_ARGS = ["cron", "guard"]


def __getattr__(name: str):
    """`cc_hub.cli.app`: the typer application, imported when first asked for."""
    if name == "app":
        from cc_hub.commands.root import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def ignore_hook_event() -> None:
    """Read the hook event on stdin and discard it: no output, no decision, exit 0."""
    stream = sys.stdin
    if stream is None:
        return
    try:
        getattr(stream, "buffer", stream).read()
    except (OSError, ValueError):
        pass


def main() -> None:
    if sys.argv[1:3] == HOOK_ARGS:
        ignore_hook_event()
        return
    configure_stdio()
    from cc_hub.commands.root import app

    app()
