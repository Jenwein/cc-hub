# -*- coding: utf-8 -*-
import os
import subprocess
from pathlib import Path

import pytest

from cc_hub import apps
from cc_hub.applock import load_lock, save_lock

LEDGER_V2_TOML = (
    '[app]\nname = "ledger"\nversion = "0.2.0"\ndescription = "Plain-text bookkeeping"\n\n'
    '[data]\ndirs = ["ledger"]\n\n'
    '[[requires]]\nname = "beancount"\nbin = "cc-hub-test-no-such-bin"\n'
    'install = "uv tool install beancount"\n\n'
    '[[requires]]\nname = "fava"\nbin = "cc-hub-test-no-such-fava"\n'
    'install = "uv tool install fava"\n'
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def installed(hub: Path, tap: Path) -> Path:
    apps.add_tap(hub, tap.as_uri(), name="my-apps")
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    return hub


def test_add_list_search_and_remove_taps(hub: Path, ledger_tap: Path) -> None:
    name, entry, count, _ = apps.add_tap(hub, ledger_tap.as_uri(), name="my-apps")
    assert (name, entry, count) == ("my-apps", {"url": ledger_tap.as_uri()}, 1)
    assert (hub / ".cc-hub" / "taps" / "my-apps" / ".git").exists()
    assert apps.tap_infos(hub) == [{"name": "my-apps", "source": ledger_tap.as_uri(), "apps": 1}]
    with pytest.raises(apps.AppError, match="already registered"):
        apps.add_tap(hub, ledger_tap.as_uri(), name="my-apps")
    local, entry, _, _ = apps.add_tap(hub, str(ledger_tap), name="local")
    assert "path" in entry
    assert apps.search_apps(hub, "bookkeeping")[0] == {
        "app": "local/ledger", "version": "0.1.0",
        "description": "Plain-text bookkeeping", "installed": False,
    }
    assert apps.search_apps(hub, "nothing like it") == []
    apps.install(hub, apps.plan_install(hub, "my-apps/ledger"))
    with pytest.raises(apps.AppError, match="remove them first"):
        apps.remove_tap(hub, "my-apps")
    apps.remove_tap(hub, "local")
    assert set(load_lock(hub).taps) == {"my-apps"}


def test_preview_then_apply_an_update(hub: Path, ledger_tap: Path, tap_commit) -> None:
    installed(hub, ledger_tap)
    apps.set_setup_state(hub, "ledger", "done")
    old = load_lock(hub).apps["ledger"]["commit"]
    new = tap_commit(ledger_tap, {
        "ledger/app.toml": LEDGER_V2_TOML,
        "ledger/SETUP.md": "# Setup v2\n",
        "ledger/scripts/report.sh": "#!/bin/sh\n",
        "ledger/seed/ledger/budget.beancount": "; budget\n",
    })
    skill = hub / "apps" / "ledger" / "skills" / "ledger" / "SKILL.md"
    skill.write_text("my local edit\n", encoding="utf-8")

    preview = apps.preview_update(hub, "ledger")
    assert (preview.old, preview.new) == (old, new)
    assert set(preview.changed) == {
        ("M", "app.toml"), ("M", "SETUP.md"), ("A", "scripts/report.sh"),
        ("A", "seed/ledger/budget.beancount"),
    }
    assert "Setup v2" in preview.diff and "report.sh" in preview.diff
    assert "budget.beancount" not in preview.diff
    assert preview.new_requires == ["fava"]
    assert preview.local_changes == ["skills/ledger/SKILL.md"]
    assert load_lock(hub).apps["ledger"]["commit"] == old

    result = apps.apply_update(hub, preview)
    assert result.version == "0.2.0"
    assert result.seeded == ["ledger/budget.beancount"]
    assert load_lock(hub).apps["ledger"] == {"tap": "my-apps", "commit": new, "version": "0.2.0"}
    assert (hub / "apps" / "ledger" / "SETUP.md").read_text(encoding="utf-8") == "# Setup v2\n"
    backup = hub / ".cc-hub" / "backups" / "apps" / "ledger" / old[:7]
    assert (backup / "skills" / "ledger" / "SKILL.md").read_text(encoding="utf-8") == (
        "my local edit\n"
    )
    assert apps.setup_status(hub, "ledger") == ("pending", "")


def test_update_refuses_a_stale_preview(hub: Path, ledger_tap: Path, tap_commit) -> None:
    installed(hub, ledger_tap)
    tap_commit(ledger_tap, {"ledger/SETUP.md": "v2\n"})
    preview = apps.preview_update(hub, "ledger")
    lock = load_lock(hub)
    lock.apps["ledger"]["commit"] = "f" * 40
    save_lock(hub, lock)
    with pytest.raises(apps.AppError, match="changed since the preview"):
        apps.apply_update(hub, preview)


def test_a_linked_app_has_nothing_to_update(hub: Path, tmp_path: Path) -> None:
    dev = tmp_path / "dev" / "notes"
    dev.mkdir(parents=True)
    (dev / "app.toml").write_text(
        '[app]\nname = "notes"\nversion = "0.1.0"\ndescription = "Notes"\n', encoding="utf-8"
    )
    apps.install(hub, apps.plan_install(hub, str(dev), link=True))
    assert apps.preview_update(hub, "notes") is None


def test_remove_plan_and_apply(hub: Path, ledger_tap: Path) -> None:
    (hub / ".claude" / "skills").mkdir(parents=True)
    installed(hub, ledger_tap)
    apps.set_setup_state(hub, "ledger", "done")
    plan = apps.plan_remove(hub, "ledger")
    assert plan.cron_tasks == ["hub:ledger/monthly"]
    assert plan.data_dirs == ["ledger"]
    assert [r.name for r in plan.software] == ["beancount"]
    assert plan.remove_md == "" and not plan.linked
    assert (hub / "apps" / "ledger").is_dir()
    apps.apply_remove(hub, "ledger")
    assert not (hub / "apps" / "ledger").exists()
    assert "ledger" not in load_lock(hub).apps
    assert (hub / "ledger" / "main.beancount").is_file()
    assert not os.path.lexists(hub / ".claude" / "skills" / "ledger")
    assert "ledger" not in apps.load_state(hub)
    with pytest.raises(apps.AppError, match="not installed"):
        apps.plan_remove(hub, "ledger")


def test_sync_restores_apps_in_a_clone_of_the_hub(
    git_hub: Path, ledger_tap: Path, tmp_path: Path
) -> None:
    installed(git_hub, ledger_tap)
    clone = tmp_path / "other machine" / "hub"
    subprocess.run(["git", "clone", "-q", str(git_hub), str(clone)], check=True)
    assert (clone / "apps.lock").is_file() and not (clone / "apps").exists()
    (clone / "apps" / "stray").mkdir(parents=True)
    report = apps.sync(clone)
    assert report.restored == ["ledger"] and report.failed == []
    assert report.strays == ["stray"]
    assert (clone / "apps" / "ledger" / "SETUP.md").is_file()
    assert apps.setup_status(clone, "ledger") == ("pending", "")
    assert apps.sync(clone).present == ["ledger"]


def test_sync_reports_a_commit_that_is_gone(hub: Path, ledger_tap: Path) -> None:
    installed(hub, ledger_tap)
    lock = load_lock(hub)
    lock.apps["ledger"]["commit"] = "f" * 40
    save_lock(hub, lock)
    from cc_hub.platform import rmtree

    rmtree(hub / "apps" / "ledger")
    report = apps.sync(hub)
    assert [name for name, _ in report.failed] == ["ledger"]
    assert "no longer in tap" in report.failed[0][1]


def test_tap_and_app_commands_commit_apps_lock(git_hub: Path, ledger_tap: Path) -> None:
    installed(git_hub, ledger_tap)
    apps.apply_remove(git_hub, "ledger")
    apps.remove_tap(git_hub, "my-apps")
    log = git(git_hub, "log", "--format=%s").splitlines()
    assert log[:4] == [
        "cc-hub: tap remove my-apps",
        "cc-hub: app remove ledger",
        log[2],
        "cc-hub: tap add my-apps",
    ]
    assert log[2].startswith("cc-hub: app install ledger (my-apps@")


def test_a_failed_update_rolls_back_and_keeps_the_first_backup(
    hub: Path, ledger_tap: Path, tap_commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed(hub, ledger_tap)
    old = load_lock(hub).apps["ledger"]["commit"]
    new = tap_commit(ledger_tap, {
        "ledger/SETUP.md": "# Setup v2\n",
        "ledger/seed/ledger/budget.beancount": "; budget\n",
    })
    app_dir = hub / "apps" / "ledger"
    skill = app_dir / "skills" / "ledger" / "SKILL.md"
    skill.write_text("my local edit\n", encoding="utf-8")
    preview = apps.preview_update(hub, "ledger")
    backup = hub / ".cc-hub" / "backups" / "apps" / "ledger" / old[:7]

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(apps, "save_lock", boom)
        with pytest.raises(OSError, match="disk full"):
            apps.apply_update(hub, preview)

    assert load_lock(hub).apps["ledger"]["commit"] == old
    assert (app_dir / "SETUP.md").read_text(encoding="utf-8") == (
        "# Setup\n\nAsk the user for the currency.\n"
    )
    assert skill.read_text(encoding="utf-8") == "my local edit\n"
    assert (backup / "skills" / "ledger" / "SKILL.md").read_text(encoding="utf-8") == (
        "my local edit\n"
    )
    assert not any((hub / ".cc-hub" / "tmp").iterdir())

    again = apps.preview_update(hub, "ledger")
    assert again.local_changes == ["skills/ledger/SKILL.md"]
    apps.apply_update(hub, again)
    assert load_lock(hub).apps["ledger"]["commit"] == new
    assert (app_dir / "SETUP.md").read_text(encoding="utf-8") == "# Setup v2\n"
    assert (backup / "skills" / "ledger" / "SKILL.md").read_text(encoding="utf-8") == (
        "my local edit\n"
    )


def test_remove_reads_a_remove_md_that_is_not_utf8(hub: Path, ledger_tap: Path) -> None:
    installed(hub, ledger_tap)
    (hub / "apps" / "ledger" / "REMOVE.md").write_bytes(b"stop \xff service\n")
    plan = apps.plan_remove(hub, "ledger")
    assert "stop" in plan.remove_md and "service" in plan.remove_md
    apps.apply_remove(hub, "ledger")
    assert not (hub / "apps" / "ledger").exists()


def test_sync_sets_a_local_identity_in_a_clone_on_a_machine_without_one(
    git_hub: Path, git_env: Path, ledger_tap: Path, tmp_path: Path
) -> None:
    installed(git_hub, ledger_tap)
    clone = tmp_path / "other machine" / "hub"
    subprocess.run(["git", "clone", "-q", str(git_hub), str(clone)], check=True)
    git_env.write_text("", encoding="utf-8")
    report = apps.sync(clone)
    assert report.restored == ["ledger"] and report.warnings == []
    assert git(clone, "config", "--local", "user.email").strip() == "hub@cc-hub.invalid"
    assert git(clone, "config", "--local", "user.name").strip() == "中文 hub (cc-hub)"
