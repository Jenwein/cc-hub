# -*- coding: utf-8 -*-
"""Operating-system differences, kept in one place."""

from __future__ import annotations

import os
import shutil
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


def minimal_path() -> str:
    """The PATH a service manager typically gives a daemon."""
    if is_windows():
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return os.pathsep.join([str(Path(root) / "System32"), root])
    return "/usr/bin:/bin"


def which_minimal(name: str, path: str | None = None) -> str | None:
    return shutil.which(name, path=path or minimal_path())
