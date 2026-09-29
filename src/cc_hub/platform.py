# -*- coding: utf-8 -*-
"""Operating-system differences, kept in one place."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

COPY_MARKER = ".cc-hub-copied"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_wsl(proc_version: Path = Path("/proc/version")) -> bool:
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


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

