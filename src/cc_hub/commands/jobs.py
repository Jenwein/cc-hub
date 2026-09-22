# -*- coding: utf-8 -*-
"""cc-hub jobs: detached background jobs supervised by a runner process."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import typer

from cc_hub.encoding import decode_bytes, read_text, write_text
from cc_hub.platform import child_env, kill_pid, kill_tree, pid_alive, spawn_detached

STATUSES = ("running", "done", "failed", "stopped", "lost")
STARTUP_GRACE = timedelta(seconds=10)


class JobError(Exception):
    pass


@dataclass
class Job:
    id: str
    name: str
    cmd: list[str]
    cwd: str
    pid: int | None
    runner_pid: int | None
    started: str
    ended: str | None
    status: str
    exit_code: int | None
    log: str


def jobs_dir(hub: Path) -> Path:
    return Path(hub) / "jobs"


def job_path(hub: Path, job_id: str) -> Path:
    return jobs_dir(hub) / f"{job_id}.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def save_job(hub: Path, job: Job) -> None:
    write_text(job_path(hub, job.id), json.dumps(asdict(job), ensure_ascii=False, indent=2) + "\n")


def load_job(hub: Path, job_id: str) -> Job:
    path = job_path(hub, job_id)
    if not path.is_file():
        raise JobError(f"no job named {job_id}")
    return Job(**json.loads(read_text(path)))


def list_jobs(hub: Path) -> list[Job]:
    paths = sorted(jobs_dir(hub).glob("*.json"), reverse=True)
    return [Job(**json.loads(read_text(p))) for p in paths]


def start_job(hub: Path, cmd: list[str], *, cwd: Path, name: str | None = None) -> Job:
    hub = Path(hub)
    if not cmd:
        raise JobError("no command given (put it after --)")
    cwd = Path(cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise JobError(f"{cwd} is not a directory")
    jobs_dir(hub).mkdir(exist_ok=True)
    job_id = new_id()
    job = Job(
        id=job_id, name=name or Path(cmd[0]).name, cmd=list(cmd), cwd=str(cwd),
        pid=None, runner_pid=None, started=_now(), ended=None, status="running",
        exit_code=None, log=f"jobs/{job_id}.log",
    )
    save_job(hub, job)
    runner = [sys.executable, "-m", "cc_hub", "--hub", str(hub), "jobs", "_run", job_id]
    job.runner_pid = spawn_detached(runner, cwd=hub)
    # Do not save here: the runner writes runner_pid/pid itself; a second write would race it.
    return job


def run_job(hub: Path, job_id: str) -> int:
    """Runner body: execute the command, stream output to the log, record the outcome."""
    hub = Path(hub)
    job = load_job(hub, job_id)
    job.runner_pid = os.getpid()
    save_job(hub, job)
    log = hub / job.log
    log.parent.mkdir(exist_ok=True)
    with log.open("ab") as fh:
        try:
            proc = subprocess.Popen(
                job.cmd, cwd=job.cwd, stdin=subprocess.DEVNULL, stdout=fh,
                stderr=subprocess.STDOUT, env=child_env(),
            )
        except OSError as exc:
            fh.write(f"cc-hub: cannot start command: {exc}\n".encode())
            job.status, job.exit_code, job.ended = "failed", 127, _now()
            save_job(hub, job)
            return 127
        job.pid = proc.pid
        save_job(hub, job)
        code = proc.wait()
    job.exit_code = code
    job.ended = _now()
    job.status = "done" if code == 0 else "failed"
    save_job(hub, job)
    return code


def is_lost(job: Job) -> bool:
    if job.status != "running":
        return False
    if job.runner_pid is None:
        started = datetime.fromisoformat(job.started)
        if datetime.now(started.tzinfo) - started < STARTUP_GRACE:
            return False
    return not (pid_alive(job.runner_pid) or pid_alive(job.pid))


def reconcile(hub: Path, job: Job) -> Job:
    if is_lost(job):
        job.status = "lost"
        job.ended = _now()
        save_job(hub, job)
    return job


def _alive(job: Job) -> bool:
    return pid_alive(job.runner_pid) or pid_alive(job.pid)


def _no_pid_yet(job: Job) -> bool:
    return job.status == "running" and job.runner_pid is None and job.pid is None


def _signal(job: Job, *, force: bool) -> bool:
    """Reach the job however we can: runner's group, child's group, then the child alone."""
    if job.runner_pid and kill_tree(job.runner_pid, force=force):
        return True
    if not job.pid:
        return False
    # The child shares the runner's group, so killpg on its own pid usually
    # fails; signalling the process itself is the last resort.
    return kill_tree(job.pid, force=force) or kill_pid(job.pid, force=force)


def stop_job(hub: Path, job_id: str, *, force: bool = False, grace: float = 10.0) -> Job:
    job = reconcile(hub, load_job(hub, job_id))
    if _no_pid_yet(job):
        # The runner may not have persisted its own pid yet (start_job returns
        # right after spawning it). Wait up to the startup grace before giving
        # up, so we do not silently skip killing a job that is really running.
        deadline = time.monotonic() + STARTUP_GRACE.total_seconds()
        while _no_pid_yet(job) and time.monotonic() < deadline:
            time.sleep(0.1)
            job = load_job(hub, job_id)
        if _no_pid_yet(job):
            return reconcile(hub, job)
    if job.status != "running":
        return job
    _signal(job, force=force)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and _alive(job):
        time.sleep(0.1)
    if _alive(job):
        _signal(job, force=True)
        time.sleep(0.3)
    job = load_job(hub, job_id)
    if job.status == "running":
        job.status = "stopped"
        job.ended = _now()
        save_job(hub, job)
    return job


def tail(hub: Path, job_id: str, n: int) -> str:
    path = Path(hub) / load_job(hub, job_id).log
    if not path.is_file():
        return ""
    return "\n".join(decode_bytes(path.read_bytes()).splitlines()[-n:])


def parse_days(text: str) -> int:
    match = re.fullmatch(r"(\d+)d?", text.strip())
    if not match:
        raise ValueError(f"expected a number of days like 7d, got {text!r}")
    return int(match.group(1))


def clean(hub: Path, *, older_than_days: int) -> list[str]:
    cutoff = datetime.now().astimezone() - timedelta(days=older_than_days)
    removed: list[str] = []
    for job in list_jobs(hub):
        job = reconcile(hub, job)
        if job.status == "running" or not job.ended:
            continue
        ended = datetime.fromisoformat(job.ended)
        if ended.tzinfo is None:
            ended = ended.astimezone()
        if ended < cutoff:
            job_path(hub, job.id).unlink(missing_ok=True)
            (Path(hub) / job.log).unlink(missing_ok=True)
            removed.append(job.id)
    return removed


jobs_app = typer.Typer(
    no_args_is_help=True, help="Detached background jobs that outlive the chat session."
)
_RAW = {"allow_interspersed_args": False, "ignore_unknown_options": True}


@jobs_app.command("start", context_settings=_RAW)
def start_cmd(
    ctx: typer.Context,
    command: list[str] = typer.Argument(..., help="Command and arguments; put -- before them."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory for the job."),
    name: str | None = typer.Option(None, "--name", help="Short label."),
) -> None:
    """Start a detached background job and return its id immediately."""
    from cc_hub.console import fail, resolve_hub

    hub = resolve_hub(ctx)
    try:
        job = start_job(hub, command, cwd=cwd, name=name)
    except JobError as exc:
        fail(exc)
    typer.echo(f"started {job.id} (runner pid {job.runner_pid})")
    typer.echo(f"log: {hub / job.log}")


@jobs_app.command("_run", hidden=True)
def run_cmd(ctx: typer.Context, job_id: str) -> None:
    from cc_hub.console import resolve_hub

    raise typer.Exit(code=run_job(resolve_hub(ctx), job_id))


@jobs_app.command("status")
def status_cmd(
    ctx: typer.Context,
    job_id: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show one job or all jobs, newest first."""
    from cc_hub.console import echo_json, fail, resolve_hub

    hub = resolve_hub(ctx)
    try:
        jobs = [load_job(hub, job_id)] if job_id else list_jobs(hub)
    except JobError as exc:
        fail(exc)
    jobs = [reconcile(hub, j) for j in jobs]
    if as_json:
        echo_json([asdict(j) for j in jobs])
        return
    if not jobs:
        typer.echo("no jobs")
        return
    for j in jobs:
        typer.echo(f"{j.id}\t{j.status}\t{j.name}\texit={j.exit_code}\tstarted={j.started}\tcwd={j.cwd}")


@jobs_app.command("log")
def log_cmd(ctx: typer.Context, job_id: str, tail_n: int = typer.Option(50, "--tail")) -> None:
    """Print the last lines of a job's output."""
    from cc_hub.console import fail, resolve_hub

    try:
        typer.echo(tail(resolve_hub(ctx), job_id, tail_n))
    except JobError as exc:
        fail(exc)


@jobs_app.command("stop")
def stop_cmd(ctx: typer.Context, job_id: str, force: bool = typer.Option(False, "--force")) -> None:
    """Terminate a running job (SIGTERM, then SIGKILL after 10 s)."""
    from cc_hub.console import fail, resolve_hub

    try:
        job = stop_job(resolve_hub(ctx), job_id, force=force)
    except JobError as exc:
        fail(exc)
    typer.echo(f"{job.id} {job.status}")


@jobs_app.command("clean")
def clean_cmd(ctx: typer.Context, older_than: str = typer.Option("7d", "--older-than")) -> None:
    """Delete records and logs of jobs that finished more than N days ago."""
    from cc_hub.console import fail, resolve_hub

    try:
        days = parse_days(older_than)
    except ValueError as exc:
        fail(exc)
    removed = clean(resolve_hub(ctx), older_than_days=days)
    typer.echo(f"removed {len(removed)} job(s)")


def register(app: typer.Typer) -> None:
    app.add_typer(jobs_app, name="jobs")
