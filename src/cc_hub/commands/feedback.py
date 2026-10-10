# -*- coding: utf-8 -*-
"""cc-hub feedback: where to report a problem and what to attach; sends nothing."""

from __future__ import annotations

import platform
from importlib import metadata
from pathlib import Path

import typer

from cc_hub import __version__, apps, taps
from cc_hub.applock import load_lock
from cc_hub.commands.link import POINTERS
from cc_hub.console import echo_json, fail, resolve_hub


def package_issues_url() -> str | None:
    """The `Issues` URL in the installed package's metadata."""
    try:
        urls = metadata.metadata("cc-hub").get_all("Project-URL") or []
    except metadata.PackageNotFoundError:
        return None
    for item in urls:
        label, _, url = item.partition(",")
        if label.strip().casefold() == "issues":
            return url.strip()
    return None


def environment(hub: Path) -> dict:
    """Versions, platform and the agent ecosystems set up in the hub; nothing personal."""
    agents = sorted(
        agent
        for agent, (instructions, skills_dir) in POINTERS.items()
        if any((Path(hub) / p).exists() for p in (instructions, skills_dir) if p)
    )
    return {
        "cc-hub": __version__,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "agents": agents,
    }


def feedback_info(
    hub: Path, app: str | None = None, *, issues_url: str | None = None
) -> dict:
    hub = Path(hub)
    env = environment(hub)
    if app is None:
        target = issues_url if issues_url is not None else package_issues_url()
    else:
        lock = load_lock(hub)
        entry = lock.apps.get(app)
        if entry is None:
            raise apps.AppError(f"{app} is not installed")
        m = apps.read_installed(hub, app)
        target = taps.strip_credentials(m.issues) if m and m.issues else None
        url = lock.taps.get(entry.get("tap", ""), {}).get("url")
        if "link" in entry:
            kind, source = "link", "linked from a local directory"
        elif url:
            kind, source = "remote tap", taps.strip_credentials(url)
        else:
            kind, source = "local tap", "a local tap"
        if target is None and url and (repo := taps.github_repo(url)):
            target = f"https://github.com/{repo}/issues"
        env["app"] = {
            "name": app,
            "version": entry.get("version"),
            "kind": kind,
            "source": source,
            "commit": entry.get("commit"),
            "setup": apps.setup_status(hub, app)[0],
        }
    repo = taps.github_repo(target.rstrip("/").removesuffix("/issues")) if target else None
    return {
        "target": target,
        "new_issue_url": f"https://github.com/{repo}/issues/new" if repo else None,
        "github_repo": repo,
        "environment": env,
    }


def _print(info: dict, app: str | None) -> None:
    if info["target"]:
        typer.echo(f"report to: {info['target']}")
        if info["new_issue_url"]:
            typer.echo(f"new issue: {info['new_issue_url']}")
        if info["github_repo"]:
            typer.echo(
                f'with gh: gh issue create -R {info["github_repo"]} '
                '--title "<title>" --body-file <file>'
            )
    elif app:
        app_env = info["environment"]["app"]
        if app_env["kind"] == "remote tap":
            typer.echo(f"no issue tracker known for {app}; its tap is {app_env['source']}")
        else:
            typer.echo(
                f"no issue tracker: {app} is the user's own (a linked directory or a local tap)"
            )
    else:
        typer.echo("no issue tracker: this cc-hub build does not name one")
    typer.echo("environment:")
    for key, value in info["environment"].items():
        if isinstance(value, dict):
            typer.echo(f"  {key}:")
            for k, v in value.items():
                typer.echo(f"    {k}: {v}")
        elif isinstance(value, list):
            typer.echo(f"  {key}: {', '.join(value) or 'none'}")
        else:
            typer.echo(f"  {key}: {value}")


def register(app: typer.Typer) -> None:
    @app.command("feedback")
    def feedback_cmd(
        ctx: typer.Context,
        app_name: str | None = typer.Option(
            None, "--app", help="Report about an installed app instead of cc-hub."
        ),
        as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    ) -> None:
        """Print where to report a problem, with an environment block; sends nothing."""
        hub = resolve_hub(ctx)
        try:
            info = feedback_info(hub, app_name)
        except apps.HUB_ERRORS as exc:
            fail(exc)
        if as_json:
            echo_json(info)
        else:
            _print(info, app_name)
