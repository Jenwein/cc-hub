# -*- coding: utf-8 -*-
"""The hub's own git repository: path-limited commits, identity, status."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

IDENTITY_EMAIL = "hub@cc-hub.invalid"
_INDEX_LOCK = "index.lock"


class GitError(Exception):
    pass


def git_available() -> bool:
    return shutil.which("git") is not None


def run_git(
    repo: Path, *args: str, check: bool = True, binary: bool = False
) -> subprocess.CompletedProcess:
    """Run `git -C <repo> <args>`; never waits for a credential prompt."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    text_mode = {} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, env=env, **text_mode
    )
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace") if binary else proc.stderr
        raise GitError(err.strip() or f"git {args[0]} exited with {proc.returncode}")
    return proc


def is_repo(hub: Path) -> bool:
    return git_available() and (Path(hub) / ".git").exists()


def has_commits(hub: Path) -> bool:
    return run_git(hub, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def _config(hub: Path, key: str) -> str:
    return run_git(hub, "config", "--get", key, check=False).stdout.strip()


def has_identity(hub: Path) -> bool:
    return bool(_config(hub, "user.name") and _config(hub, "user.email"))


def ensure_identity(hub: Path, name: str) -> list[str]:
    """Set whatever part of user.name / user.email git lacks, in this repository only."""
    wanted = {"user.name": f"{name} (cc-hub)", "user.email": IDENTITY_EMAIL}
    set_keys = []
    for key, value in wanted.items():
        if not _config(hub, key):
            run_git(hub, "config", "--local", key, value)
            set_keys.append(key)
    return set_keys


def _committable(hub: Path, rel: str) -> bool:
    """Present or tracked, and not ignored."""
    if run_git(hub, "check-ignore", "-q", "--", rel, check=False).returncode == 0:
        return False
    if (Path(hub) / rel).exists():
        return True
    return bool(run_git(hub, "ls-files", "--", rel, check=False).stdout.strip())


def commit_paths(hub: Path, paths: list[str], message: str, *, wait: float = 0.5) -> str | None:
    """Commit exactly `paths` (relative to the hub); other changes stay as they are.

    Returns None when committed or when there was nothing to commit, otherwise a
    warning. Does nothing outside a git repository.
    """
    hub = Path(hub)
    if not is_repo(hub):
        return None
    rels = sorted({p for p in paths if _committable(hub, p)})
    if not rels:
        return None
    for attempt in (0, 1):
        try:
            run_git(hub, "add", "-A", "--", *rels)
            staged = run_git(hub, "diff", "--cached", "--quiet", "--", *rels, check=False)
            if staged.returncode == 0:
                return None
            run_git(hub, "commit", "-q", "-m", message, "--", *rels)
            return None
        except GitError as exc:
            if attempt == 0 and _INDEX_LOCK in str(exc):
                time.sleep(wait)
                continue
            return f"not committed: {exc}"
    return None


def commit_all(hub: Path, message: str) -> str | None:
    """Commit every file that is not ignored."""
    hub = Path(hub)
    if not is_repo(hub):
        return None
    try:
        run_git(hub, "add", "-A")
        if run_git(hub, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        run_git(hub, "commit", "-q", "-m", message)
    except GitError as exc:
        return f"not committed: {exc}"
    return None


def uncommitted(hub: Path) -> int:
    out = run_git(hub, "status", "--porcelain", check=False).stdout
    return len([line for line in out.splitlines() if line.strip()])


def remotes(hub: Path) -> list[str]:
    return run_git(hub, "remote", check=False).stdout.split()
