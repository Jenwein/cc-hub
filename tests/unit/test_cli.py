# -*- coding: utf-8 -*-
from typer.testing import CliRunner

from cc_hub import __version__
from cc_hub.cli import app


def test_version_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_no_args_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_app_does_not_dump_locals_in_tracebacks() -> None:
    from cc_hub.cli import app as cli_app

    assert cli_app.pretty_exceptions_show_locals is False
