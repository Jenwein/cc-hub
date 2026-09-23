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


def _signalable(pid: object) -> bool:
    """Guard the killers: 0 and negatives address whole groups or every process."""
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 1


def kill_tree(pid: int, *, force: bool = False) -> bool:
    """Terminate a process group and everything in it; False when nothing was signalled.

    A pid that is not an integer above 1 is refused outright: os.killpg(-1, ...)
    and os.kill(-1, ...) address whole groups or every process on the machine.

    POSIX: `pid` must be the group leader, which every process started by
    `spawn_detached` is (start_new_session makes its pgid equal its pid). The
    group outlives its leader, so signalling it still reaches the children of a
    runner that has already died.

    Windows: taskkill always gets /F. A process started with DETACHED_PROCESS
    has no console and no message queue that WM_CLOSE could reach, so the
    graceful pass would only ever be a no-op.
    """
    if not _signalable(pid):
        return False
    if is_windows():
        argv = ["taskkill", "/T", "/F", "/PID", str(pid)]
        return subprocess.run(argv, capture_output=True, check=False).returncode == 0
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def kill_pid(pid: int, *, force: bool = False) -> bool:
    """Signal one process rather than its group; False when it is already gone."""
    if not _signalable(pid):
        return False
    if is_windows():
        argv = ["taskkill", "/F", "/PID", str(pid)]
        return subprocess.run(argv, capture_output=True, check=False).returncode == 0
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True
