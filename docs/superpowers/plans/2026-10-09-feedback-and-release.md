# Feedback and 0.4.0 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent a way to report problems and suggestions about cc-hub or an installed app as issues on the right repository, and release 0.4.0.

**Architecture:** `cc-hub feedback [--app NAME] [--json]` prints the issue tracker and a privacy-safe environment block and sends nothing. The `hub-feedback` skill drafts the issue, strips private data, shows the full text, and files it with `gh` only after the user agrees. The release task bumps the version and brings CHANGELOG, acceptance checklist and install docs up to date.

**Tech Stack:** Python ≥ 3.11, typer, `importlib.metadata`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-cc-hub-design.md` (§4.1 safety, §5.9, §6, §10, §13.1 `[project.urls]`, §13.3, §15).

**Depends on:** plans 1 and 2 (`docs/superpowers/plans/2026-10-09-hub-git.md`, `docs/superpowers/plans/2026-10-09-apps.md`): `cc_hub.apps` (`AppError`, `HUB_ERRORS`, `read_installed`, `setup_status`), `cc_hub.taps` (`github_repo`, `strip_credentials`), `cc_hub.applock.load_lock`, `cc_hub.commands.link.POINTERS`, and the fixtures `ledger_tap`, `register_tap`.

## Global Constraints

- Every Python file starts with `# -*- coding: utf-8 -*-`.
- `cc-hub feedback` sends nothing and prints no hub path, user name or host name; URLs lose any `user:password@`.
- The cc-hub issue tracker comes from the package metadata (`[project.urls]` `Issues`), not from a constant in code.
- Templates are English, LF; each `SKILL.md` ≤ 100 lines; `AGENTS.md` ≤ 150 lines.
- Docs describe the current design; CHANGELOG states facts only.
- `ruff check .` and `pytest -q` pass before each commit.

---

### Task 1: `cc-hub feedback`

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cc_hub/commands/feedback.py`
- Modify: `src/cc_hub/cli.py`, `README.md`, `README.zh-CN.md`, `docs/apps.md`
- Test: `tests/integration/test_feedback.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces (in `cc_hub.commands.feedback`):
  - `package_issues_url() -> str | None`
  - `environment(hub: Path) -> dict` (`cc-hub`, `python`, `os`, `agents`)
  - `feedback_info(hub: Path, app: str | None = None, *, issues_url: str | None = None) -> dict` with keys `target`, `new_issue_url`, `github_repo`, `environment` (`environment["app"]` when `app` is given)
  - command `cc-hub feedback [--app NAME] [--json]`

- [ ] **Step 1: Add the issue tracker to `pyproject.toml`**

```toml
[project.urls]
Homepage = "https://github.com/Jenwein/cc-hub"
Issues = "https://github.com/Jenwein/cc-hub/issues"
```

Reinstall so the metadata is regenerated: `python -m pip install -e .` (CI's `uv sync` does this by itself).

- [ ] **Step 2: Write the failing tests**

In `tests/unit/test_cli.py` add `"feedback"` to the expected command names:

```python
def test_cli_exposes_exactly_the_hub_commands() -> None:
    assert _command_names() == {
        "init", "doctor", "update", "memory", "link", "where", "version", "tap", "app",
        "feedback",
    }
```

Create `tests/integration/test_feedback.py`:

```python
# -*- coding: utf-8 -*-
import json
import platform
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub import __version__, apps
from cc_hub.applock import load_lock, save_lock
from cc_hub.cli import app
from cc_hub.commands.feedback import feedback_info, package_issues_url

TRACKER = "https://github.com/Jenwein/cc-hub/issues"


def private_bits(hub: Path) -> list[str]:
    bits = [str(Path.home()), str(hub), hub.as_posix()]
    node = platform.node()
    return bits + ([node] if len(node) > 3 else [])


def test_the_package_names_its_issue_tracker() -> None:
    assert package_issues_url() == TRACKER


def test_feedback_about_cc_hub(hub: Path) -> None:
    (hub / ".claude" / "skills").mkdir(parents=True)
    info = feedback_info(hub, issues_url=TRACKER)
    assert info["target"] == TRACKER
    assert info["github_repo"] == "Jenwein/cc-hub"
    assert info["new_issue_url"] == TRACKER + "/new"
    env = info["environment"]
    assert env["cc-hub"] == __version__
    assert env["agents"] == ["claude"]
    assert set(env) == {"cc-hub", "python", "os", "agents"}
    text = json.dumps(info)
    for bit in private_bits(hub):
        assert bit not in text


@pytest.fixture
def ledger_installed(hub: Path, ledger_tap: Path, register_tap) -> Path:
    register_tap(hub, "my-apps", ledger_tap)
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    return hub


def test_feedback_about_an_app_from_a_github_tap(ledger_installed: Path) -> None:
    hub = ledger_installed
    lock = load_lock(hub)
    lock.taps["my-apps"] = {"url": "https://u:tok@github.com/you/my-apps.git"}
    save_lock(hub, lock)
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://github.com/you/my-apps/issues"
    assert info["github_repo"] == "you/my-apps"
    app_env = info["environment"]["app"]
    assert app_env["source"] == "https://github.com/you/my-apps.git"
    assert app_env["name"] == "ledger" and app_env["version"] == "0.1.0"
    assert app_env["setup"] == "pending"
    assert "tok" not in json.dumps(info)


def test_feedback_about_an_app_with_its_own_tracker_or_none(ledger_installed: Path) -> None:
    hub = ledger_installed
    info = feedback_info(hub, "ledger")
    assert info["target"] is None and info["github_repo"] is None
    assert info["environment"]["app"]["source"] == "a local tap"
    toml = hub / "apps" / "ledger" / "app.toml"
    issues = 'issues = "https://gitlab.com/you/apps/-/issues"\n'
    description = 'description = "Plain-text bookkeeping"\n'
    text = toml.read_text(encoding="utf-8").replace(description, description + issues)
    toml.write_text(text, encoding="utf-8")
    info = feedback_info(hub, "ledger")
    assert info["target"] == "https://gitlab.com/you/apps/-/issues"
    assert info["new_issue_url"] is None and info["github_repo"] is None
    with pytest.raises(apps.AppError):
        feedback_info(hub, "nope")


def test_feedback_cli(hub: Path) -> None:
    r = CliRunner().invoke(app, ["--hub", str(hub), "feedback"])
    assert r.exit_code == 0, r.output
    assert f"report to: {TRACKER}" in r.output
    assert 'gh issue create -R Jenwein/cc-hub --title "<title>" --body-file <file>' in r.output
    assert "environment:" in r.output and f"cc-hub: {__version__}" in r.output
    data = json.loads(CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--json"]).stdout)
    assert data["github_repo"] == "Jenwein/cc-hub"
    assert CliRunner().invoke(app, ["--hub", str(hub), "feedback", "--app", "nope"]).exit_code == 1
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/integration/test_feedback.py tests/unit/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'cc_hub.commands.feedback'`.

- [ ] **Step 4: Write `src/cc_hub/commands/feedback.py`**

```python
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
        target = m.issues if m and m.issues else None
        url = lock.taps.get(entry.get("tap", ""), {}).get("url")
        if "link" in entry:
            source = "linked from a local directory"
        else:
            source = taps.strip_credentials(url) if url else "a local tap"
        if target is None and url and (repo := taps.github_repo(url)):
            target = f"https://github.com/{repo}/issues"
        env["app"] = {
            "name": app,
            "version": entry.get("version"),
            "source": source,
            "commit": entry.get("commit"),
            "setup": apps.setup_status(hub, app)[0],
        }
    repo = taps.github_repo(target.rstrip("/").removesuffix("/issues")) if target else None
    return {
        "target": target,
        "new_issue_url": f"{target.rstrip('/')}/new" if target and repo else None,
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
        typer.echo(
            f"no issue tracker: {app} comes from a local tap or directory; it is the user's own"
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
```

- [ ] **Step 5: Register it in `src/cc_hub/cli.py`**

```python
from cc_hub.commands import feedback as _feedback  # noqa: E402
```

and after the other `register` calls:

```python
_feedback.register(app)
```

- [ ] **Step 6: Add the command to both READMEs and to `docs/apps.md`**

`README.md` commands table, before the `where` row:

```markdown
| `cc-hub feedback [--app NAME] [--json]` | Where to report a problem, with an environment block; sends nothing. |
```

`README.zh-CN.md`, same place:

```markdown
| `cc-hub feedback [--app NAME] [--json]` | 反馈问题的去处和环境信息，不发送任何东西 |
```

`docs/apps.md`, at the end of "## Publish":

```markdown
Problems with an app go to its tap's issue tracker: `cc-hub feedback --app
<name>` prints where, and the agent drafts the issue for you to approve.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_feedback.py tests/unit -q`
Expected: all pass.

- [ ] **Step 8: Lint and commit**

```bash
python -m ruff check .
git add pyproject.toml src/cc_hub/commands/feedback.py src/cc_hub/cli.py README.md README.zh-CN.md docs/apps.md tests/integration/test_feedback.py tests/unit/test_cli.py
git commit -m "feat: cc-hub feedback prints where to report a problem"
```

---

### Task 2: the hub-feedback skill

**Files:**
- Create: `src/cc_hub/templates/skills/hub-feedback/SKILL.md`
- Modify: `src/cc_hub/manifest.py`, `src/cc_hub/templates/AGENTS.md`
- Test: `tests/unit/test_manifest.py`, `tests/integration/test_link.py`, `tests/integration/test_doctor.py`

**Interfaces:**
- Produces: framework file `skills/hub-feedback/SKILL.md`; an `AGENTS.md` safety rule naming `hub-feedback`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_manifest.py`:

1. In `test_skills_have_valid_frontmatter_and_budget`, expect
   `{"hub-adapt", "hub-apps", "hub-feedback", "hub-memory"}`.
2. Append:

```python
def test_hub_feedback_asks_before_filing() -> None:
    skill = manifest.render("skills/hub-feedback/SKILL.md")
    for phrase in ("cc-hub feedback", "gh issue list", "gh issue create", "--body-file",
                   "USER.md", "MEMORY.md", "agrees", "group chat"):
        assert phrase in skill, phrase
    agents = manifest.render("AGENTS.md")
    assert "`hub-feedback`" in agents and "publishes" in agents
```

In `tests/integration/test_link.py` set `BUILT_IN = ["hub-adapt", "hub-apps", "hub-feedback", "hub-memory"]`.

In `tests/integration/test_doctor.py`, in `test_skill_links_are_checked_per_skill`, expect `"not linked: hub-adapt, hub-apps, hub-feedback, hub-memory"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/unit/test_manifest.py -q`
Expected: FAIL (`hub-feedback` missing).

- [ ] **Step 3: Register the skill in `src/cc_hub/manifest.py`**

Add `"skills/hub-feedback/SKILL.md",` to `FRAMEWORK_OWNED` after `"skills/hub-apps/authoring.md",`.

- [ ] **Step 4: Write `src/cc_hub/templates/skills/hub-feedback/SKILL.md`**

```markdown
---
name: hub-feedback
description: Report a problem or a suggestion about cc-hub or an installed app as an issue on its repository. Use when a cc-hub command or a built-in hub skill misbehaves, when an app's skills, setup or scripts are wrong, or when the user wants to suggest something for cc-hub or an app.
---

# hub-feedback

Opening an issue publishes text on the internet. Nothing is filed until the
user agrees to the exact title and body.

1. **Whose problem.** cc-hub: its commands, `AGENTS.md`, `BOOTSTRAP.md` and
   the built-in skills. An app: anything under `apps/<name>/`. Neither:
   cc-connect, your own runtime, or software an app uses (such as beancount);
   tell the user which project it belongs to and stop.
2. **Where.** `cc-hub feedback` (cc-hub) or `cc-hub feedback --app <name>`
   prints the issue tracker and an environment block. If it names no tracker,
   the app is the user's own; say so and stop.
3. **Already known?** If `gh auth status` succeeds, search first:
   `gh issue list -R <owner/repo> --search "<words>" --state all`. If one
   matches, show it and offer to comment there instead of opening a new one.
4. **Draft.** A one-line title. For a problem: what happened, steps to
   reproduce, expected and actual result, and the environment block. For a
   suggestion: what and why.
5. **Remove private data.** Nothing from `USER.md`, `MEMORY.md`, `memory/` or
   app data directories; no credentials, host names, IP addresses or paths
   that contain user names. Quote only the error lines that matter.
6. **Ask.** Show the full title and body. File only after the user agrees:
   with `gh`, write the body to a temporary file and run
   `gh issue create -R <owner/repo> --title "<title>" --body-file <file>`;
   without `gh`, give the user the new-issue link and the text to paste.
7. **Record.** `cc-hub memory log "issue filed: <url>"`.

In a scheduled task or a group chat, only draft: log the draft with
`cc-hub memory log` and bring it up in the next direct chat with the user.
```

- [ ] **Step 5: Add the rule to "## 5. Safety" in `src/cc_hub/templates/AGENTS.md`**

```markdown
- Opening an issue publishes text: show the user the full title and body and
  file it only after they agree (`hub-feedback`).
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Lint and commit**

```bash
python -m ruff check .
git add src/cc_hub/manifest.py src/cc_hub/templates tests/unit/test_manifest.py tests/integration/test_link.py tests/integration/test_doctor.py
git commit -m "feat: the hub-feedback skill files issues only after the user agrees"
```

---

### Task 3: release 0.4.0

**Files:**
- Modify: `src/cc_hub/__init__.py`, `CHANGELOG.md`, `docs/acceptance.md`, `docs/install.md`

- [ ] **Step 1: Bump the version**

`src/cc_hub/__init__.py`: `__version__ = "0.4.0"`.

- [ ] **Step 2: Add the CHANGELOG entry**

Insert above `## 0.3.1`, with today's date from `date +%F`:

```markdown
## 0.4.0 - YYYY-MM-DD

### Added

- Apps. `cc-hub tap add|list|remove` registers git repositories of apps
  (taps; `owner/repo` means a GitHub repository), and `cc-hub app
  search|install|list|update|remove|sync|setup-state` manages apps in
  `apps/<name>/`. Install, update and remove print what will happen and act
  only with `--yes`. `apps.lock` records taps and installed apps and is
  committed; `apps/` is gitignored and `cc-hub app sync` restores it.
- The `hub-apps` skill: setting apps up (software with the user's approval,
  `SETUP.md`, scheduled tasks named `hub:<app>/<task>`), updating, removing,
  and writing and publishing apps (`skills/hub-apps/authoring.md`).
- `cc-hub feedback [--app NAME]` prints where to report a problem and an
  environment block. The `hub-feedback` skill drafts the issue and files it
  only after the user agrees.
- `doctor` checks `apps` and `git`.
- `docs/apps.md` and `docs/backup.md`.

### Changed

- The hub's git repository is used. `init` makes the first commit and sets a
  repository-local identity when git has none; `update`, `tap`, `app` and
  `doctor --fix` commit the paths they change. `AGENTS.md` has a Git section:
  the agent commits after each task and never rewrites history. The nightly
  memory-consolidate task pushes when the hub has a remote.
- `hub-adapt` registers the hub's default scheduled tasks, so they are
  registered on every machine; `BOOTSTRAP.md` has five steps.
- `cc-hub link` and the `doctor` check `pointers` include the skills of
  installed apps.
- `.gitignore` ignores `apps/`.

### Migration notes

- Run `cc-hub update`. In a hub without commits it first commits everything
  that is not ignored (`cc-hub: init`), then the update.
- Then have the agent run `hub-adapt` so the new `hub-apps` and
  `hub-feedback` skills are linked; `cc-hub doctor` lists what is missing.
- A hub that was bootstrapped keeps its registered `hub:memory-consolidate`
  task. To back the hub up, add a private remote (`docs/backup.md`).
```

- [ ] **Step 3: Rewrite `docs/acceptance.md`**

```markdown
# Manual acceptance checklist

Environment: WSL2, cc-connect running as a service, Claude Code as the agent,
one chat platform (Feishu or any other).

1. Install cc-hub from a regular terminal (see `install.md`), `cc-hub init`,
   `cc-hub doctor`: everything green except `bootstrap-pending` and `git`
   (no remote); `git log` in the hub shows `cc-hub: init`.
2. Configure cc-connect `work_dir` and `env.PATH`, restart cc-connect.
3. Send the first message. The agent runs bootstrap: asks for a name, writes
   `IDENTITY.md` and `USER.md`, runs `hub-adapt` (pointers, skill links,
   `hub:memory-consolidate` registered), deletes `BOOTSTRAP.md` and commits.
4. Add a private remote (`backup.md`); `cc-hub doctor`: all green.
5. Ask the agent to remember something. `memory/` has today's file,
   `cc-hub memory search` finds it, and the task ends with a commit.
6. Point a Codex bot at the same hub and send `/cron setup` in its chat.
   `AGENTS.md` ends with cc-connect's instructions block.
7. Bump the package version and run `cc-hub update`: `AGENTS.md` changes above
   its closing marker and keeps everything below it (the cc-connect block
   included); `SOUL.md`, `USER.md` and `memory/` do not change;
   `.cc-hub/backups/` holds the previous version; there is a `cc-hub: update`
   commit.
8. Prepare a test tap whose app has `requires`, `cron/`, `seed/` and
   `SETUP.md`. Ask the agent in the chat to install it: it shows the overview
   first and installs after you agree, asks before installing the software,
   registers `hub:<app>/<task>`, and `cc-hub app list` shows `done`.
9. Change `SETUP.md` in the tap and commit. Ask the agent to update the app:
   it shows the changes first, updates after you agree, and runs setup again.
10. Ask the agent to remove the app: it shows the plan first, unregisters the
    scheduled task, and the data directory stays.
11. Trigger the consolidation task by hand: the remote gets a new commit.
12. Clone the hub to another machine, run `cc-hub app sync`, configure
    cc-connect and send a message: `hub-adapt` registers the default
    scheduled tasks and the app is set up again.
13. Ask the agent to draft an issue about a cc-hub problem: it shows the full
    title and body, without private data, and files it only after you agree.
```

- [ ] **Step 4: Point `docs/install.md` at 0.4.0**

Replace `@v0.3.0` with `@v0.4.0` and `cc_hub-0.3.0-py3-none-any.whl` with `cc_hub-0.4.0-py3-none-any.whl`.

- [ ] **Step 5: Run everything**

```bash
python -m pytest -q
python -m ruff check .
python -m cc_hub version
```

Expected: tests pass, ruff clean, `0.4.0`.

- [ ] **Step 6: Commit**

```bash
git add src/cc_hub/__init__.py CHANGELOG.md docs/acceptance.md docs/install.md
git commit -m "release: 0.4.0, apps from taps, a committed hub and feedback"
```

Then follow superpowers:finishing-a-development-branch to open the pull request; tagging `v0.4.0` (which publishes) happens after the merge and only when the user says so.
