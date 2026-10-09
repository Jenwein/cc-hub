# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from cc_hub import taps


def test_normalize_source(tmp_path: Path, ledger_tap: Path) -> None:
    url = "https://github.com/you/my-apps"
    assert taps.normalize_source(url) == {"url": url}
    assert taps.normalize_source("git@github.com:you/my-apps.git") == {
        "url": "git@github.com:you/my-apps.git"
    }
    assert taps.normalize_source("you/my-apps", cwd=tmp_path) == {"url": url}
    entry = taps.normalize_source(str(ledger_tap))
    assert taps.repo_path(tmp_path, "x", entry).resolve() == ledger_tap.resolve()
    with pytest.raises(taps.TapError, match="not a git repository"):
        taps.normalize_source(str(tmp_path))
    with pytest.raises(taps.TapError):
        taps.normalize_source("not a source", cwd=tmp_path)


def test_default_name_and_urls() -> None:
    assert taps.default_name({"url": "https://github.com/you/My-Apps.git"}) == "my-apps"
    assert taps.default_name({"url": "git@github.com:you/x.git"}) == "x"
    assert taps.default_name({"path": "~/dev/hub-apps"}) == "hub-apps"
    assert taps.strip_credentials("https://u:tok@github.com/a/b.git") == "https://github.com/a/b.git"
    assert taps.strip_credentials("git@github.com:a/b.git") == "git@github.com:a/b.git"
    assert taps.github_repo("https://github.com/a/b") == "a/b"
    assert taps.github_repo("https://u:tok@github.com/a/b.git") == "a/b"
    assert taps.github_repo("git@github.com:a/b.git") == "a/b"
    assert taps.github_repo("ssh://git@github.com/a/b.git") == "a/b"
    assert taps.github_repo("https://gitlab.com/a/b") is None
    assert taps.describe({"url": "https://u:p@example.com/t.git"}) == "https://example.com/t.git"


def test_clone_list_read_and_diff(
    tmp_path: Path, ledger_tap: Path, ledger_files: dict, tap_commit
) -> None:
    dest = tmp_path / "clone"
    taps.clone(ledger_tap.as_uri(), dest)
    head = taps.resolve(dest, "origin/HEAD")
    assert taps.list_apps(dest, head) == ["ledger"]
    entries = {e.path: e for e in taps.ls_app(dest, head, "ledger")}
    assert set(entries) == {p.removeprefix("ledger/") for p in ledger_files}
    assert all(e.kind == "blob" for e in entries.values())
    toml = ledger_files["ledger/app.toml"].encode()
    assert taps.read_blob(dest, entries["app.toml"].sha) == toml
    assert taps.read_blob(dest, f"{head}:ledger/app.toml") == toml
    assert taps.blob_sha(toml) == entries["app.toml"].sha

    new = tap_commit(ledger_tap, {"ledger/SETUP.md": "# Setup v2\n"})
    taps.fetch(dest, ledger_tap.as_uri())
    assert taps.resolve(dest, "origin/HEAD") == new
    assert taps.has_commit(dest, head)
    assert taps.changed_files(dest, head, new, "ledger") == [("M", "SETUP.md")]
    assert "Setup v2" in taps.diff_text(dest, head, new, "ledger", ["SETUP.md"])
    assert taps.diff_text(dest, head, new, "ledger", []) == ""
    assert taps.resolve(dest, head[:7]) == head
    with pytest.raises(taps.TapError):
        taps.resolve(dest, "no-such-ref")
    with pytest.raises(taps.TapError, match="no such app"):
        taps.ls_app(dest, new, "missing")


def test_a_local_tap_resolves_head(ledger_tap: Path) -> None:
    head = taps.resolve(ledger_tap, taps.default_ref({"path": str(ledger_tap)}))
    assert taps.list_apps(ledger_tap, head) == ["ledger"]


def test_a_failed_clone_hides_credentials(tmp_path: Path, git_env: Path) -> None:
    with pytest.raises(taps.TapError) as info:
        taps.clone("https://user:secret@127.0.0.1:9/none.git", tmp_path / "c")
    assert "secret" not in str(info.value)
