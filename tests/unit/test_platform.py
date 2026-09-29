# -*- coding: utf-8 -*-
from pathlib import Path

from cc_hub import platform as plat


def test_is_wsl_reads_proc_version(tmp_path: Path) -> None:
    fake = tmp_path / "version"
    fake.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@x)", encoding="utf-8")
    assert plat.is_wsl(fake) is True
    fake.write_text("Linux version 6.8.0-45-generic (buildd@x)", encoding="utf-8")
    assert plat.is_wsl(fake) is False
    assert plat.is_wsl(tmp_path / "missing") is False

