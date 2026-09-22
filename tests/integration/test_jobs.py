# -*- coding: utf-8 -*-
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.jobs import (
    Job,
    JobError,
    clean,
    list_jobs,
    load_job,
    parse_days,
    reconcile,
    save_job,
    start_job,
    stop_job,
    tail,
)
from cc_hub.platform import pid_alive

PY = sys.executable


def wait_for(hub: Path, job_id: str, timeout: float = 30.0) -> Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = reconcile(hub, load_job(hub, job_id))
        if job.status != "running":
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish")


def test_job_runs_and_records_exit_code_and_output(hub: Path, tmp_path: Path) -> None:
    job = start_job(
        hub, [PY, "-c", "import sys; print('hello 世界'); sys.exit(3)"],
        cwd=tmp_path, name="demo",
    )
    assert job.status == "running"
    assert job.runner_pid
    assert (hub / "jobs" / f"{job.id}.json").is_file()
    done = wait_for(hub, job.id)
    assert done.status == "failed"
    assert done.exit_code == 3
    assert done.pid
    assert done.ended
    assert "hello 世界" in tail(hub, job.id, 10)


def test_successful_job_is_done(hub: Path, tmp_path: Path) -> None:
    job = start_job(hub, [PY, "-c", "print('ok')"], cwd=tmp_path)
    assert wait_for(hub, job.id).status == "done"


def test_missing_command_is_failed_127(hub: Path, tmp_path: Path) -> None:
    job = start_job(hub, ["definitely-not-a-command-xyz"], cwd=tmp_path)
    done = wait_for(hub, job.id)
    assert done.status == "failed"
    assert done.exit_code == 127
    assert "cannot start" in tail(hub, job.id, 5)


def test_stop_kills_running_job(hub: Path, tmp_path: Path) -> None:
    job = start_job(hub, [PY, "-c", "import time; time.sleep(120)"], cwd=tmp_path)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and load_job(hub, job.id).pid is None:
        time.sleep(0.1)
    assert load_job(hub, job.id).pid, "runner never reported the child pid"
    stopped = stop_job(hub, job.id, grace=3.0)
    assert stopped.status == "stopped"
    time.sleep(0.5)
    assert not pid_alive(stopped.pid)


def test_stop_immediately_after_start_still_kills(hub: Path, tmp_path: Path) -> None:
    job = start_job(hub, [PY, "-c", "import time; time.sleep(120)"], cwd=tmp_path)
    stopped = stop_job(hub, job.id, grace=3.0)
    assert stopped.status == "stopped"
    time.sleep(0.5)
    assert not pid_alive(stopped.pid)
    assert not pid_alive(stopped.runner_pid)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX process groups")
def test_stop_kills_child_when_runner_is_dead(hub: Path, tmp_path: Path) -> None:
    job = start_job(hub, [PY, "-c", "import time; time.sleep(120)"], cwd=tmp_path)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and load_job(hub, job.id).pid is None:
        time.sleep(0.1)
    started = load_job(hub, job.id)
    assert started.pid, "runner never reported the child pid"
    os.kill(started.runner_pid, signal.SIGKILL)
    try:  # reap it, so the pid is really gone and os.getpgid() can no longer find it
        os.waitpid(started.runner_pid, 0)
    except ChildProcessError:
        pass
    stopped = stop_job(hub, job.id, grace=3.0)
    assert stopped.status == "stopped"
    time.sleep(0.5)
    assert not pid_alive(started.pid)


def test_reconcile_marks_dead_runner_as_lost(hub: Path) -> None:
    job = Job(
        id="20260101-000000-dead", name="x", cmd=["x"], cwd=str(hub), pid=999999, runner_pid=999999,
        started="2026-01-01T00:00:00+00:00", ended=None, status="running", exit_code=None,
        log="jobs/20260101-000000-dead.log",
    )
    save_job(hub, job)
    assert reconcile(hub, load_job(hub, job.id)).status == "lost"


def test_reconcile_keeps_just_started_job_without_runner_pid(hub: Path) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    job = Job(
        id="20260101-000000-new", name="x", cmd=["x"], cwd=str(hub), pid=None, runner_pid=None,
        started=now, ended=None, status="running", exit_code=None, log="jobs/x.log",
    )
    save_job(hub, job)
    assert reconcile(hub, load_job(hub, job.id)).status == "running"


def test_clean_removes_only_old_finished_jobs(hub: Path) -> None:
    old_end = (datetime.now(UTC) - timedelta(days=10)).isoformat(timespec="seconds")
    new_end = datetime.now(UTC).isoformat(timespec="seconds")
    for job_id, ended in (("20260101-000000-old0", old_end), ("20260901-000000-new0", new_end)):
        save_job(hub, Job(
            id=job_id, name="x", cmd=["x"], cwd=str(hub), pid=1, runner_pid=1, started=ended,
            ended=ended, status="done", exit_code=0, log=f"jobs/{job_id}.log",
        ))
        (hub / "jobs" / f"{job_id}.log").write_text("log", encoding="utf-8")
    removed = clean(hub, older_than_days=7)
    assert removed == ["20260101-000000-old0"]
    assert not (hub / "jobs" / "20260101-000000-old0.log").exists()
    assert (hub / "jobs" / "20260901-000000-new0.json").exists()


def test_parse_days() -> None:
    assert parse_days("7d") == 7
    assert parse_days("3") == 3
    with pytest.raises(ValueError):
        parse_days("soon")


def test_jobs_cli_start_status_log(hub: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, [
        "--hub", str(hub), "jobs", "start", "--cwd", str(tmp_path), "--name", "cli",
        "--", PY, "-c", "print('from cli')",
    ])
    assert r.exit_code == 0, r.output
    job_id = r.output.split()[1]
    wait_for(hub, job_id)
    r = runner.invoke(app, ["--hub", str(hub), "jobs", "status", job_id])
    assert "done" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "jobs", "log", job_id])
    assert "from cli" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "jobs", "status", "nope"])
    assert r.exit_code == 1


def _bad_records(hub: Path) -> None:
    (hub / "jobs").mkdir(exist_ok=True)
    (hub / "jobs" / "garbage.json").write_text("{", encoding="utf-8")
    (hub / "jobs" / "extra.json").write_text('{"id": "x", "surprise": 1}', encoding="utf-8")


def test_load_job_rejects_corrupt_records(hub: Path) -> None:
    _bad_records(hub)
    for job_id in ("garbage", "extra"):
        with pytest.raises(JobError):
            load_job(hub, job_id)


def test_list_jobs_skips_corrupt_records_and_reports_them(hub: Path, tmp_path: Path) -> None:
    good = start_job(hub, [PY, "-c", "print('ok')"], cwd=tmp_path)
    wait_for(hub, good.id)
    _bad_records(hub)
    seen: list[str] = []
    jobs = list_jobs(hub, on_error=lambda path, exc: seen.append(path.name))
    assert [j.id for j in jobs] == [good.id]
    assert sorted(seen) == ["extra.json", "garbage.json"]


def test_jobs_status_cli_survives_corrupt_records(hub: Path, tmp_path: Path) -> None:
    good = start_job(hub, [PY, "-c", "print('ok')"], cwd=tmp_path)
    wait_for(hub, good.id)
    _bad_records(hub)
    r = CliRunner().invoke(app, ["--hub", str(hub), "jobs", "status"])
    assert r.exit_code == 0, r.output
    assert good.id in r.output


def test_tail_rejects_a_record_with_a_foreign_log_path(hub: Path) -> None:
    save_job(hub, Job(
        id="20260101-000000-evil", name="x", cmd=["x"], cwd=str(hub), pid=1, runner_pid=1,
        started="2026-01-01T00:00:00+00:00", ended="2026-01-01T00:00:01+00:00",
        status="done", exit_code=0, log="../../etc/passwd",
    ))
    with pytest.raises(JobError):
        tail(hub, "20260101-000000-evil", 5)
    with pytest.raises(JobError):
        clean(hub, older_than_days=7)
