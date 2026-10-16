# -*- coding: utf-8 -*-
import shutil
import subprocess
from pathlib import Path

import pytest

GIT_CONFIG = (
    "[user]\n\tname = Tester\n\temail = tester@example.invalid\n"
    "[init]\n\tdefaultBranch = main\n"
    "[core]\n\tautocrlf = false\n"
)


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    from cc_hub.commands.init import init_hub

    target = tmp_path / "hub"
    init_hub(target, git=False)
    return target


@pytest.fixture
def git_env(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway global git config with an identity; system config ignored."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    config = tmp_path_factory.mktemp("gitconfig") / "config"
    config.write_text(GIT_CONFIG, encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    return config


@pytest.fixture
def git_hub(tmp_path: Path, git_env: Path) -> Path:
    from cc_hub.commands.init import init_hub

    target = tmp_path / "中文 hub"
    init_hub(target, git=True)
    return target


LEDGER_APP = {
    "ledger/app.toml": (
        '[app]\nname = "ledger"\nversion = "0.1.0"\ndescription = "Plain-text bookkeeping"\n\n'
        '[data]\ndirs = ["ledger"]\n\n'
        '[[requires]]\nname = "beancount"\nbin = "cc-hub-test-no-such-bin"\n'
        'install = "uv tool install beancount"\n'
    ),
    "ledger/SETUP.md": "# Setup\n\nAsk the user for the currency.\n",
    "ledger/skills/ledger/SKILL.md": (
        "---\nname: ledger\ndescription: Record expenses.\n---\nRun bean-check after each change.\n"
    ),
    "ledger/cron/monthly.md": (
        '---\nschedule: "0 9 1 * *"\ndefault: true\nsession: new_per_run\n---\n'
        "Summarise last month.\n"
    ),
    "ledger/scripts/check.sh": "#!/bin/sh\nbean-check ledger/main.beancount\n",
    "ledger/seed/ledger/main.beancount": 'option "title" "Ledger"\n',
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def _write_and_commit(root: Path, files: dict[str, str], remove, message: str) -> str:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    for rel in remove:
        (root / rel).unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def ledger_files() -> dict[str, str]:
    return dict(LEDGER_APP)


@pytest.fixture
def make_tap(tmp_path: Path, git_env: Path):
    """make_tap(name, {path: text}) -> a new git repository with one commit."""

    def _make(name: str, files: dict[str, str]) -> Path:
        root = tmp_path / "taps" / name
        root.mkdir(parents=True)
        _git(root, "init", "-q")
        _write_and_commit(root, files, (), "initial")
        return root

    return _make


@pytest.fixture
def tap_commit(git_env: Path):
    """tap_commit(root, {path: text}, remove=(...)) -> sha of the new commit."""

    def _commit(root: Path, files: dict[str, str], remove=(), message: str = "change") -> str:
        return _write_and_commit(root, files, remove, message)

    return _commit


@pytest.fixture
def ledger_tap(make_tap, ledger_files) -> Path:
    return make_tap("my-apps", {**ledger_files, "README.md": "Apps for tests.\n"})


@pytest.fixture
def register_tap():
    """register_tap(hub, name, repo): add a local tap to apps.lock directly."""

    def _register(hub: Path, name: str, repo: Path) -> None:
        from cc_hub.applock import load_lock, save_lock

        lock = load_lock(hub)
        lock.taps[name] = {"path": str(repo)}
        save_lock(hub, lock)

    return _register


def write(path: Path, text: str) -> None:
    """Write a UTF-8 file with LF endings, creating the parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def fake_app(hub: Path, name: str, files: dict[str, str]) -> None:
    """Install an app into the hub as apps.lock and apps/<name>/ show it, without a tap."""
    lock = hub / "apps.lock"
    old = lock.read_text(encoding="utf-8") if lock.exists() else ""
    write(lock, old + f'[apps.{name}]\nlink = "~/fake/{name}"\n')
    for rel, text in files.items():
        write(hub / "apps" / name / rel, text)


PLANS_CRON = {
    "cron/morning.md": (
        '---\nschedule: "0 8 * * *"\ndefault: true\nsession: new_per_run\n---\n'
        "Send the user today's plan.\n"
    ),
    "cron/review.md": '---\nschedule: "0 18 * * 5"\n---\nAsk how the week went.\n',
}


@pytest.fixture
def hub_with_plans(hub: Path) -> Path:
    fake_app(hub, "plans", PLANS_CRON)
    return hub


@pytest.fixture
def git_hub_with_plans(git_hub: Path) -> Path:
    fake_app(git_hub, "plans", PLANS_CRON)
    return git_hub
