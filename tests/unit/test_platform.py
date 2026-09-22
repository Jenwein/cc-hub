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


def test_minimal_path_is_short() -> None:
    parts = plat.minimal_path().split(";" if plat.is_windows() else ":")
    assert 1 <= len(parts) <= 3


def test_which_minimal_uses_given_path(tmp_path: Path) -> None:
    exe = tmp_path / ("tool.exe" if plat.is_windows() else "tool")
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    assert plat.which_minimal("tool", path=str(tmp_path)) is not None
    assert plat.which_minimal("tool", path=str(tmp_path / "nowhere")) is None


def test_kill_tree_reports_whether_the_signal_was_delivered() -> None:
    assert plat.kill_tree(999999) is False
    assert plat.kill_pid(999999) is False


def test_kill_tree_on_windows_always_forces(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Done:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _Done()

    monkeypatch.setattr(plat, "is_windows", lambda: True)
    monkeypatch.setattr(plat.subprocess, "run", fake_run)
    assert plat.kill_tree(4242) is True
    assert calls == [["taskkill", "/T", "/F", "/PID", "4242"]]
