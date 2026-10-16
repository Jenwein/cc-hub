# -*- coding: utf-8 -*-
"""Apps: app.toml, installing from taps, setup state, update, remove and sync."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import tomllib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import tomli_w

from cc_hub import __version__, cronoverrides, gitops, manifest, reports, reportstate, taps
from cc_hub.applock import (
    LOCK_FILE,
    Lock,
    LockError,
    from_tilde,
    load_lock,
    save_lock,
    to_tilde,
)
from cc_hub.commands.link import POINTERS, sync_skill_links
from cc_hub.crontasks import CronError, TaskDef, parse_task
from cc_hub.encoding import read_text, write_text
from cc_hub.hub import HUB_FILE, hub_name
from cc_hub.platform import LinkError, is_link, is_windows, link_dir, remove_link, rmtree
from cc_hub.reports import NOT_A_PERIOD, PERIODS, ReportError, SectionDef, parse_section
from cc_hub.tomltables import edit_table

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION = re.compile(r"^\d+(?:\.\d+){0,2}$")
NAME_RULE = (
    "lowercase letters, digits and hyphens, starting with a letter or digit, "
    "at most 64 characters"
)


class AppError(Exception):
    pass


def check_name(name: str, what: str, *, skill: bool = False) -> str:
    if not NAME.match(name) or (skill and name.startswith("hub-")):
        rule = NAME_RULE + (", not starting with 'hub-'" if skill else "")
        raise AppError(f"{what} {name!r}: use {rule}")
    return name


def version_tuple(text: str) -> tuple[int, int, int]:
    if not VERSION.match(text):
        raise AppError(f"{text!r} is not a version like 0.4.0")
    parts = [int(p) for p in text.split(".")] + [0, 0]
    return (parts[0], parts[1], parts[2])


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


@dataclass
class Requirement:
    name: str
    bin: str
    install: str | dict[str, str] | None = None

    def install_line(self, platform: str | None = None) -> str | None:
        if isinstance(self.install, dict):
            return self.install.get(platform or platform_key())
        return self.install


@dataclass
class AppManifest:
    name: str
    version: str
    description: str
    min_hub: str | None = None
    issues: str | None = None
    data_dirs: list[str] = field(default_factory=list)
    requires: list[Requirement] = field(default_factory=list)


def reserved_names() -> set[str]:
    firsts = {rel.split("/")[0] for rel in manifest.all_templates()}
    extra = {*manifest.USER_DIRS, "apps", LOCK_FILE, "secrets", "CLAUDE.md", "reports"}
    return {name.casefold() for name in firsts | extra}


_WINDOWS_DEVICE = re.compile(
    r"\s*(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\s*(?:\.|\Z)", re.IGNORECASE
)


def _windows_unsafe(part: str) -> bool:
    """True for a path part Windows would strip, refuse, or read as a device."""
    return (
        part.endswith((".", " "))
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in part)
        or _WINDOWS_DEVICE.match(part) is not None
    )


# "~" is left out on purpose: NTFS answers to 8.3 short names such as GIT~1 for .git.
DATA_DIR_PART = re.compile(r"[A-Za-z0-9._-]+")


def normalize_data_dir(raw: str) -> str:
    path = PurePosixPath(raw)
    parts = raw.split("/")
    if (
        not raw
        or "\\" in raw
        or re.search(r'[:*?"<>|]', raw)
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise AppError(f"data dir {raw!r}: use a relative path inside the hub, with / separators")
    if not all(DATA_DIR_PART.fullmatch(part) for part in parts):
        raise AppError(
            f"data dir {raw!r}: every part may use only the ASCII letters, digits, "
            "'.', '_' and '-'"
        )
    if any(_windows_unsafe(part) for part in parts):
        raise AppError(
            f"data dir {raw!r}: no part may end with a dot or space, hold a control "
            "character, or be a Windows device name"
        )
    first = path.parts[0]
    if first.startswith(".") or first.casefold() in reserved_names():
        raise AppError(f"data dir {raw!r}: {first!r} belongs to the hub itself")
    if any(part.startswith(".") for part in parts):
        raise AppError(f"data dir {raw!r}: no part may start with a dot")
    return path.as_posix()


def _parts(rel: str) -> tuple[str, ...]:
    return PurePosixPath(rel.casefold()).parts


def overlaps(a: str, b: str) -> bool:
    pa, pb = _parts(a), _parts(b)
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]


def inside(rel: str, directory: str) -> bool:
    pr, pd = _parts(rel), _parts(directory)
    return len(pr) > len(pd) and pr[: len(pd)] == pd


def check_entry_path(rel: str) -> None:
    parts = rel.split("/")
    if (
        "\\" in rel
        or ":" in rel
        or "~" in rel  # an 8.3 short name such as GIT~1 is another name for .git
        or any(p in ("", ".", "..") or p.casefold() == ".git" for p in parts)
        or any(_windows_unsafe(p) for p in parts)
    ):
        raise AppError(f"unsafe path in the app: {rel!r}")


PLATFORMS = ("linux", "macos", "windows")


def _install(value: object, *, label: str, where: str) -> str | dict[str, str] | None:
    if value is None:
        return None
    shape = f"{where}: {label}: install must be a non-empty string or a table"
    if isinstance(value, str):
        if not value.strip():
            raise AppError(shape)
        return value.strip()
    if not isinstance(value, dict):
        raise AppError(shape)
    unknown = sorted(set(value) - set(PLATFORMS))
    if unknown:
        raise AppError(
            f"{where}: {label}: install keys must be linux, macos or windows, not {unknown}"
        )
    for key, line in value.items():
        if not isinstance(line, str) or not line.strip():
            raise AppError(f"{where}: {label}: install.{key} must be a non-empty string")
    return {key: line.strip() for key, line in value.items()}


def _requirement(item: object, *, where: str, number: int) -> Requirement:
    if not (
        isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("bin"), str)
    ):
        raise AppError(f"{where}: every [[requires]] needs name and bin")
    name, bin_ = item["name"].strip(), item["bin"].strip()
    label = f"requirement {name!r}" if name else f"requirement #{number}"
    for field_name, value in (("name", name), ("bin", bin_)):
        if not value:
            raise AppError(f"{where}: {label}: {field_name} must not be empty")
    return Requirement(name, bin_, _install(item.get("install"), label=label, where=where))


def parse_manifest(text: str, *, dirname: str) -> AppManifest:
    where = f"{dirname}/app.toml"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AppError(f"{where}: {exc}") from exc
    app = data.get("app")
    if not isinstance(app, dict):
        raise AppError(f"{where}: missing [app] table")
    for key in ("name", "version", "description"):
        if not isinstance(app.get(key), str) or not app[key].strip():
            raise AppError(f"{where}: [app] {key} is required")
    if app["name"] != dirname:
        raise AppError(f"{where}: name {app['name']!r} must equal the directory name {dirname!r}")
    check_name(app["name"], "app name")
    min_hub = app.get("min_hub")
    if min_hub is not None:
        version_tuple(str(min_hub))
    data_table = data.get("data", {})
    if not isinstance(data_table, dict):
        raise AppError(f"{where}: [data] must be a table")
    dirs = data_table.get("dirs", [])
    if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
        raise AppError(f"{where}: [data] dirs must be a list of paths")
    raw_requires = data.get("requires", [])
    if not isinstance(raw_requires, list):
        raise AppError(f"{where}: [[requires]] must be a list of tables")
    requires = [
        _requirement(item, where=where, number=i) for i, item in enumerate(raw_requires, 1)
    ]
    data_dirs = [normalize_data_dir(d) for d in dirs]
    for i, a in enumerate(data_dirs):
        for b in data_dirs[i + 1 :]:
            if overlaps(a, b):
                raise AppError(f"{where}: data dirs {a!r} and {b!r} overlap")
    issues = app.get("issues")
    return AppManifest(
        name=app["name"],
        version=app["version"],
        description=app["description"].strip(),
        min_hub=str(min_hub) if min_hub is not None else None,
        issues=issues if isinstance(issues, str) else None,
        data_dirs=data_dirs,
        requires=requires,
    )


def parse_cron(text: str, *, where: str) -> TaskDef:
    try:
        return parse_task(text, where=where)
    except CronError as exc:
        raise AppError(str(exc)) from exc


def parse_report(text: str, *, where: str) -> SectionDef:
    try:
        return parse_section(text, where=where)
    except ReportError as exc:
        raise AppError(str(exc)) from exc


HUB_ERRORS: tuple[type[Exception], ...] = (
    AppError, taps.TapError, LockError, gitops.GitError, LinkError, OSError,
)
STATE_FILE = ".cc-hub/apps-state.toml"


class GitSource:
    """An app at a commit of a tap."""

    def __init__(self, tap: str, repo: Path, commit: str, app: str) -> None:
        self.tap, self.repo, self.commit, self.app = tap, Path(repo), commit, app
        self.entries = taps.ls_app(self.repo, commit, app)
        self._sha = {e.path: e.sha for e in self.entries}

    def paths(self) -> list[str]:
        return sorted(self._sha)

    def read(self, rel: str) -> bytes:
        return taps.read_blob(self.repo, self._sha[rel])

    def validate(self) -> None:
        seen: dict[str, str] = {}
        for e in self.entries:
            if e.kind != "blob" or e.mode == "120000":
                raise AppError(
                    f"{self.app}/{e.path}: only regular files are allowed "
                    "(no symlinks or submodules)"
                )
            check_entry_path(e.path)
            other = seen.setdefault(e.path.casefold(), e.path)
            if other != e.path:
                raise AppError(
                    f"{self.app}: {other!r} and {e.path!r} differ only in case; "
                    "they would overwrite each other on Windows and macOS"
                )

    def write_to(self, dest: Path) -> None:
        for e in self.entries:
            target = dest / e.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(taps.read_blob(self.repo, e.sha))
            if e.mode == "100755" and not is_windows():
                target.chmod(target.stat().st_mode | 0o111)

    def describe(self) -> str:
        return f"{self.tap}@{self.commit[:7]}"


class DirSource:
    """An app in a local directory, linked rather than copied."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().absolute()
        if not (self.root / "app.toml").is_file():
            raise AppError(f"{self.root}: no app.toml")
        self.app = self.root.name

    def paths(self) -> list[str]:
        out = []
        for p in self.root.rglob("*"):
            rel = p.relative_to(self.root)
            if p.is_file() and ".git" not in rel.parts:
                out.append(rel.as_posix())
        return sorted(out)

    def read(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    def validate(self) -> None:
        """The user's own working copy is linked as it is."""

    def describe(self) -> str:
        return f"link {to_tilde(self.root)}"


@dataclass
class AppPlan:
    manifest: AppManifest
    source: GitSource | DirSource
    skills: list[str]
    crons: dict[str, TaskDef]
    scripts: list[str]
    seed: list[str]  # hub-relative paths
    has_setup: bool
    has_remove: bool
    reports: dict[str, SectionDef] = field(default_factory=dict)  # period -> the app's section


def read_installed(hub: Path, name: str) -> AppManifest | None:
    try:
        return parse_manifest(read_text(Path(hub) / "apps" / name / "app.toml"), dirname=name)
    except (OSError, UnicodeDecodeError, AppError):
        return None


def _installed_skills(hub: Path, lock: Lock, *, exclude: str) -> set[str]:
    hub = Path(hub)
    roots = [hub / "skills"] + [hub / "apps" / a / "skills" for a in lock.apps if a != exclude]
    return {
        p.name
        for root in roots
        if root.is_dir()
        for p in root.iterdir()
        if (p / "SKILL.md").is_file()
    }


def build_plan(hub: Path, lock: Lock, source, *, replacing: str | None = None) -> AppPlan:
    source.validate()
    paths = source.paths()
    try:
        text = source.read("app.toml").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError(f"{source.app}/app.toml is not UTF-8") from exc
    m = parse_manifest(text, dirname=source.app)
    if m.min_hub and version_tuple(__version__) < version_tuple(m.min_hub):
        raise AppError(f"{m.name} needs cc-hub {m.min_hub} or newer; run `uv tool upgrade cc-hub`")
    if replacing is None and m.name in lock.apps:
        raise AppError(f"{m.name} is already installed; use `cc-hub app update {m.name}`")
    skills = sorted({p.split("/")[1] for p in paths if re.fullmatch(r"skills/[^/]+/SKILL\.md", p)})
    for skill in skills:
        check_name(skill, "skill name", skill=True)
    clash = sorted(set(skills) & _installed_skills(hub, lock, exclude=m.name))
    if clash:
        raise AppError(f"skill name already used in this hub: {', '.join(clash)}")
    for other in lock.apps:
        theirs = read_installed(hub, other) if other != m.name else None
        for mine in m.data_dirs:
            for dir_ in theirs.data_dirs if theirs else []:
                if overlaps(mine, dir_):
                    raise AppError(f"data dir {mine!r} overlaps {dir_!r} of {other}")
    seed = []
    for p in paths:
        if p.startswith("seed/"):
            rel = p[len("seed/") :]
            if not any(inside(rel, d) for d in m.data_dirs):
                raise AppError(f"{m.name}/seed/{rel}: not inside a data dir declared in app.toml")
            seed.append(rel)
    crons = {}
    for p in paths:
        if re.fullmatch(r"cron/[^/]+\.md", p):
            task = p[len("cron/") : -len(".md")]
            check_name(task, "cron task")
            try:
                cron_text = source.read(p).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AppError(f"{m.name}/{p} is not UTF-8") from exc
            crons[task] = parse_cron(cron_text, where=f"{m.name}/{p}")
    sections = {}
    for p in paths:
        if re.fullmatch(r"reports/[^/]+\.md", p) and p != "reports/README.md":
            period = p[len("reports/") : -len(".md")]
            if period not in PERIODS:
                raise AppError(f"{m.name}/{p}: {period} {NOT_A_PERIOD}")
            try:
                section_text = source.read(p).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AppError(f"{m.name}/{p} is not UTF-8") from exc
            sections[period] = parse_report(section_text, where=f"{m.name}/{p}")
    scripts = [p for p in paths if p.startswith("scripts/")]
    return AppPlan(
        m, source, skills, crons, scripts, seed, "SETUP.md" in paths, "REMOVE.md" in paths,
        sections,
    )


def tap_source(
    hub: Path, lock: Lock, tap: str, app: str, ref: str | None, *, fetch: bool
) -> GitSource:
    entry = lock.taps.get(tap)
    if entry is None:
        raise AppError(f"no tap named {tap!r}; add it with `cc-hub tap add`")
    repo = taps.repo_path(hub, tap, entry)
    if "url" in entry:
        if not taps.is_clone(repo):
            taps.clone(entry["url"], repo)
        elif fetch:
            taps.fetch(repo, entry["url"])
    elif not repo.exists():
        raise AppError(f"tap {tap}: {entry['path']} does not exist")
    commit = taps.resolve(repo, ref or taps.default_ref(entry), remote="url" in entry)
    return GitSource(tap, repo, commit, app)


def plan_install(
    hub: Path, spec: str, *, ref: str | None = None, link: bool = False, fetch: bool = True
) -> AppPlan:
    hub = Path(hub)
    lock = load_lock(hub)
    if link:
        return build_plan(hub, lock, DirSource(Path(spec)))
    tap, sep, app = spec.partition("/")
    if not sep or not tap or not app or "/" in app:
        raise AppError(f"{spec}: name an app as <tap>/<app>, or pass a directory with --link")
    return build_plan(hub, lock, tap_source(hub, lock, tap, app, ref, fetch=fetch))


@contextmanager
def hub_lock(hub: Path, *, stale_after: float = 600.0) -> Iterator[None]:
    """One tap or app command changes a hub at a time."""
    path = Path(hub) / ".cc-hub" / "op.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    for attempt in (0, 1):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > stale_after
            except OSError:
                stale = True
            if attempt == 0 and stale:
                path.unlink(missing_ok=True)
                continue
            raise AppError(
                "another cc-hub tap or app command is changing this hub; try again shortly"
            ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


@dataclass
class InstallResult:
    name: str
    version: str
    source: str
    seeded: list[str] = field(default_factory=list)
    missing: list[Requirement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _staging(hub: Path, name: str) -> Path:
    path = Path(hub) / ".cc-hub" / "tmp" / f"{name}-{uuid.uuid4().hex[:8]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _materialize(hub: Path, source: GitSource, dest: Path) -> None:
    """Write the app to a temporary directory, then move it to `dest` in one step."""
    source.validate()
    staging = _staging(hub, source.app)
    try:
        source.write_to(staging)
        os.rename(staging, dest)
    finally:
        if staging.exists():
            rmtree(staging)


def _seed(hub: Path, plan: AppPlan, only: set[str] | None = None) -> list[str]:
    hub = Path(hub)
    for d in plan.manifest.data_dirs:
        (hub / d).mkdir(parents=True, exist_ok=True)
        first = d.split("/")[0]
        real = Path(os.path.realpath(hub / first))  # expands 8.3 short names on Windows
        if real.name.casefold() != first.casefold():
            raise AppError(f"data dir {d!r} resolves to {real}; refusing to write there")
    seeded = []
    for rel in plan.seed:
        dst = hub / rel
        if (only is not None and rel not in only) or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(plan.source.read(f"seed/{rel}"))
        seeded.append(rel)
    return seeded


def relink(hub: Path) -> list[str]:
    """Run `cc-hub link` again for every agent skills directory the hub has."""
    warnings = []
    for _, skills_dir in POINTERS.values():
        target = Path(hub) / skills_dir
        if not target.is_dir():
            continue
        try:
            for name, status in sync_skill_links(hub, target):
                if status == "blocked":
                    warnings.append(f"{skills_dir}/{name}: something else has this name")
        except LinkError as exc:
            warnings.append(str(exc))
    return warnings


def missing_requirements(m: AppManifest, which=shutil.which) -> list[Requirement]:
    return [r for r in m.requires if which(r.bin) is None]


def _discard(dest: Path) -> None:
    """Remove an app directory (or only the link to a linked one); never hides the real error."""
    try:
        if is_link(dest):
            remove_link(dest)
        elif os.path.lexists(dest):
            rmtree(dest)
    except (OSError, LinkError):
        pass


def install(hub: Path, plan: AppPlan) -> InstallResult:
    hub = Path(hub)
    m, source = plan.manifest, plan.source
    with hub_lock(hub):
        lock = load_lock(hub)
        if m.name in lock.apps:
            raise AppError(f"{m.name} is already installed")
        dest = hub / "apps" / m.name
        if os.path.lexists(dest):
            raise AppError(f"{dest} exists but is not in apps.lock; move it away first")
        dest.parent.mkdir(exist_ok=True)
        if isinstance(source, DirSource):
            link_dir(source.root, dest)
            entry = {"link": to_tilde(source.root), "version": m.version}
        else:
            _materialize(hub, source, dest)
            entry = {"tap": source.tap, "commit": source.commit, "version": m.version}
        try:
            lock.apps[m.name] = entry
            seeded = _seed(hub, plan)
            save_lock(hub, lock)
        except BaseException:
            _discard(dest)  # no half-installed app; seeded data files stay, they are data
            raise
        warnings = relink(hub)
        warning = gitops.commit_paths(
            hub, [LOCK_FILE, *seeded], f"cc-hub: app install {m.name} ({source.describe()})"
        )
    return InstallResult(
        m.name, m.version, source.describe(), seeded, missing_requirements(m),
        warnings + ([warning] if warning else []),
    )


def load_state(hub: Path) -> dict:
    path = Path(hub) / STATE_FILE
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(read_text(path))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def save_state(hub: Path, state: dict) -> None:
    write_text(Path(hub) / STATE_FILE, tomli_w.dumps(state))


def fingerprint(app_dir: Path) -> str:
    """Hash of what setup depends on: SETUP.md, the requires of app.toml, the cron tasks and the
    report sections."""
    h = hashlib.sha256()
    setup = app_dir / "SETUP.md"
    h.update(b"setup\0" + (setup.read_bytes() if setup.is_file() else b""))
    requires = tomllib.loads(read_text(app_dir / "app.toml")).get("requires", [])
    h.update(b"requires\0" + json.dumps(requires, sort_keys=True).encode("utf-8"))
    cron = app_dir / "cron"
    for p in sorted(cron.glob("*.md")) if cron.is_dir() else []:
        h.update(b"cron\0" + p.name.encode("utf-8") + b"\0" + p.read_bytes())
    section_dir = app_dir / "reports"
    for p in sorted(section_dir.glob("*.md")) if section_dir.is_dir() else []:
        h.update(b"reports\0" + p.name.encode("utf-8") + b"\0" + p.read_bytes())
    return h.hexdigest()


def setup_status(hub: Path, name: str) -> tuple[str, str]:
    """(pending | waiting | done, note) for an installed app on this machine."""
    entry = load_state(hub).get(name)
    try:
        current = fingerprint(Path(hub) / "apps" / name)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return "pending", ""
    if not entry or entry.get("fingerprint") != current:
        return "pending", ""
    return entry.get("state", "pending"), entry.get("note", "")


def set_setup_state(hub: Path, name: str, state: str, note: str = "") -> None:
    if state not in ("done", "waiting"):
        raise AppError("state must be done or waiting")
    if name not in load_lock(hub).apps:
        raise AppError(f"{name} is not installed")
    try:
        current = fingerprint(Path(hub) / "apps" / name)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AppError(f"{name}: cannot read the installed app: {exc}") from exc
    states = load_state(hub)
    states[name] = {"state": state, "note": note, "fingerprint": current}
    save_state(hub, states)


@dataclass
class AppStatus:
    name: str
    version: str
    source: str
    present: bool
    setup: str
    note: str
    missing: list[dict]
    update: bool | None
    min_hub_ok: bool


def _update_available(hub: Path, lock: Lock, name: str, entry: dict) -> bool | None:
    tap_entry = lock.taps.get(entry.get("tap", ""))
    if "link" in entry or tap_entry is None:
        return None
    repo = taps.repo_path(hub, entry["tap"], tap_entry)
    try:
        head = taps.resolve(repo, taps.default_ref(tap_entry), remote="url" in tap_entry)
        if head == entry["commit"]:
            return False
        return bool(taps.changed_files(repo, entry["commit"], head, name))
    except (taps.TapError, gitops.GitError, OSError):
        return None


def app_statuses(hub: Path, *, which=shutil.which) -> list[AppStatus]:
    hub = Path(hub)
    lock = load_lock(hub)
    rows = []
    for name, entry in sorted(lock.apps.items()):
        m = read_installed(hub, name)
        if "link" in entry:
            source = f"link {entry['link']}"
        else:
            source = f"{entry.get('tap')}@{str(entry.get('commit', ''))[:7]}"
        setup, note = setup_status(hub, name) if m else ("pending", "")
        missing = [
            {"name": r.name, "bin": r.bin, "install": r.install_line()}
            for r in (missing_requirements(m, which) if m else [])
        ]
        min_ok = not (m and m.min_hub) or version_tuple(__version__) >= version_tuple(m.min_hub)
        rows.append(AppStatus(
            name, str(entry.get("version", "?")), source, m is not None, setup, note,
            missing, _update_available(hub, lock, name, entry), min_ok,
        ))
    return rows


def add_tap(
    hub: Path, source: str, *, name: str | None = None, cwd: Path | None = None
) -> tuple[str, dict, int, str | None]:
    entry = taps.normalize_source(source, cwd=cwd)
    if "url" in entry and taps.strip_credentials(entry["url"]) != entry["url"]:
        raise AppError(
            "the tap URL contains credentials; remove them and use a git credential helper"
        )
    name = check_name(name or taps.default_name(entry), "tap name")
    hub = Path(hub)
    with hub_lock(hub):
        lock = load_lock(hub)
        if name in lock.taps:
            raise AppError(f"a tap named {name!r} is already registered")
        repo = taps.repo_path(hub, name, entry)
        if "url" in entry:
            taps.clone(entry["url"], repo)
        head = taps.resolve(repo, taps.default_ref(entry), remote="url" in entry)
        count = len(taps.list_apps(repo, head))
        lock.taps[name] = entry
        save_lock(hub, lock)
        warning = gitops.commit_paths(hub, [LOCK_FILE], f"cc-hub: tap add {name}")
    return name, entry, count, warning


def remove_tap(hub: Path, name: str) -> str | None:
    hub = Path(hub)
    with hub_lock(hub):
        lock = load_lock(hub)
        if name not in lock.taps:
            raise AppError(f"no tap named {name!r}")
        users = sorted(a for a, e in lock.apps.items() if e.get("tap") == name)
        if users:
            raise AppError(f"apps installed from {name}: {', '.join(users)}; remove them first")
        entry = lock.taps.pop(name)
        clone = taps.clone_dir(hub, name)
        if "url" in entry and clone.exists():
            rmtree(clone)
        save_lock(hub, lock)
        return gitops.commit_paths(hub, [LOCK_FILE], f"cc-hub: tap remove {name}")


def tap_infos(hub: Path) -> list[dict]:
    lock = load_lock(hub)
    rows = []
    for name, entry in sorted(lock.taps.items()):
        repo = taps.repo_path(hub, name, entry)
        try:
            head = taps.resolve(repo, taps.default_ref(entry), remote="url" in entry)
            count = len(taps.list_apps(repo, head))
        except (taps.TapError, gitops.GitError, OSError):
            count = 0
        rows.append({"name": name, "source": taps.describe(entry), "apps": count})
    return rows


def search_apps(hub: Path, words: str = "") -> list[dict]:
    lock = load_lock(hub)
    needle = words.casefold().strip()
    rows = []
    for tap, entry in sorted(lock.taps.items()):
        repo = taps.repo_path(hub, tap, entry)
        try:
            commit = taps.resolve(repo, taps.default_ref(entry), remote="url" in entry)
            names = taps.list_apps(repo, commit)
        except (taps.TapError, gitops.GitError, OSError):
            continue
        for app in names:
            try:
                text = taps.read_blob(repo, f"{commit}:{app}/app.toml").decode("utf-8")
                m = parse_manifest(text, dirname=app)
            except (AppError, gitops.GitError, UnicodeDecodeError):
                continue
            if needle and needle not in f"{app} {m.description}".casefold():
                continue
            rows.append({
                "app": f"{tap}/{app}", "version": m.version,
                "description": m.description, "installed": app in lock.apps,
            })
    return rows


STEERING = ("app.toml", "SETUP.md", "REMOVE.md")
STEERING_DIRS = ("skills/", "scripts/", "cron/", "reports/")


@dataclass
class UpdatePreview:
    name: str
    old: str
    new: str
    changed: list[tuple[str, str]]
    diff: str
    new_requires: list[str]
    local_changes: list[str]
    history_missing: bool
    plan: AppPlan


def local_changes(hub: Path, name: str, repo: Path, commit: str) -> list[str]:
    """Files under apps/<name>/ that differ from the app at `commit`."""
    app_dir = Path(hub) / "apps" / name
    expected = {e.path: e.sha for e in taps.ls_app(repo, commit, name)}
    actual = {p.relative_to(app_dir).as_posix(): p for p in app_dir.rglob("*") if p.is_file()}
    changed = {
        rel for rel, sha in expected.items()
        if rel not in actual or taps.blob_sha(actual[rel].read_bytes()) != sha
    }
    return sorted(changed | (set(actual) - set(expected)))


def preview_update(
    hub: Path, name: str, *, ref: str | None = None, fetch: bool = True
) -> UpdatePreview | None:
    """What `app update` would change, changing nothing; None for a linked app."""
    hub = Path(hub)
    lock = load_lock(hub)
    entry = lock.apps.get(name)
    if entry is None:
        raise AppError(f"{name} is not installed")
    if "link" in entry:
        return None
    source = tap_source(hub, lock, entry["tap"], name, ref, fetch=fetch)
    plan = build_plan(hub, lock, source, replacing=name)
    old, new = entry["commit"], source.commit
    current = read_installed(hub, name)
    old_requires = {r.name for r in current.requires} if current else set()
    history = taps.has_commit(source.repo, old)
    if history:
        changed = taps.changed_files(source.repo, old, new, name)
        steering = [p for _, p in changed if p in STEERING or p.startswith(STEERING_DIRS)]
        diff = taps.diff_text(source.repo, old, new, name, steering)
        app_dir = hub / "apps" / name
        local = local_changes(hub, name, source.repo, old) if app_dir.is_dir() else []
    else:
        changed, diff, local = [("A", p) for p in source.paths()], "", []
    new_requires = [r.name for r in plan.manifest.requires if r.name not in old_requires]
    return UpdatePreview(name, old, new, changed, diff, new_requires, local, not history, plan)


def apply_update(hub: Path, preview: UpdatePreview) -> InstallResult:
    hub = Path(hub)
    name, plan = preview.name, preview.plan
    with hub_lock(hub):
        lock = load_lock(hub)
        entry = lock.apps.get(name)
        if entry is None or entry.get("commit") != preview.old:
            raise AppError(
                f"{name} changed since the preview; run `cc-hub app update {name}` again"
            )
        app_dir = hub / "apps" / name
        backup = hub / ".cc-hub" / "backups" / "apps" / name / preview.old[:7]
        try:
            # the first backup of this commit holds the pre-update state; never overwrite it
            if app_dir.exists() and not backup.exists():
                try:
                    shutil.copytree(app_dir, backup)
                except BaseException:
                    if backup.exists():
                        rmtree(backup)  # no half-copied backup that a retry would keep
                    raise
        except OSError as exc:
            raise AppError(f"backup failed, nothing was changed: {exc}") from exc
        seed_dir = app_dir / "seed"
        old_seed = (
            {p.relative_to(seed_dir).as_posix() for p in seed_dir.rglob("*") if p.is_file()}
            if seed_dir.is_dir() else set()
        )
        retired = _staging(hub, f"{name}-old")
        if app_dir.exists():
            os.rename(app_dir, retired)
        try:
            _materialize(hub, plan.source, app_dir)
            seeded = _seed(hub, plan, only=set(plan.seed) - old_seed)
            entry.update(commit=preview.new, version=plan.manifest.version)
            save_lock(hub, lock)
        except BaseException:
            # apps.lock still names the old commit: put the old tree back
            _discard(app_dir)
            if retired.exists():
                os.rename(retired, app_dir)
            raise
        if retired.exists():
            try:
                rmtree(retired)
            except OSError:
                pass
        warnings = relink(hub)
        warning = gitops.commit_paths(
            hub, [LOCK_FILE, *seeded],
            f"cc-hub: app update {name} ({preview.old[:7]}..{preview.new[:7]})",
        )
    return InstallResult(
        name, plan.manifest.version, plan.source.describe(), seeded,
        missing_requirements(plan.manifest), warnings + ([warning] if warning else []),
    )


@dataclass
class RemovePlan:
    name: str
    linked: bool
    data_dirs: list[str]
    cron_tasks: list[str]
    software: list[Requirement]
    remove_md: str
    overrides: list[str] = field(default_factory=list)  # keys of hub.toml's [cron."<app>/<task>"]
    report_settings: list[str] = field(default_factory=list)  # [report."<app>/<period>"] keys


def _override_keys(hub: Path, app: str) -> list[str]:
    """The tasks of `app` that hub.toml holds a [cron."<app>/<task>"] override for."""
    return sorted(key for key in cronoverrides.load(hub) if key.startswith(f"{app}/"))


def plan_remove(hub: Path, name: str) -> RemovePlan:
    hub = Path(hub)
    entry = load_lock(hub).apps.get(name)
    if entry is None:
        raise AppError(f"{name} is not installed")
    app_dir = hub / "apps" / name
    m = read_installed(hub, name)
    cron = app_dir / "cron"
    tasks = sorted(p.stem for p in cron.glob("*.md")) if cron.is_dir() else []
    try:
        remove_md = (app_dir / "REMOVE.md").read_bytes().decode("utf-8", errors="replace")
    except OSError:
        remove_md = ""
    try:
        overrides = _override_keys(hub, name)
    except (OSError, ValueError, CronError):
        overrides = []  # an unreadable hub.toml is for doctor to report, not a reason to refuse
    try:
        report_settings = reports.section_keys_of(hub, name)
    except (OSError, ValueError, ReportError):
        report_settings = []
    return RemovePlan(
        name, "link" in entry, m.data_dirs if m else [], [f"hub:{name}/{t}" for t in tasks],
        m.requires if m else [], remove_md, overrides, report_settings,
    )


def _drop_overrides(hub: Path, app: str) -> tuple[bool, str | None]:
    """Remove `app`'s overrides from hub.toml: whether it changed, and a warning if it could not.

    The new text is worked out in full before anything is written, so hub.toml either loses all
    of them or none.
    """
    try:
        keys = _override_keys(hub, app)
        if not keys:
            return False, None
        path = Path(hub) / HUB_FILE
        old = path.read_bytes().decode("utf-8")  # read_text would turn CRLF into LF
        new = old
        for key in keys:
            new = cronoverrides.apply(new, key, None)
        write_text(path, new)
    except FileNotFoundError:
        return False, None
    except (OSError, ValueError, CronError) as exc:
        return False, (
            f"{HUB_FILE}: could not drop the overrides of {app}'s tasks ({exc}); "
            f'delete any [cron."{app}/<task>"] tables by hand'
        )
    return True, None


def _drop_report_settings(hub: Path, app: str) -> tuple[bool, str | None]:
    """Remove `app`'s [report."<app>/<period>"] tables from hub.toml, as `_drop_overrides` does.

    The new text is worked out in full before anything is written, so hub.toml either loses all
    of them or none.
    """
    try:
        keys = reports.section_keys_of(hub, app)
        if not keys:
            return False, None
        path = Path(hub) / HUB_FILE
        old = path.read_bytes().decode("utf-8")  # read_text would turn CRLF into LF
        new = old
        for key in keys:
            new = edit_table(new, ("report", key), None)
        write_text(path, new)
    except FileNotFoundError:
        return False, None
    except (OSError, ValueError, ReportError) as exc:
        return False, (
            f"{HUB_FILE}: could not drop the report settings of {app}'s sections ({exc}); "
            f'delete any [report."{app}/<period>"] tables by hand'
        )
    return True, None


def _forget_report_state(hub: Path, app: str) -> str | None:
    """Drop the approvals and drafts of `app`'s report sections; a warning when that fails."""
    try:
        with reportstate.state_lock(hub):
            reportstate.forget_app(hub, app)
    except (OSError, ValueError) as exc:  # a busy state is a TimeoutError, which is an OSError
        return (
            f"{app}: could not forget the approvals and drafts of its report sections ({exc}); "
            f"they stay in {reportstate.STATE_DIR}"
        )
    return None


def apply_remove(hub: Path, name: str) -> list[str]:
    hub = Path(hub)
    with hub_lock(hub):
        lock = load_lock(hub)
        if lock.apps.pop(name, None) is None:
            raise AppError(f"{name} is not installed")
        app_dir = hub / "apps" / name
        if is_link(app_dir):
            remove_link(app_dir)
        elif app_dir.exists():
            rmtree(app_dir)
        save_lock(hub, lock)
        states = load_state(hub)
        if states.pop(name, None) is not None:
            save_state(hub, states)
        warnings = relink(hub)
        paths = [LOCK_FILE]
        overrides_changed, dropped = _drop_overrides(hub, name)
        settings_changed, dropped_settings = _drop_report_settings(hub, name)
        if overrides_changed or settings_changed:
            paths.append(HUB_FILE)  # only then: the user's other edits to hub.toml stay theirs
        warning = gitops.commit_paths(hub, paths, f"cc-hub: app remove {name}")
        forgotten = _forget_report_state(hub, name)
    return warnings + [w for w in (dropped, dropped_settings, warning, forgotten) if w]


@dataclass
class SyncReport:
    restored: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    strays: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _restore(hub: Path, lock: Lock, name: str, entry: dict, dest: Path) -> None:
    if "link" in entry:
        src = from_tilde(entry["link"])
        if not src.is_dir():
            raise AppError(f"link source {entry['link']} does not exist on this machine")
        link_dir(src, dest)
        return
    tap_entry = lock.taps.get(entry.get("tap", ""))
    if tap_entry is None:
        raise AppError(f"tap {entry.get('tap')!r} is not registered")
    repo = taps.repo_path(hub, entry["tap"], tap_entry)
    if "url" in tap_entry:
        if not taps.is_clone(repo):
            taps.clone(tap_entry["url"], repo)
        elif not taps.has_commit(repo, entry["commit"]):
            taps.fetch(repo, tap_entry["url"])
    if not taps.has_commit(repo, entry["commit"]):
        raise AppError(f"commit {entry['commit'][:7]} is no longer in tap {entry['tap']}")
    _materialize(hub, GitSource(entry["tap"], repo, entry["commit"], name), dest)


def sync(hub: Path) -> SyncReport:
    """Make apps/ match apps.lock: restore what is missing, upgrade nothing."""
    hub = Path(hub)
    report = SyncReport()
    with hub_lock(hub):
        if gitops.is_repo(hub):
            try:  # the identity lives in .git/config, which a clone does not carry over
                gitops.ensure_identity(hub, hub_name(hub))
            except gitops.GitError as exc:
                report.warnings.append(f"could not set a git identity: {exc}")
        lock = load_lock(hub)
        apps_dir = hub / "apps"
        apps_dir.mkdir(exist_ok=True)
        for name, entry in sorted(lock.apps.items()):
            dest = apps_dir / name
            if os.path.lexists(dest):
                report.present.append(name)
                continue
            try:
                _restore(hub, lock, name, entry, dest)
                report.restored.append(name)
            except HUB_ERRORS as exc:
                report.failed.append((name, str(exc)))
        report.strays = sorted(p.name for p in apps_dir.iterdir() if p.name not in lock.apps)
        report.warnings += relink(hub)
    return report
