# -*- coding: utf-8 -*-
"""Command-line entry point.

`cc-hub cron guard` is a PreToolUse hook that runs before every tool call of every Claude Code
session in the hub, so `main` answers it straight from `cronguard`, without importing typer,
rich or the command modules (most of the start-up time). Everything else goes to the typer
application in `cc_hub.commands.root`.
"""

from __future__ import annotations

import sys

from cc_hub.encoding import configure_stdio

GUARD_ARGS = ["cron", "guard"]


def __getattr__(name: str):
    """`cc_hub.cli.app`: the typer application, imported when first asked for."""
    if name == "app":
        from cc_hub.commands.root import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    configure_stdio()
    if sys.argv[1:] == GUARD_ARGS:
        from cc_hub.cronguard import hook_main

        hook_main()  # never raises; prints the decision, if there is one
        return
    from cc_hub.commands.root import app

    app()
