# -*- coding: utf-8 -*-
"""Taps: git repositories holding apps, one top-level directory per app."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cc_hub.applock import from_tilde, to_tilde
from cc_hub.gitops import GitError, run_git
from cc_hub.platform import rmtree

SHORTHAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:(?!//)")
GITHUB = re.compile(
    r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<repo>[A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)
APP_TOML = re.compile(r"[^/]+/app\.toml")


class TapError(Exception):
    pass


@dataclass
class TreeEntry:
    mode: str  # 100644, 100755, 120000 (symlink), 160000 (submodule)
    kind: str  # blob, or commit for a submodule
    sha: str
    path: str  # relative to the app directory


def is_url(source: str) -> bool:
    return "://" in source or bool(SCP_LIKE.match(source))


def normalize_source(source: str, *, cwd: Path | None = None) -> dict:
    """The apps.lock entry for a tap: {"url": ...} or {"path": "~/..."}."""
    if is_url(source):
        return {"url": source}
    local = Path(source).expanduser()
    if not local.is_absolute():
        local = (cwd or Path.cwd()) / local
    if local.exists():
        if not (local / ".git").exists():
            raise TapError(f"{local} is not a git repository")
        return {"path": to_tilde(local)}
    if SHORTHAND.match(source):
        return {"url": f"https://github.com/{source}"}
    raise TapError(f"{source}: not a git URL, an existing repository, or owner/repo on GitHub")


def default_name(entry: dict) -> str:
    raw = (entry.get("url") or entry["path"]).rstrip("/")
    return re.split(r"[/:]", raw)[-1].removesuffix(".git").lower()


def strip_credentials(url: str) -> str:
    """The URL as it may be shown: no userinfo for http(s), otherwise no password."""
    parts = urlsplit(url)
    if not parts.scheme or "@" not in parts.netloc:
        return url
    userinfo, _, host = parts.netloc.rpartition("@")
    if parts.scheme in ("http", "https"):
        return urlunsplit(parts._replace(netloc=host))
    user = userinfo.partition(":")[0]
    return urlunsplit(parts._replace(netloc=f"{user}@{host}" if user else host))


def github_repo(url: str) -> str | None:
    """`owner/repo` for a GitHub https or ssh URL, else None."""
    m = GITHUB.match(strip_credentials(url))
    return m.group("repo") if m else None


def describe(entry: dict) -> str:
    return strip_credentials(entry["url"]) if "url" in entry else entry["path"]


def clone_dir(hub: Path, name: str) -> Path:
    return Path(hub) / ".cc-hub" / "taps" / name


def repo_path(hub: Path, name: str, entry: dict) -> Path:
    return from_tilde(entry["path"]) if "path" in entry else clone_dir(hub, name)


def is_clone(repo: Path) -> bool:
    """A usable clone has its own .git; a directory without one would make git walk up to
    the hub's repository."""
    return (Path(repo) / ".git").exists()


def default_ref(entry: dict) -> str:
    return "HEAD" if "path" in entry else "origin/HEAD"


def _safe(exc: Exception, url: str) -> str:
    return str(exc).replace(url, strip_credentials(url))


def clone(url: str, dest: Path) -> None:
    dest = Path(dest)
    if dest.exists():
        rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_git(dest.parent, "clone", "-q", "--no-recurse-submodules", "--", url, str(dest))
    except GitError as exc:
        raise TapError(f"could not clone {strip_credentials(url)}: {_safe(exc, url)}") from None


def fetch(repo: Path, url: str) -> None:
    try:
        run_git(repo, "fetch", "-q", "--prune", "origin")
    except GitError as exc:
        raise TapError(f"could not fetch {strip_credentials(url)}: {_safe(exc, url)}") from None
    run_git(repo, "remote", "set-head", "origin", "--auto", check=False)


def resolve(repo: Path, ref: str, *, remote: bool = False) -> str:
    """Full sha of `ref`. A cloned tap (remote=True) prefers origin/<ref>, which fetch
    advances; a local tap prefers the ref itself."""
    candidates = (f"origin/{ref}", ref) if remote else (ref, f"origin/{ref}")
    for candidate in candidates:
        proc = run_git(
            repo, "rev-parse", "--verify", "-q", f"{candidate}^{{commit}}", check=False
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    raise TapError(f"{ref}: no such commit, tag or branch in the tap")


def has_commit(repo: Path, sha: str) -> bool:
    return run_git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def list_apps(repo: Path, commit: str) -> list[str]:
    out = run_git(repo, "ls-tree", "-r", "-z", "--name-only", commit).stdout
    return sorted(p.split("/")[0] for p in out.split("\0") if APP_TOML.fullmatch(p))


def ls_app(repo: Path, commit: str, app: str) -> list[TreeEntry]:
    out = run_git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", f"{app}/").stdout
    entries = []
    for record in filter(None, out.split("\0")):
        meta, path = record.split("\t", 1)
        mode, kind, sha = meta.split()
        entries.append(TreeEntry(mode, kind, sha, path[len(app) + 1 :]))
    if not any(e.path == "app.toml" for e in entries):
        raise TapError(f"{app}: no such app at {commit[:7]}")
    return entries


def read_blob(repo: Path, obj: str) -> bytes:
    """Raw bytes of a blob, by sha or `<commit>:<path>`; no line-ending conversion."""
    return run_git(repo, "cat-file", "blob", obj, binary=True).stdout


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def changed_files(repo: Path, old: str, new: str, app: str) -> list[tuple[str, str]]:
    out = run_git(
        repo, "diff", "--name-status", "-z", "--no-renames", old, new, "--", f"{app}/"
    ).stdout
    parts = [p for p in out.split("\0") if p]
    return [(parts[i], parts[i + 1][len(app) + 1 :]) for i in range(0, len(parts), 2)]


def diff_text(repo: Path, old: str, new: str, app: str, rels: list[str]) -> str:
    if not rels:
        return ""
    paths = [f"{app}/{rel}" for rel in rels]
    return run_git(repo, "diff", "--no-color", "--no-renames", old, new, "--", *paths).stdout
