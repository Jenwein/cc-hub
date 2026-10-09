# -*- coding: utf-8 -*-
from pathlib import Path

import pytest
import typer

from cc_hub import hub
from cc_hub.console import fail


def make_hub(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    content = '[hub]\nname = "x"\ntemplate_version = "0.1.0"\n'
    (path / "hub.toml").write_text(content, encoding="utf-8")
    return path


def test_explicit_path_wins(tmp_path: Path) -> None:
    h = make_hub(tmp_path / "explicit")
    assert hub.find_hub(h, cwd=tmp_path, env={}, home=tmp_path) == h.resolve()


def test_explicit_path_that_is_not_a_hub_raises(tmp_path: Path) -> None:
    with pytest.raises(hub.HubNotFound):
        hub.find_hub(tmp_path / "nope", cwd=tmp_path, env={}, home=tmp_path)


def test_env_var_is_used_when_no_explicit(tmp_path: Path) -> None:
    h = make_hub(tmp_path / "from-env")
    result = hub.find_hub(None, cwd=tmp_path, env={"CC_HUB_DIR": str(h)}, home=tmp_path)
    assert result == h.resolve()


def test_walks_up_from_cwd(tmp_path: Path) -> None:
    h = make_hub(tmp_path / "root")
    deep = h / "memory" / "deeper"
    deep.mkdir(parents=True)
    assert hub.find_hub(None, cwd=deep, env={}, home=tmp_path / "elsewhere") == h.resolve()


def test_falls_back_to_default_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    h = make_hub(home / ".cc-hub")
    assert hub.find_hub(None, cwd=tmp_path / "unrelated", env={}, home=home) == h.resolve()


def test_raises_when_nothing_found(tmp_path: Path) -> None:
    (tmp_path / "unrelated").mkdir()
    with pytest.raises(hub.HubNotFound) as exc:
        hub.find_hub(None, cwd=tmp_path / "unrelated", env={}, home=tmp_path / "home")
    assert "cc-hub init" in str(exc.value)


def test_load_and_save_config_roundtrip(tmp_path: Path) -> None:
    h = make_hub(tmp_path / "h")
    cfg = hub.load_config(h)
    assert cfg["hub"]["name"] == "x"
    cfg["memory"] = {"max_lines": 123}
    hub.save_config(h, cfg)
    assert hub.load_config(h)["memory"]["max_lines"] == 123


def test_fail_raises_exit_with_code_1(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(ValueError("boom"))
    assert exc.value.exit_code == 1
    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_hub_name_comes_from_hub_toml_or_the_directory(tmp_path: Path) -> None:
    h = make_hub(tmp_path / "dir-name")
    assert hub.hub_name(h) == "x"
    (h / "hub.toml").write_text("[hub\n", encoding="utf-8")
    assert hub.hub_name(h) == "dir-name"
    (h / "hub.toml").write_text('[hub]\ntemplate_version = "1"\n', encoding="utf-8")
    assert hub.hub_name(h) == "dir-name"
    (h / "hub.toml").unlink()
    assert hub.hub_name(h) == "dir-name"
