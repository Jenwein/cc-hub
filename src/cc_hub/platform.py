# -*- coding: utf-8 -*-
"""Operating-system differences, kept in one place."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform.startswith("win")


class LinkError(Exception):
    pass


def is_link(path: Path) -> bool:
    """True for a symlink, and for a junction on Windows."""
    if Path(path).is_symlink():
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT


def link_target(path: Path) -> Path:
    """Where a symlink or junction points, whether or not the target exists."""
    raw = os.readlink(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    target = Path(raw)
    return target if target.is_absolute() else Path(path).parent / target


def remove_link(path: Path) -> None:
    """Remove a directory link without touching what it points to."""
    if is_windows():
        os.rmdir(path)
    else:
        os.unlink(path)


def link_dir(
    src: Path,
    dst: Path,
    *,
    windows: bool | None = None,
    run=subprocess.run,
) -> str:
    """Make `dst` a directory link to `src`: symlink on POSIX, junction on Windows."""
    src = Path(src).resolve()
    dst = Path(dst)
    if not src.is_dir():
        raise LinkError(f"{src} is not a directory")
    if os.path.lexists(dst):
        raise LinkError(f"{dst} already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    windows = is_windows() if windows is None else windows
    try:
        if not windows:
            dst.symlink_to(src, target_is_directory=True)
            return "symlink"
        run(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
            check=True,
            capture_output=True,
        )
        return "junction"
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LinkError(f"could not link {dst} to {src}: {exc}") from exc


def rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files, such as git objects on Windows."""

    def _retry(func, failed, *_):
        os.chmod(failed, stat.S_IWRITE)
        func(failed)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)
