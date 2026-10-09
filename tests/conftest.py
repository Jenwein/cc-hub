# -*- coding: utf-8 -*-
import shutil
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
