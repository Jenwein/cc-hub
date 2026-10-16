# -*- coding: utf-8 -*-
"""Planning, assembling and sending a report.

`plan` says what a period's report will hold; `build` runs the approved section commands, reads
the drafts agents wrote for instruction sections and the notes waiting, and returns the text. It
only returns text: output of the commands never reaches the console, and nothing is stored or
removed by it. `send` is the caller that does that: it sends the text through cc-connect, then
archives and commits it, removes the notes and drafts that went in, and records the run.
`add_routed_note` stores a note for the report that will carry it.
"""

from __future__ import annotations

import calendar
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cc_hub import apps, gitops
from cc_hub.encoding import write_text
from cc_hub.reports import (
    PERIODS,
    ReportError,
    Section,
    enabled_sections,
    load_config,
    note_target,
)
from cc_hub.reportstate import (
    add_note,
    clear_drafts,
    drop_notes,
    is_approved,
    last_run,
    last_sent,
    load_state,
    read_draft,
    read_notes,
    record_run,
)

SECTION_TIMEOUT = 300  # seconds a section command may run
MAX_SECTION_CHARS = 20000  # characters of a section's output that go into the report
REAP_TIMEOUT = 5  # seconds to wait for the output of a command that was killed

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "daily": "Daily report",
        "weekly": "Weekly report",
        "monthly": "Monthly report",
        "quarterly": "Quarterly report",
        "yearly": "Yearly report",
        "notes": "Notes",
        "failed": "{title}: this section failed: {line}",
        "unapproved": (
            "{title}: not run, because its command is not approved on this machine. "
            "Approve it with cc-hub report approve {app}."
        ),
        "cut": "(cut: too long)",
    },
    "zh": {
        "daily": "日报",
        "weekly": "周报",
        "monthly": "月报",
        "quarterly": "季报",
        "yearly": "年报",
        "notes": "留言",
        "failed": "{title}：这一段出错了：{line}",
        "unapproved": (
            "{title}：没有运行，因为它的命令还没在这台机器上批准。"
            "批准：cc-hub report approve {app}"
        ),
        "cut": "（太长，已截断）",
    },
}

# months in one period; daily and weekly are counted in days
MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
DAYS = {"daily": 1, "weekly": 7}


def strings_for(language: str | None) -> dict[str, str]:
    """The built-in wording for a language tag: Chinese for `zh...`, English for anything else."""
    return STRINGS["zh" if language and language.lower().startswith("zh") else "en"]


# --- the window a report covers ---


def _months_back(moment: datetime, months: int) -> datetime:
    index = moment.year * 12 + moment.month - 1 - months
    year, month = index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])  # 31 March minus a month: 28 Feb
    return moment.replace(year=year, month=month, day=day)


def window(period: str, now: datetime, last_run: datetime | None) -> tuple[datetime, datetime]:
    """(since, until) of a report: from the last run, or one period back on a first run, to now."""
    if last_run is not None:
        return last_run, now
    if period in DAYS:
        return now - timedelta(days=DAYS[period]), now
    return _months_back(now, MONTHS[period]), now


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


# --- running a section command ---

Runner = Callable[[Path, str, dict[str, str]], tuple[str, str | None]]


def _executable(hub: Path, name: str) -> str | None:
    """`name` as shutil.which finds it (a .cmd shim too); a relative path starts in the hub."""
    if (os.sep in name or "/" in name) and not Path(name).is_absolute():
        name = str(hub / name)
    return shutil.which(name)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a command and everything it started (a .cmd shim, `uv run`, a script's children)."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=REAP_TIMEOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the command leads its own session
        except OSError:
            pass
    try:
        proc.kill()  # in case the tree kill did not reach it
    except OSError:
        pass


def run_command(hub: Path, command: str, env: dict[str, str]) -> tuple[str, str | None]:
    """Run an approved section command in the hub: (its output, None) or ("", why it failed)."""
    hub = Path(hub).absolute()
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return "", str(exc)
    if not argv:
        return "", "the command is empty"
    executable = _executable(hub, argv[0])
    if executable is None:
        return "", f"{argv[0]}: command not found"
    timeout = SECTION_TIMEOUT
    # its own process group (Windows) or session (POSIX), so that a timeout can end all of it
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    try:
        proc = subprocess.Popen(
            [executable, *argv[1:]],
            cwd=hub,
            env=os.environ | env | {"PYTHONUTF8": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            **group,
        )
    except (OSError, ValueError) as exc:
        return "", str(exc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=REAP_TIMEOUT)  # collect and drop what is left
        except subprocess.TimeoutExpired:
            pass  # something still holds the pipes: give up on them rather than wait
        return "", f"timed out after {timeout} s"
    except BaseException:  # Ctrl+C and the like: do not leave the command running
        _kill_tree(proc)
        raise
    if proc.returncode == 0:
        return stdout.strip(), None
    line = next((ln.strip() for ln in stderr.splitlines() if ln.strip()), None)
    return "", line or f"exit {proc.returncode}"


def _env(hub: Path, period: str, language: str | None, since: datetime, until: datetime) -> dict:
    return {
        "CC_HUB_DIR": str(Path(hub).absolute()),
        "CC_HUB_REPORT_PERIOD": period,
        "CC_HUB_REPORT_SINCE": _iso(since),
        "CC_HUB_REPORT_UNTIL": _iso(until),
        "CC_HUB_LANGUAGE": language or "en",
    }


# --- notes ---

_EPOCH = datetime.min.replace(tzinfo=UTC)


def _note_time(note: dict) -> datetime:
    """When a note was written; a note whose time cannot be read counts as the oldest."""
    try:
        at = datetime.fromisoformat(note["at"])
        return at if at.tzinfo is not None else at.astimezone()  # a naive time is local
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return _EPOCH


def _notes_for(hub: Path, period: str) -> list[tuple[str, dict]]:
    """(period it was written for, note) of every note the `period` report includes, oldest first.

    That is the period's own notes and those of each shorter period that routes here: one whose
    own report is not on, so that its notes go into the next one that is.
    """
    found: list[tuple[str, dict]] = []
    for shorter in PERIODS[: PERIODS.index(period)]:
        if note_target(hub, shorter) == period:
            found += [(shorter, n) for n in read_notes(hub, shorter)]
    found += [(period, n) for n in read_notes(hub, period)]
    found.sort(key=lambda item: _note_time(item[1]))  # stable: same time keeps shorter first
    return found


# --- plan ---


def plan(hub: Path, period: str, now: datetime) -> dict:
    """What the `period` report will hold: its sections, how many notes, and whether it is empty."""
    hub = Path(hub)
    sections = enabled_sections(hub, period)  # also checks the period
    config = load_config(hub)
    state = load_state(hub)
    since, until = window(period, now, last_run(state, period))
    notes = len(_notes_for(hub, period))
    return {
        "period": period,
        "language": config.language or "en",
        "since": _iso(since),
        "until": _iso(until),
        "sections": [
            {
                "app": s.app,
                "kind": s.kind,
                "title": s.title,
                "file": s.file,
                "approved": (
                    is_approved(state, s.app, period, s.command) if s.command is not None else None
                ),
            }
            for s in sections
        ],
        "notes": notes,
        "empty": not sections and notes == 0,
    }


# --- build ---


@dataclass
class Built:
    text: str  # "" when nothing in the report has content
    sections: int  # how many sections went in
    notes: int  # how many notes went in
    included: dict[str, int]  # per period, how many of its notes went in (the first ones)


def _body(
    hub: Path, section: Section, state: dict, strings: dict[str, str], env: dict, runner: Runner
) -> str:
    """The text of one section; "" when it has nothing to say."""
    if section.command is None:
        return read_draft(hub, section.period, section.app).strip()
    if not is_approved(state, section.app, section.period, section.command):
        return strings["unapproved"].format(title=section.title, app=section.app)
    output, error = runner(hub, section.command, env)
    if error is not None:
        return strings["failed"].format(title=section.title, line=error)
    output = output.strip()
    if len(output) > MAX_SECTION_CHARS:
        output = output[:MAX_SECTION_CHARS].rstrip() + "\n" + strings["cut"]
    return output


def build(hub: Path, period: str, now: datetime, *, runner: Runner = run_command) -> Built:
    """Assemble the `period` report. Runs approved commands; prints, stores and removes nothing."""
    hub = Path(hub).absolute()
    sections = enabled_sections(hub, period)  # also checks the period
    config = load_config(hub)
    strings = strings_for(config.language)
    state = load_state(hub)
    since, until = window(period, now, last_run(state, period))
    env = _env(hub, period, config.language, since, until)
    notes = _notes_for(hub, period)

    blocks: list[str] = []
    for section in sections:
        body = _body(hub, section, state, strings, env, runner)
        if body:
            blocks.append(f"## {section.title}\n\n{body}")
    count = len(blocks)
    included: dict[str, int] = {}
    for written_for, _ in notes:
        included[written_for] = included.get(written_for, 0) + 1
    if notes:
        lines = "\n".join(f"- {note['from']}: {note['text']}" for _, note in notes)
        blocks.append(f"## {strings['notes']}\n\n{lines}")
    if not blocks:
        return Built("", 0, 0, {})
    title = f"# {strings[period]} · {now.date().isoformat()}"
    return Built("\n\n".join([title, *blocks]), count, len(notes), included)


# --- sending ---

Sender = Callable[[str], None]

SEND_TIMEOUT = 60  # seconds cc-connect may take to take a report
MAX_DETAIL = 500  # characters of cc-connect's own words that go into an error
SOURCE_RULE = re.compile(r"^[a-z0-9][a-z0-9/-]{0,99}$")  # what a note's --from may be
ARCHIVE_DIR = "reports"


def _output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return (value or "").strip()


def _detail(proc: subprocess.CompletedProcess, text: str) -> str:
    """cc-connect's own words about a failure, as ": ..." (empty when it said nothing)."""
    detail = _output(proc.stderr) or _output(proc.stdout)
    if text.strip():
        detail = detail.replace(text.strip(), "(the report)")  # an error never carries the report
    if len(detail) > MAX_DETAIL:
        detail = detail[:MAX_DETAIL].rstrip() + "…"
    return f": {detail}" if detail else ""


def cc_connect_sender(
    *, which=shutil.which, run=subprocess.run, env: Mapping[str, str] = os.environ
) -> Sender:
    """A sender that gives the text to `cc-connect send`, for the project and session in `env`.

    The text goes in on stdin as UTF-8, never on the command line. ReportError says why it failed.
    """

    def send_text(text: str) -> None:
        cc = which("cc-connect")
        if cc is None:
            raise ReportError("cc-connect not found on PATH")
        argv = [cc, "send"]
        if env.get("CC_PROJECT"):
            argv += ["-p", env["CC_PROJECT"]]
        if env.get("CC_SESSION_KEY"):
            argv += ["-s", env["CC_SESSION_KEY"]]
        argv.append("--stdin")
        try:
            proc = run(argv, input=text.encode("utf-8"), capture_output=True, timeout=SEND_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ReportError(
                f"cc-connect send did not answer within {SEND_TIMEOUT} seconds; "
                "check that cc-connect is running and responsive"
            ) from None
        except OSError as exc:
            raise ReportError(f"cannot run cc-connect: {exc}") from None
        if proc.returncode != 0:
            raise ReportError(
                f"cc-connect send failed (exit {proc.returncode}){_detail(proc, text)}"
            )

    return send_text


@dataclass
class SendResult:
    status: str  # "sent" | "empty" | "already"
    sections: int
    notes: int
    archive: str | None  # the archive file, relative to the hub, with /
    warning: str | None  # a problem after the report went out; the report itself was sent


def _require_aware(now: datetime) -> None:
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _archive(hub: Path, period: str, now: datetime, text: str) -> str:
    """Write the report to reports/<year>/<date>-<period>[-2, -3, ...].md; its path in the hub."""
    year = f"{now.year:04d}"
    stem = f"{now.date().isoformat()}-{period}"
    number = 1
    while True:
        name = f"{stem}.md" if number == 1 else f"{stem}-{number}.md"
        if not os.path.lexists(hub / ARCHIVE_DIR / year / name):
            break
        number += 1
    write_text(hub / ARCHIVE_DIR / year / name, text + "\n")
    return f"{ARCHIVE_DIR}/{year}/{name}"


def send(
    hub: Path,
    period: str,
    now: datetime,
    *,
    again: bool = False,
    runner: Runner = run_command,
    sender: Sender | None = None,
) -> SendResult:
    """Build the `period` report and send it; once a day unless `again`.

    Nothing changes when the sender fails (ReportError). After it went out, a problem with the
    archive comes back as the result's warning: the report must not go out a second time.
    `now` is timezone-aware; a day is a day in its timezone.
    """
    _require_aware(now)
    hub = Path(hub).absolute()
    with apps.hub_lock(hub):
        before = last_sent(load_state(hub), period)
        if not again and before is not None and before.astimezone(now.tzinfo).date() == now.date():
            return SendResult("already", 0, 0, None, None)
        built = build(hub, period, now, runner=runner)
        if not built.text:
            record_run(hub, period, now, sent=False)
            clear_drafts(hub, period)
            return SendResult("empty", 0, 0, None, None)
        (sender if sender is not None else cc_connect_sender())(built.text)
        archive: str | None = None
        try:
            archive = _archive(hub, period, now, built.text)
        except OSError as exc:
            warning: str | None = f"report not archived: {exc}"
        else:
            warning = gitops.commit_paths(hub, [archive], f"cc-hub: report {period}")
        for written_for, count in built.included.items():
            drop_notes(hub, written_for, count)  # the first ones: later notes stay
        clear_drafts(hub, period)
        record_run(hub, period, now, sent=True)
        return SendResult("sent", built.sections, built.notes, archive, warning)


def add_routed_note(hub: Path, period: str, source: str, text: str, now: datetime) -> str | None:
    """Store a note for the `period` report; returns the report that will carry it.

    That is the first report from `period` up that is on, and None, with nothing stored, when
    none is. The note stays under `period`: `build` of the report it routes to picks it up.
    """
    _require_aware(now)
    hub = Path(hub).absolute()
    with apps.hub_lock(hub):
        target = note_target(hub, period)
        if target is not None:
            add_note(hub, period, source, text, now)
        return target
