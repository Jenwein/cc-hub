# -*- coding: utf-8 -*-
import stat
from pathlib import Path

import pytest

from cc_hub.platform import is_link, rmtree


def test_rmtree_removes_read_only_files(tmp_path: Path) -> None:
    root = tmp_path / "d"
    (root / "sub").mkdir(parents=True)
    ro = root / "sub" / "ro.txt"
    ro.write_text("x", encoding="utf-8")
    ro.chmod(stat.S_IREAD)
    rmtree(root)
    assert not root.exists()


def test_is_link_on_a_real_directory_without_windows_reparse_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux and macOS have no stat.IO_REPARSE_TAG_MOUNT_POINT."""
    monkeypatch.delattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", raising=False)
    (tmp_path / "real").mkdir()
    assert is_link(tmp_path / "real") is False
    assert is_link(tmp_path / "missing") is False
