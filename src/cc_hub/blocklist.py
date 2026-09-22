# -*- coding: utf-8 -*-
"""Catastrophic-command blocklist used by `cc-hub hook pre-tool-use`."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    raw: str
    name: str
    args: list[str]


@dataclass(frozen=True)
class Rule:
    name: str
    scope: str  # "segment" | "command"
    test: Callable[..., bool]


SPLIT_RE = re.compile(r"\|\||&&|;|\||\n")
WRAPPERS = {"sudo", "doas", "nohup", "time", "command", "exec", "builtin", "env", "nice", "timeout"}
WRAPPER_OPTS_WITH_ARG = {"-u", "-g", "-p", "-n"}
ROOT_TARGETS = {
    "/", "/*", "~", "~/", "~/*", "$home", "$home/", "${home}", "${home}/", "/home", "/home/*",
    "$env:userprofile", "$env:userprofile\\", "$env:systemdrive", "$env:systemdrive\\",
}
ROOT_TARGET_RE = re.compile(
    r"^(?:[a-z]:[\\/]?\*?|/home/[^/]+/?|/users/[^/]+/?|c:\\users\\[^\\]+\\?)$"
)
DEVICE_REDIRECT = re.compile(r">\s*/dev/(?:sd|nvme|disk|hd|mmcblk|xvd)")
FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
PIPE_TO_SHELL = re.compile(
    r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:bash|sh|zsh|dash|fish)\b"
)
POWER = {"shutdown", "reboot", "poweroff", "halt", "stop-computer", "restart-computer"}
WIN_REMOVE = {"remove-item", "ri", "del", "erase", "rd", "rmdir"}
FORMAT = {"format", "format.com", "diskpart", "diskpart.exe"}
MAIN_REF = re.compile(r"^(?:.*:)?(?:refs/heads/)?(?:main|master)$")
PROTECTED_NAME = re.compile(r"^\.env(?:\..+)?$")


def normalize(command: str) -> str:
    return " ".join(command.split())


def split_segments(command: str) -> list[Segment]:
    segments: list[Segment] = []
    for part in SPLIT_RE.split(command):
        part = part.strip()
        if not part:
            continue
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            tokens = part.split()
        while tokens and (
            tokens[0] in WRAPPERS or ("=" in tokens[0] and not tokens[0].startswith("-"))
        ):
            head = tokens.pop(0)
            if head in ("sudo", "doas", "timeout", "nice", "env"):
                while tokens and tokens[0].startswith("-"):
                    opt = tokens.pop(0)
                    if opt in WRAPPER_OPTS_WITH_ARG and tokens:
                        tokens.pop(0)
                if head == "timeout" and tokens:
                    tokens.pop(0)  # the duration
        if not tokens:
            continue
        name = Path(tokens[0]).name.casefold()
        segments.append(Segment(raw=part, name=name, args=tokens[1:]))
    return segments


def _short_flags(args: list[str]) -> str:
    return "".join(
        a[1:] for a in args if a.startswith("-") and not a.startswith("--") and len(a) > 1
    )


def _recursive(args: list[str]) -> bool:
    if "--recursive" in args:
        return True
    lowered = [a.casefold() for a in args]
    if any(a in ("-recurse", "/s") or a.startswith("-recurse") for a in lowered):
        return True
    return any(ch in "rR" for ch in _short_flags(args))


def _targets(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-") and a.casefold() not in ("/s", "/q")]


def _is_root_target(target: str) -> bool:
    t = target.casefold()
    return t in ROOT_TARGETS or ROOT_TARGET_RE.match(t) is not None


def rule_rm_root(seg: Segment) -> bool:
    return (
        seg.name == "rm"
        and _recursive(seg.args)
        and any(_is_root_target(t) for t in _targets(seg.args))
    )


def rule_mkfs(seg: Segment) -> bool:
    return seg.name.startswith("mkfs")


def rule_dd_device(seg: Segment) -> bool:
    return seg.name == "dd" and any(a.startswith("of=/dev/") for a in seg.args)


def rule_power(seg: Segment) -> bool:
    if seg.name in POWER:
        return True
    return seg.name == "systemctl" and any(a in ("poweroff", "reboot", "halt") for a in seg.args)


def rule_force_push_main(seg: Segment) -> bool:
    if seg.name != "git" or "push" not in seg.args:
        return False
    force = any(a in ("-f", "--force") for a in seg.args)
    return force and any(MAIN_REF.match(a) for a in seg.args if not a.startswith("-"))


def rule_chmod_root(seg: Segment) -> bool:
    return seg.name in ("chmod", "chown", "chgrp") and _recursive(seg.args) and any(
        _is_root_target(t) for t in _targets(seg.args)
    )


def rule_win_remove_root(seg: Segment) -> bool:
    return seg.name in WIN_REMOVE and _recursive(seg.args) and any(
        _is_root_target(t) for t in _targets(seg.args)
    )


def rule_win_format(seg: Segment) -> bool:
    return seg.name in FORMAT


BUILTIN_RULES: tuple[Rule, ...] = (
    Rule("rm-root", "segment", rule_rm_root),
    Rule("mkfs", "segment", rule_mkfs),
    Rule("dd-device", "segment", rule_dd_device),
    Rule("redirect-device", "command", lambda text: DEVICE_REDIRECT.search(text) is not None),
    Rule("fork-bomb", "command", lambda text: FORK_BOMB.search(text) is not None),
    Rule("pipe-to-shell", "command", lambda text: PIPE_TO_SHELL.search(text) is not None),
    Rule("power", "segment", rule_power),
    Rule("force-push-main", "segment", rule_force_push_main),
    Rule("chmod-root", "segment", rule_chmod_root),
    Rule("win-remove-root", "segment", rule_win_remove_root),
    Rule("win-format", "segment", rule_win_format),
)


def match_command(command: str, extra: Iterable[str] = ()) -> str | None:
    text = normalize(command)
    if not text:
        return None
    segments = split_segments(text)
    for rule in BUILTIN_RULES:
        if rule.scope == "command":
            if rule.test(text):
                return rule.name
        elif any(rule.test(seg) for seg in segments):
            return rule.name
    for index, pattern in enumerate(extra):
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return f"extra:{index}"
        except re.error:
            continue
    return None


def is_protected_path(path: str, hub: Path) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(hub) / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    secrets = (Path(hub) / "secrets").resolve()
    if resolved == secrets or secrets in resolved.parents:
        return True
    name = candidate.name
    return bool(PROTECTED_NAME.match(name)) and name != ".env.example"
