# -*- coding: utf-8 -*-
"""Operating-system differences, kept in one place."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import psutil

COPY_MARKER = ".cc-hub-copied"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_wsl(proc_version: Path = Path("/proc/version")) -> bool:
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def minimal_path() -> str:
    """The PATH a service manager typically gives a daemon."""
    if is_windows():
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return os.pathsep.join([str(Path(root) / "System32"), root])
    return "/usr/bin:/bin"


def which_minimal(name: str, path: str | None = None) -> str | None:
    return shutil.which(name, path=path or minimal_path())


class LinkError(Exception):
    pass


def link_dir(
    src: Path,
    dst: Path,
    *,
    windows: bool | None = None,
    run=subprocess.run,
) -> str:
    """Make `dst` reach `src`: symlink on POSIX, junction on Windows, copy as last resort."""
    src = Path(src).resolve()
    dst = Path(dst)
    if not src.is_dir():
        raise LinkError(f"{src} is not a directory")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        if dst.resolve() == src:
            return "existing"
        dst.unlink()
    elif dst.exists():
        if dst.resolve() == src:
            return "existing"
        if (dst / COPY_MARKER).is_file():
            shutil.rmtree(dst)
        else:
            raise LinkError(
                f"{dst} exists and was not created by cc-hub; remove it first"
            )
    windows = is_windows() if windows is None else windows
    if not windows:
        dst.symlink_to(src, target_is_directory=True)
        return "symlink"
    try:
        run(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
            check=True,
            capture_output=True,
        )
        return "junction"
    except (OSError, subprocess.CalledProcessError):
        shutil.copytree(src, dst)
        (dst / COPY_MARKER).write_text(f"copied from {src}\n", encoding="utf-8")
        return "copy"


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.update(extra or {})
    return env


def spawn_detached(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    """Start argv detached from this process and its session; return the pid."""
    kwargs: dict = {
        "cwd": str(cwd),
        "env": env or child_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if is_windows():
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs).pid


def pid_alive(pid: int | None) -> bool:
    if not pid or not psutil.pid_exists(pid):
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def kill_tree(pid: int, *, force: bool = False) -> None:
    """Terminate a process and everything under it."""
    if is_windows():
        argv = ["taskkill", "/T", "/PID", str(pid)] + (["/F"] if force else [])
        subprocess.run(argv, capture_output=True, check=False)
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        pass
