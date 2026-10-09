# -*- coding: utf-8 -*-
import stat
from pathlib import Path

from cc_hub.platform import rmtree


def test_rmtree_removes_read_only_files(tmp_path: Path) -> None:
    root = tmp_path / "d"
    (root / "sub").mkdir(parents=True)
    ro = root / "sub" / "ro.txt"
    ro.write_text("x", encoding="utf-8")
    ro.chmod(stat.S_IREAD)
    rmtree(root)
    assert not root.exists()
