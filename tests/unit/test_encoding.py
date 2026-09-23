# -*- coding: utf-8 -*-
import base64
import stat
import sys
from pathlib import Path

import pytest

from cc_hub import encoding

CHINESE = "总站：把工作目录变成 agent 的家。路径里有空格 和 中文，引号 \"双\" '单'，还有 $HOME。"


def test_write_and_read_roundtrip_utf8(tmp_path: Path) -> None:
    target = tmp_path / "子目录 带空格" / "文件.md"
    encoding.write_text(target, CHINESE)
    assert encoding.read_text(target) == CHINESE
    assert target.read_bytes().startswith("总".encode())  # no BOM


def test_write_is_atomic_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    encoding.write_text(target, "one")
    encoding.write_text(target, "two")
    assert encoding.read_text(target) == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_append_text_creates_and_appends(tmp_path: Path) -> None:
    target = tmp_path / "log.md"
    encoding.append_text(target, "a\n")
    encoding.append_text(target, "b\n")
    assert encoding.read_text(target) == "a\nb\n"


def test_decode_bytes_prefers_utf8() -> None:
    assert encoding.decode_bytes(CHINESE.encode("utf-8")) == CHINESE


def test_decode_bytes_detects_gbk() -> None:
    text = (
        "这是一段足够长的中文文本，用来让编码探测器有把握地识别出 GBK 编码。"
        "再加一句话增加样本量。"
    )
    assert encoding.decode_bytes(text.encode("gbk")) == text


def test_decode_bytes_never_raises_on_garbage() -> None:
    out = encoding.decode_bytes(b"\xff\xfe\xfa\x00\x01")
    assert isinstance(out, str)


def test_decode_bytes_empty() -> None:
    assert encoding.decode_bytes(b"") == ""


def test_bash_wrapper_carries_command_as_base64() -> None:
    wrapped = encoding.bash_wrapper(CHINESE)
    assert wrapped.startswith('bash -c "$(printf %s ')
    assert wrapped.endswith(' | base64 -d)"')
    b64 = wrapped[len('bash -c "$(printf %s ') : -len(' | base64 -d)"')]
    assert base64.b64decode(b64).decode("utf-8") == CHINESE
    assert '"' not in b64 and "'" not in b64 and "$" not in b64


def test_powershell_wrapper_uses_utf16le_base64() -> None:
    wrapped = encoding.powershell_wrapper(CHINESE, exe="powershell")
    assert wrapped.startswith("powershell -NoProfile -EncodedCommand ")
    b64 = wrapped.split()[-1]
    assert base64.b64decode(b64).decode("utf-16-le") == CHINESE


def test_powershell_wrapper_default_exe_is_pwsh() -> None:
    assert encoding.powershell_wrapper("dir").startswith("pwsh ")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix permissions test")
def test_write_text_fresh_file_respects_umask(tmp_path: Path) -> None:
    """Fresh write_text should produce readable file, not 0o600."""
    target = tmp_path / "fresh.txt"
    encoding.write_text(target, "content")
    mode = stat.S_IMODE(target.stat().st_mode)
    # Assert that group/other have read permission (not mode 0o600)
    assert mode & 0o044 != 0


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix permissions test")
def test_write_text_preserves_existing_permissions(tmp_path: Path) -> None:
    """Overwriting a file should preserve its existing permissions."""
    target = tmp_path / "existing.txt"
    # Create file with specific permissions 0o640
    encoding.write_text(target, "original")
    target.chmod(0o640)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    assert original_mode == 0o640
    # Overwrite the file
    encoding.write_text(target, "new content")
    # Permissions should be preserved
    new_mode = stat.S_IMODE(target.stat().st_mode)
    assert new_mode == 0o640
