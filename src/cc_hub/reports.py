# -*- coding: utf-8 -*-
"""Reports: the sections apps add to them, and the report settings in hub.toml.

An app adds a section to a period's report with `apps/<app>/reports/<period>.md`: a command
that prints the section, or instructions for the agent to write it. The user switches single
sections off, picks the order of the apps and the language in the [report] table of hub.toml.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cc_hub import crontasks
from cc_hub.applock import LOCK_FILE, load_lock
from cc_hub.crontasks import NAME_RULE, TASK_NAME, CronError
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import HUB_FILE
from cc_hub.tomltables import CANNOT_EDIT, LINE, TableEditError, edit_table, header_path

# short to long: a note for a period that is not on goes to the next one that is
PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")
LANGUAGE_RULE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")

PERIOD_LIST = ", ".join(PERIODS)
NOT_A_PERIOD = f"is not a report period ({PERIOD_LIST})"
KEY_RULE = f"<app>/<period>, the period one of {PERIOD_LIST}"


class ReportError(Exception):
    pass


# --- section files ---


@dataclass(frozen=True)
class SectionDef:
    command: str | None  # a section with a command is printed by it; without, the agent writes it
    title: str | None


def parse_section(text: str, *, where: str) -> SectionDef:
    """Read one section file; ReportError (starting with `where`) if it is not valid."""
    try:
        fields = crontasks.read_frontmatter(text, where=where)
    except CronError as exc:
        raise ReportError(str(exc)) from None
    command = fields.get("command")
    if command is not None and not command.strip():
        raise ReportError(f"{where}: command is empty")
    return SectionDef(command, fields.get("title") or None)


@dataclass
class Section:
    app: str
    period: str
    file: str  # the section file, relative to the hub, with /
    definition: SectionDef | None
    error: str | None

    @property
    def key(self) -> str:
        return f"{self.app}/{self.period}"

    @property
    def kind(self) -> str | None:
        if self.definition is None:
            return None
        return "instruction" if self.definition.command is None else "command"

    @property
    def title(self) -> str:
        return (self.definition.title if self.definition else None) or self.app

    @property
    def command(self) -> str | None:
        return self.definition.command if self.definition else None


def _load(app: str, period: str, file: str, path: Path) -> Section:
    """One section; a file that cannot be used becomes a Section with `error`, not an exception."""
    if period not in PERIODS:
        return Section(app, period, file, None, f"{file}: {period} {NOT_A_PERIOD}")
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        return Section(app, period, file, None, f"{file}: is not UTF-8")
    except OSError as exc:
        return Section(app, period, file, None, f"{file}: cannot be read: {exc}")
    try:
        return Section(app, period, file, parse_section(text, where=file), None)
    except ReportError as exc:
        return Section(app, period, file, None, str(exc))


def discover_sections(hub: Path) -> list[Section]:
    """The sections of every installed app, by app name and then file name."""
    hub = Path(hub)
    sections: list[Section] = []
    for app in sorted(load_lock(hub).apps):
        if not TASK_NAME.fullmatch(app):
            error = f"{LOCK_FILE}: app name {app!r}: use {NAME_RULE}"
            sections.append(Section(app, "", LOCK_FILE, None, error))
            continue
        directory = hub / "apps" / app / "reports"
        if not directory.is_dir():
            continue
        files = sorted(
            p for p in directory.glob("*.md") if p.is_file() and p.name != "README.md"
        )
        for p in files:
            sections.append(_load(app, p.stem, f"apps/{app}/reports/{p.name}", p))
    return sections


# --- hub.toml: [report] ---


@dataclass
class ReportConfig:
    language: str | None
    order: list[str]
    off: set[str]  # section keys, <app>/<period>, the user switched off


def _split_key(key: str) -> tuple[str, str] | None:
    """(app, period) of a section key, or None when it is not `<app>/<period>`."""
    app, sep, period = key.partition("/")
    if not sep or not TASK_NAME.fullmatch(app) or period not in PERIODS:
        return None
    return app, period


def _read_toml(hub: Path) -> dict:
    try:
        return tomllib.loads(read_text(Path(hub) / HUB_FILE))
    except tomllib.TOMLDecodeError as exc:
        raise ReportError(f"{HUB_FILE} is not valid TOML: {exc}") from None


def _report_table(data: dict) -> dict:
    report = data.get("report", {})
    if not isinstance(report, dict):
        raise ReportError(f"{HUB_FILE}: [report] must be a table")
    return report


def load_config(hub: Path) -> ReportConfig:
    """The [report] settings of hub.toml; ReportError naming the key that cannot be used."""
    report = _report_table(_read_toml(hub))
    language: str | None = None
    order: list[str] = []
    off: set[str] = set()
    for key, value in report.items():
        if key == "language":
            if not isinstance(value, str) or not LANGUAGE_RULE.match(value):
                raise ReportError(
                    f'{HUB_FILE}: [report] language must be a language tag such as "en" or "zh-CN"'
                )
            language = value
        elif key == "order":
            if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
                raise ReportError(f"{HUB_FILE}: [report] order must be a list of app names")
            order = list(value)
        elif isinstance(value, dict):
            where = f'{HUB_FILE}: [report."{key}"]'
            if _split_key(key) is None:
                raise ReportError(f"{where}: the table name must be {KEY_RULE}")
            for name, setting in value.items():
                if name != "enabled":
                    raise ReportError(f"{where}: {name} is not a setting (enabled)")
                if not isinstance(setting, bool):
                    raise ReportError(f"{where}: enabled must be true or false")
            if value.get("enabled") is False:
                off.add(key)
        else:
            raise ReportError(
                f'{HUB_FILE}: [report] {key} is not a setting (language, order, '
                f'or a [report."<app>/<period>"] table)'
            )
    return ReportConfig(language, order, off)


def ordered(sections: list[Section], order: list[str]) -> list[Section]:
    """Sections of the apps named in `order` first, in that order, then the rest by app name."""
    rank: dict[str, int] = {}
    for app in order:
        rank.setdefault(app, len(rank))
    return sorted(sections, key=lambda s: (rank.get(s.app, len(rank)), s.app))


def _check_period(period: str) -> None:
    if period not in PERIODS:
        raise ReportError(f"{period} {NOT_A_PERIOD}")


def enabled_sections(hub: Path, period: str) -> list[Section]:
    """The sections that make up the `period` report: usable and not switched off, in order."""
    _check_period(period)
    config = load_config(hub)
    sections = [
        s
        for s in discover_sections(hub)
        if s.period == period and s.error is None and s.key not in config.off
    ]
    return ordered(sections, config.order)


# --- which periods are on ---


def periods_on(hub: Path) -> dict[str, bool]:
    """Per period: whether its report task (cron/report-<period>.md) is scheduled to run."""
    try:
        rows = {row["name"]: row for row in crontasks.rows(hub)}
    except CronError as exc:
        raise ReportError(str(exc)) from None
    on = {}
    for period in PERIODS:
        row = rows.get(f"report-{period}")
        on[period] = row is not None and row["error"] is None and bool(row["enabled"])
    return on


def note_target(hub: Path, period: str) -> str | None:
    """The report a note for `period` goes into: the first period from it up that is on."""
    _check_period(period)
    on = periods_on(hub)
    return next((p for p in PERIODS[PERIODS.index(period) :] if on[p]), None)


# --- writing hub.toml ---


def _where(path: tuple[str, ...]) -> str:
    return "[report]" if len(path) == 1 else f'[report."{path[1]}"]'


def _edit(text: str, path: tuple[str, ...], values: dict | None) -> str:
    try:
        return edit_table(text, path, values)
    except TableEditError as exc:
        if str(exc) == CANNOT_EDIT:
            raise ReportError(
                f"{HUB_FILE}: cannot edit {_where(path)} in place; edit it by hand"
            ) from None
        raise ReportError(f"{HUB_FILE}: {exc}") from None


def _rewrite(hub: Path, change: Callable[[str], str]) -> None:
    """Replace hub.toml by `change(its text)`; bytes are read so that CRLF endings survive."""
    path = Path(hub) / HUB_FILE
    old = path.read_bytes().decode("utf-8")
    new = change(old)
    if new != old:
        write_text(path, new)


def _own_keys(text: str, report: dict) -> dict:
    """What [report] holds itself: all of it but the tables that `[report."x"]` headers declare."""
    declared = set()
    for line in LINE.findall(text):
        found = header_path(line)
        if found is not None and len(found) > 1 and found[0] == "report":
            declared.add(found[1])
    return {k: v for k, v in report.items() if not (isinstance(v, dict) and k in declared)}


def save_language(hub: Path, tag: str) -> None:
    """Set `language` in [report], keeping its other keys and the section tables."""
    if not isinstance(tag, str) or not LANGUAGE_RULE.match(tag):
        raise ReportError(f'language must be a language tag such as "en" or "zh-CN", not {tag!r}')

    def change(text: str) -> str:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ReportError(f"{HUB_FILE} is not valid TOML: {exc}") from None
        own = _own_keys(text, _report_table(data))
        return _edit(text, ("report",), {**own, "language": tag})

    _rewrite(hub, change)


def save_section(hub: Path, key: str, on: bool) -> None:
    """Switch the section `key` (`<app>/<period>`) on, which removes its table, or off."""
    if not isinstance(key, str) or _split_key(key) is None:
        raise ReportError(f"{key!r} is not a section: use {KEY_RULE}")
    path = ("report", key)
    _rewrite(hub, lambda text: _edit(text, path, None if on else {"enabled": False}))


def section_keys_of(hub: Path, app: str) -> list[str]:
    """The section tables of `app` in [report], for removing them with the app."""
    report = _report_table(_read_toml(hub))
    return sorted(k for k, v in report.items() if isinstance(v, dict) and k.startswith(f"{app}/"))
