# -*- coding: utf-8 -*-
"""UTF-8 discipline: text IO and stdio."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path


def configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr regardless of the console's code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    """Atomic write: temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        # Preserve file permissions: copy from existing file or use umask-derived default
        try:
            if path.exists():
                os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
            else:
                current = os.umask(0)
                os.umask(current)
                os.chmod(tmp, 0o666 & ~current)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

