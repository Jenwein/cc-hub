# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

from cc_hub import gitops


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def fresh_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r 仓库"
    repo.mkdir()
    git(repo, "init", "-q")
    return repo


def test_commit_paths_commits_only_the_given_paths(tmp_path: Path, git_env: Path) -> None:
    repo = fresh_repo(tmp_path)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git(repo, "add", "b.txt")
    assert gitops.commit_paths(repo, ["a.txt"], "cc-hub: test") is None
    assert git(repo, "show", "--name-only", "--format=%s", "HEAD").split() == [
        "cc-hub:", "test", "a.txt",
    ]
    assert git(repo, "diff", "--cached", "--name-only").split() == ["b.txt"]


def test_commit_paths_records_a_deletion(tmp_path: Path, git_env: Path) -> None:
    repo = fresh_repo(tmp_path)
    (repo / "old.txt").write_text("x", encoding="utf-8")
    gitops.commit_paths(repo, ["old.txt"], "add")
    (repo / "old.txt").unlink()
    assert gitops.commit_paths(repo, ["old.txt"], "remove") is None
    assert "old.txt" not in git(repo, "ls-tree", "-r", "--name-only", "HEAD")


def test_commit_paths_with_nothing_to_commit(tmp_path: Path, git_env: Path) -> None:
    repo = fresh_repo(tmp_path)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    gitops.commit_paths(repo, ["a.txt"], "first")
    assert gitops.commit_paths(repo, ["a.txt", "missing.txt"], "second") is None
    assert git(repo, "log", "--format=%s").split("\n")[0] == "first"


def test_commit_paths_skips_ignored_paths(tmp_path: Path, git_env: Path) -> None:
    repo = fresh_repo(tmp_path)
    (repo / ".gitignore").write_text(".cc-hub/\n", encoding="utf-8")
    (repo / ".cc-hub").mkdir()
    (repo / ".cc-hub" / "x").write_text("x", encoding="utf-8")
    assert gitops.commit_paths(repo, [".cc-hub/x"], "nothing") is None
    assert not gitops.has_commits(repo)


def test_commit_paths_outside_a_repository_does_nothing(hub: Path) -> None:
    assert gitops.commit_paths(hub, ["SOUL.md"], "x") is None
    assert not (hub / ".git").exists()


def test_commit_paths_warns_when_git_refuses(tmp_path: Path, git_env: Path) -> None:
    git_env.write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    repo = fresh_repo(tmp_path)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    warning = gitops.commit_paths(repo, ["a.txt"], "x")
    assert warning is not None and warning.startswith("not committed:")


def test_ensure_identity_sets_only_what_is_missing(tmp_path: Path, git_env: Path) -> None:
    git_env.write_text("[user]\n\tname = Someone\n", encoding="utf-8")
    repo = fresh_repo(tmp_path)
    assert not gitops.has_identity(repo)
    assert gitops.ensure_identity(repo, "hub") == ["user.email"]
    assert git(repo, "config", "--local", "user.email").strip() == gitops.IDENTITY_EMAIL
    assert git(repo, "config", "user.name").strip() == "Someone"
    assert gitops.has_identity(repo)
    assert gitops.ensure_identity(repo, "hub") == []


def test_commit_all_and_status(tmp_path: Path, git_env: Path) -> None:
    repo = fresh_repo(tmp_path)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    assert gitops.uncommitted(repo) == 1
    assert gitops.commit_all(repo, "cc-hub: init") is None
    assert gitops.has_commits(repo)
    assert gitops.uncommitted(repo) == 0
    assert gitops.commit_all(repo, "again") is None
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "1"
    assert gitops.remotes(repo) == []
    git(repo, "remote", "add", "origin", "https://example.invalid/hub.git")
    assert gitops.remotes(repo) == ["origin"]
