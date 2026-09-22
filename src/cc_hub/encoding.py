# -*- coding: utf-8 -*-
"""UTF-8 discipline: text IO, byte decoding, stdio, and base64 command wrappers."""

from __future__ import annotations

import base64
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


def decode_bytes(data: bytes) -> str:
    """UTF-8 first; otherwise detect with charset-normalizer; never raise."""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:  # detection is best effort
        pass
    return data.decode("utf-8", errors="replace")


def bash_wrapper(command: str) -> str:
    """Wrap a command so a remote POSIX shell decodes and runs it without quoting issues."""
    b64 = base64.b64encode(command.encode("utf-8")).decode("ascii")
    return f'bash -c "$(printf %s {b64} | base64 -d)"'


def powershell_wrapper(command: str, exe: str = "pwsh") -> str:
    """PowerShell's -EncodedCommand expects base64 of UTF-16LE."""
    b64 = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return f"{exe} -NoProfile -EncodedCommand {b64}"
