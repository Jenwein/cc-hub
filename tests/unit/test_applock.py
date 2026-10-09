# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from cc_hub.applock import Lock, LockError, from_tilde, load_lock, save_lock, to_tilde


def test_a_missing_lock_is_empty(tmp_path: Path) -> None:
    assert load_lock(tmp_path) == Lock()


def test_the_lock_round_trips(tmp_path: Path) -> None:
    lock = Lock(
        taps={
            "my-apps": {"url": "https://github.com/you/my-apps"},
            "local": {"path": "~/dev/tap"},
        },
        apps={
            "ledger": {"tap": "my-apps", "commit": "a" * 40, "version": "0.1.0"},
            "notes": {"link": "~/dev/notes", "version": "0.2.0"},
        },
    )
    save_lock(tmp_path, lock)
    assert load_lock(tmp_path) == lock
    assert (tmp_path / "apps.lock").read_text(encoding="utf-8").startswith("# Written by")


def test_an_unreadable_lock_raises(tmp_path: Path) -> None:
    (tmp_path / "apps.lock").write_text("[taps\n", encoding="utf-8")
    with pytest.raises(LockError):
        load_lock(tmp_path)


def test_paths_under_home_use_a_tilde(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert to_tilde(home / "dev" / "x", home=home) == "~/dev/x"
    assert from_tilde("~/dev/x", home=home) == home / "dev" / "x"
    outside = tmp_path / "elsewhere"
    assert from_tilde(to_tilde(outside, home=home), home=home) == outside.absolute()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("taps = 1\n", "taps must be a table"),
        ("apps = 1\n", "apps must be a table"),
        ("[taps]\nx = 1\n", "taps.x must be a table"),
        ("[apps]\nx = 1\n", "apps.x must be a table"),
        ('[taps.t]\nname = "x"\n', "taps.t needs a url or a path"),
        ("[taps.t]\nurl = 1\n", "taps.t has a non-string url"),
        ('[apps.a]\ntap = "t"\n', "apps.a needs a link, or a tap and a commit"),
        ('[apps.a]\nversion = "1"\n', "apps.a needs a link, or a tap and a commit"),
        ("[apps.a]\nlink = 1\n", "apps.a has a non-string link"),
    ],
)
def test_a_wrongly_shaped_lock_raises(tmp_path: Path, text: str, match: str) -> None:
    (tmp_path / "apps.lock").write_text(text, encoding="utf-8")
    with pytest.raises(LockError, match=match):
        load_lock(tmp_path)
