# -*- coding: utf-8 -*-
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cc_hub import apps
from cc_hub.applock import load_lock
from cc_hub.crontasks import TaskDef
from cc_hub.platform import is_link


@pytest.fixture
def tapped(hub: Path, ledger_tap: Path, register_tap) -> Path:
    register_tap(hub, "my-apps", ledger_tap)
    return hub


def test_the_plan_describes_the_app_and_changes_nothing(tapped: Path) -> None:
    plan = apps.plan_install(tapped, "my-apps/ledger")
    assert plan.manifest.name == "ledger"
    assert plan.skills == ["ledger"]
    assert plan.crons == {"monthly": TaskDef("0 9 1 * *", True, "new_per_run")}
    assert plan.scripts == ["scripts/check.sh"]
    assert plan.seed == ["ledger/main.beancount"]
    assert plan.has_setup and not plan.has_remove
    assert plan.source.describe().startswith("my-apps@")
    assert not (tapped / "apps").exists() and not (tapped / "ledger").exists()


def test_install_copies_seeds_links_and_records(tapped: Path, ledger_files: dict) -> None:
    (tapped / ".claude" / "skills").mkdir(parents=True)
    plan = apps.plan_install(tapped, "my-apps/ledger")
    result = apps.install(tapped, plan)
    assert (tapped / "apps" / "ledger" / "app.toml").read_bytes() == (
        ledger_files["ledger/app.toml"].encode()
    )
    assert result.seeded == ["ledger/main.beancount"]
    assert (tapped / "ledger" / "main.beancount").is_file()
    assert load_lock(tapped).apps["ledger"] == {
        "tap": "my-apps", "commit": plan.source.commit, "version": "0.1.0",
    }
    assert (tapped / ".claude" / "skills" / "ledger" / "SKILL.md").is_file()
    assert [r.name for r in result.missing] == ["beancount"]


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes")
def test_install_keeps_the_executable_bit(tapped: Path, ledger_tap: Path, tap_commit) -> None:
    (ledger_tap / "ledger" / "scripts" / "check.sh").chmod(0o755)
    tap_commit(ledger_tap, {})
    apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    assert os.access(tapped / "apps" / "ledger" / "scripts" / "check.sh", os.X_OK)


def test_install_keeps_existing_data(tapped: Path) -> None:
    (tapped / "ledger").mkdir()
    (tapped / "ledger" / "main.beancount").write_text("mine", encoding="utf-8")
    result = apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    assert result.seeded == []
    assert (tapped / "ledger" / "main.beancount").read_text(encoding="utf-8") == "mine"


def test_install_refuses_conflicts(tapped: Path) -> None:
    mine = tapped / "skills" / "ledger"
    mine.mkdir()
    (mine / "SKILL.md").write_text("---\nname: ledger\n---\n", encoding="utf-8")
    with pytest.raises(apps.AppError, match="skill name already used"):
        apps.plan_install(tapped, "my-apps/ledger")
    (mine / "SKILL.md").unlink()
    mine.rmdir()
    apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    with pytest.raises(apps.AppError, match="already installed"):
        apps.plan_install(tapped, "my-apps/ledger")
    with pytest.raises(apps.AppError, match="<tap>/<app>"):
        apps.plan_install(tapped, "ledger")
    with pytest.raises(apps.AppError, match="no tap named"):
        apps.plan_install(tapped, "other/ledger")


def test_seed_outside_the_data_dirs_is_refused(hub: Path, make_tap, register_tap,
                                              ledger_files: dict) -> None:
    files = {**ledger_files, "ledger/seed/elsewhere/x.txt": "x"}
    register_tap(hub, "bad", make_tap("bad", files))
    with pytest.raises(apps.AppError, match="not inside a data dir"):
        apps.plan_install(hub, "bad/ledger")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlinks need privileges")
def test_a_symlink_in_the_app_is_refused(hub: Path, make_tap, register_tap, tap_commit,
                                         ledger_files: dict) -> None:
    root = make_tap("links", ledger_files)
    (root / "ledger" / "escape").symlink_to("/etc/passwd")
    tap_commit(root, {})
    register_tap(hub, "links", root)
    with pytest.raises(apps.AppError, match="only regular files"):
        apps.plan_install(hub, "links/ledger")


def test_link_install(hub: Path, tmp_path: Path) -> None:
    dev = tmp_path / "dev" / "notes"
    (dev / "skills" / "notes").mkdir(parents=True)
    (dev / "app.toml").write_text(
        '[app]\nname = "notes"\nversion = "0.2.0"\ndescription = "Notes"\n', encoding="utf-8"
    )
    (dev / "skills" / "notes" / "SKILL.md").write_text("---\nname: notes\n---\n",
                                                       encoding="utf-8")
    plan = apps.plan_install(hub, str(dev), link=True)
    assert plan.source.describe().startswith("link ")
    apps.install(hub, plan)
    assert is_link(hub / "apps" / "notes")
    assert load_lock(hub).apps["notes"]["version"] == "0.2.0"
    (dev / "SETUP.md").write_text("new", encoding="utf-8")
    assert (hub / "apps" / "notes" / "SETUP.md").read_text(encoding="utf-8") == "new"


def test_setup_state_follows_the_fingerprint(tapped: Path) -> None:
    apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    assert apps.setup_status(tapped, "ledger") == ("pending", "")
    apps.set_setup_state(tapped, "ledger", "done")
    assert apps.setup_status(tapped, "ledger") == ("done", "")
    apps.set_setup_state(tapped, "ledger", "waiting", "user installs beancount")
    assert apps.setup_status(tapped, "ledger") == ("waiting", "user installs beancount")
    (tapped / "apps" / "ledger" / "SETUP.md").write_text("changed", encoding="utf-8")
    assert apps.setup_status(tapped, "ledger") == ("pending", "")
    with pytest.raises(apps.AppError):
        apps.set_setup_state(tapped, "ledger", "finished")
    with pytest.raises(apps.AppError):
        apps.set_setup_state(tapped, "nope", "done")


def test_statuses(tapped: Path, ledger_tap: Path, tap_commit) -> None:
    apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    [row] = apps.app_statuses(tapped, which=lambda name: None)
    assert (row.name, row.version, row.present, row.setup) == ("ledger", "0.1.0", True, "pending")
    assert row.source.startswith("my-apps@")
    assert row.missing == [{"name": "beancount", "bin": "cc-hub-test-no-such-bin",
                            "install": "uv tool install beancount"}]
    assert row.update is False and row.min_hub_ok
    tap_commit(ledger_tap, {"README.md": "only the readme\n"})
    assert apps.app_statuses(tapped)[0].update is False
    tap_commit(ledger_tap, {"ledger/SETUP.md": "v2\n"})
    assert apps.app_statuses(tapped)[0].update is True


def test_hub_lock_allows_one_command_at_a_time(hub: Path) -> None:
    with apps.hub_lock(hub):
        with pytest.raises(apps.AppError, match="try again"):
            with apps.hub_lock(hub):
                pass
    lock_file = hub / ".cc-hub" / "op.lock"
    lock_file.write_text("123", encoding="utf-8")
    os.utime(lock_file, (0, 0))
    with apps.hub_lock(hub):
        pass
    assert not lock_file.exists()


def test_install_commits_the_lock_and_the_seeds(git_hub: Path, ledger_tap: Path,
                                                register_tap) -> None:
    register_tap(git_hub, "my-apps", ledger_tap)
    subprocess.run(["git", "-C", str(git_hub), "add", "apps.lock"], check=True)
    subprocess.run(["git", "-C", str(git_hub), "commit", "-qm", "tap"], check=True)
    plan = apps.plan_install(git_hub, "my-apps/ledger")
    apps.install(git_hub, plan)
    out = subprocess.run(
        ["git", "-C", str(git_hub), "show", "--name-only", "--format=%s", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.split("\n")
    assert out[0] == f"cc-hub: app install ledger (my-apps@{plan.source.commit[:7]})"
    assert set(filter(None, out[1:])) == {"apps.lock", "ledger/main.beancount"}


def test_a_failed_install_leaves_nothing_to_move_away(tapped: Path) -> None:
    (tapped / "ledger").write_text("a file where the data dir should be", encoding="utf-8")
    plan = apps.plan_install(tapped, "my-apps/ledger")
    with pytest.raises((apps.AppError, OSError)):
        apps.install(tapped, plan)
    assert not os.path.lexists(tapped / "apps" / "ledger")
    assert "ledger" not in load_lock(tapped).apps
    (tapped / "ledger").unlink()
    result = apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    assert result.name == "ledger"
    assert (tapped / "apps" / "ledger" / "app.toml").is_file()
    assert "ledger" in load_lock(tapped).apps


def test_a_failed_link_install_removes_only_the_link(hub: Path, tmp_path: Path) -> None:
    dev = tmp_path / "dev" / "notes"
    dev.mkdir(parents=True)
    (dev / "app.toml").write_text(
        '[app]\nname = "notes"\nversion = "0.2.0"\ndescription = "Notes"\n\n'
        '[data]\ndirs = ["notes-data"]\n',
        encoding="utf-8",
    )
    (hub / "notes-data").write_text("in the way", encoding="utf-8")
    plan = apps.plan_install(hub, str(dev), link=True)
    with pytest.raises((apps.AppError, OSError)):
        apps.install(hub, plan)
    assert not os.path.lexists(hub / "apps" / "notes")
    assert (dev / "app.toml").is_file()
    assert "notes" not in load_lock(hub).apps


def test_a_cron_file_that_is_not_utf8_is_an_app_error(hub: Path, make_tap, register_tap,
                                                      tap_commit, ledger_files: dict) -> None:
    root = make_tap("badcron", ledger_files)
    (root / "ledger" / "cron" / "monthly.md").write_bytes(b"---\nschedule: \xff\xfe\n---\nx\n")
    tap_commit(root, {})
    register_tap(hub, "badcron", root)
    with pytest.raises(apps.AppError, match="not UTF-8"):
        apps.plan_install(hub, "badcron/ledger")


def test_setup_state_of_a_broken_app_toml_is_an_app_error(tapped: Path) -> None:
    apps.install(tapped, apps.plan_install(tapped, "my-apps/ledger"))
    (tapped / "apps" / "ledger" / "app.toml").write_text("[app\n", encoding="utf-8")
    assert apps.setup_status(tapped, "ledger") == ("pending", "")
    with pytest.raises(apps.AppError, match="cannot read the installed app"):
        apps.set_setup_state(tapped, "ledger", "done")


def test_a_short_name_data_dir_is_refused_by_the_plan(
    hub: Path, make_tap, register_tap, ledger_files: dict
) -> None:
    """On NTFS `GIT~1` is the hub's own .git (git itself refuses such a path in a tap)."""
    files = {
        **ledger_files,
        "ledger/app.toml": ledger_files["ledger/app.toml"].replace(
            'dirs = ["ledger"]', 'dirs = ["GIT~1"]'
        ),
    }
    register_tap(hub, "bad", make_tap("bad", files))
    with pytest.raises(apps.AppError, match="data dir 'GIT~1'"):
        apps.plan_install(hub, "bad/ledger")


def test_seeding_refuses_a_data_dir_that_resolves_elsewhere(
    tapped: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = apps.plan_install(tapped, "my-apps/ledger")
    real = os.path.realpath

    def other_name(path, *args, **kwargs):
        if Path(path) == tapped / "ledger":
            return str(tapped / ".git")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(apps.os.path, "realpath", other_name)
    with pytest.raises(apps.AppError, match="resolves to .*refusing to write there"):
        apps.install(tapped, plan)
    assert not os.path.lexists(tapped / "apps" / "ledger")
    assert "ledger" not in load_lock(tapped).apps
    assert not (tapped / "ledger" / "main.beancount").exists()


def _tap_with_names_differing_in_case(root: Path) -> None:
    """Commit two files that differ only in case without touching the file system."""

    def git(*args: str, data: str | None = None) -> str:
        # bytes in and out: text mode would end the input lines with CRLF on Windows
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=True,
            input=data.encode("utf-8") if data is not None else None,
        ).stdout.decode("utf-8").strip()

    toml = (
        '[app]\nname = "notes"\nversion = "0.1.0"\ndescription = "Notes"\n'
    )
    blobs = {
        name: git("hash-object", "-w", "--stdin", data=text)
        for name, text in (("app.toml", toml), ("Notes.md", "one\n"), ("notes.md", "two\n"))
    }
    app_tree = git("mktree", data="".join(
        f"100644 blob {sha}\t{name}\n" for name, sha in blobs.items()
    ))
    root_tree = git("mktree", data=f"040000 tree {app_tree}\tnotes\n")
    commit = git("commit-tree", root_tree, "-m", "case clash")
    git("update-ref", "HEAD", commit)


def test_two_files_differing_only_in_case_are_refused(
    hub: Path, tmp_path: Path, git_env: Path, register_tap
) -> None:
    root = tmp_path / "taps" / "clash"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _tap_with_names_differing_in_case(root)
    register_tap(hub, "clash", root)
    with pytest.raises(apps.AppError, match="'Notes.md' and 'notes.md'.*differ only in case"):
        apps.plan_install(hub, "clash/notes")
