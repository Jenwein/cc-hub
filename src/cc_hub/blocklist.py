# -*- coding: utf-8 -*-
"""Catastrophic-command blocklist used by `cc-hub hook pre-tool-use`."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    name: str
    args: list[str]
    program: str = ""  # argv[0] as written, before basename normalisation
    redirects: list[str] = field(default_factory=list)  # targets of > >> < 2> &>


@dataclass
class Group:
    """One command's tokens, with the redirect targets kept out of its arguments."""

    tokens: list[str]
    redirects: list[str]


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
DD_SAFE_SINKS = {"of=/dev/null", "of=/dev/zero", "of=/dev/stdout", "of=/dev/stderr"}
MAIN_REF = re.compile(r"^(?:.*:)?(?:refs/heads/)?(?:main|master)$")
PROTECTED_NAME = re.compile(r"^\.env(?:\..+)?$")
SHELLS = {"bash", "sh", "zsh", "dash", "fish", "ksh", "pwsh", "powershell", "cmd"}
SHELL_SCRIPT_OPTS = {"-c", "-lc", "-ec", "-ic", "-command", "/c"}
MAX_SHELL_DEPTH = 4
# shlex(punctuation_chars=True) returns runs of these as their own tokens.
PUNCTUATION = "();<>|&"
QUOTES = "\"'"


def normalize(command: str) -> str:
    return " ".join(command.split())


def _basename(token: str) -> str:
    return Path(token).name.casefold().removesuffix(".exe")


def _unquote(token: str) -> str:
    """Strip one matched pair of surrounding quotes (the non-posix pass keeps them)."""
    if len(token) >= 2 and token[0] in QUOTES and token[-1] == token[0]:
        return token[1:-1]
    return token


def _shell_script(tokens: list[str]) -> str | None:
    """For `bash -lc <script>` return <script>; None when this is not such a wrapper."""
    if _basename(_unquote(tokens[0])) not in SHELLS:
        return None
    index = 1
    while index < len(tokens):
        token = _unquote(tokens[index]).casefold()
        if token in SHELL_SCRIPT_OPTS:
            script = _unquote(tokens[index + 1]) if index + 1 < len(tokens) else ""
            return script or None
        if token.startswith("-") and not token.startswith("--") and len(token) > 1:
            index += 1  # an option of the shell itself, e.g. `bash -l -c ...`
            continue
        return None
    return None


def _is_punctuation(token: str) -> bool:
    return bool(token) and all(ch in PUNCTUATION for ch in token)


def _is_paren(token: str) -> bool:
    return bool(token) and all(ch in "()" for ch in token)


def _lex(line: str, *, posix: bool) -> list[str] | None:
    """One line's tokens; None if the quotes are unbalanced.

    Working from the token stream rather than the raw text is what keeps a
    quoted operator (`git commit -m 'a; b'`) inside its argument and still
    separates a real one (`echo hi; rm -rf /`).
    """
    lexer = shlex.shlex(line, posix=posix, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _group(tokens: list[str], *, split_parens: bool) -> list[Group]:
    """Cut a token stream at shell operators, keeping each redirect target aside.

    POSIX unescaping makes `find / \\( -name x \\) -delete` look exactly like a
    subshell, so parens get both readings: one where they end the group (real
    subshells) and one where they are dropped (escaped parens in an argument
    list). Callers judge the union.
    """
    groups: list[Group] = [Group([], [])]
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            groups[-1].redirects.append(token)
            continue
        if not _is_punctuation(token):
            groups[-1].tokens.append(token)
        elif ">" in token or "<" in token:
            skip_next = True  # the next token is the redirect target, not an argument
        elif _is_paren(token) and not split_parens:
            continue
        else:
            groups.append(Group([], []))  # && || | ; ;; & ( )
    return groups


def _fallback_groups(line: str) -> list[Group]:
    """Unbalanced quotes: the old behaviour, splitting the raw text on operators."""
    return [Group(part.split(), []) for part in SPLIT_RE.split(line) if part.strip()]


def _strip_wrappers(tokens: list[str]) -> list[str]:
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
    return tokens


def _segments_from(group: Group, *, depth: int) -> list[Segment]:
    tokens = _strip_wrappers(list(group.tokens))
    if not tokens:
        return []
    inner = _shell_script(tokens) if depth < MAX_SHELL_DEPTH else None
    if inner is not None:
        # `bash -lc "cd /tmp && rm -rf /"` must be judged by the script, not by
        # `bash`; the posix pass hands us the whole script as a single token.
        nested = split_segments(inner, _depth=depth + 1)
        if nested:  # `bash -lc "cat x" > secrets/key` must not lose its target
            nested[0].redirects.extend(group.redirects)
        return nested
    return [
        Segment(
            name=_basename(tokens[0]),
            args=tokens[1:],
            program=tokens[0],
            redirects=list(group.redirects),
        )
    ]


def split_segments(command: str, *, _depth: int = 0) -> list[Segment]:
    """Every command in `command`, under every reading that a shell might give it.

    The passes disagree on purpose. POSIX resolves escapes, so `rm -rf \\/` is the
    root directory; the literal pass keeps `C:\\Users\\bob` in one piece. Parens
    are read both as subshell boundaries and as ordinary noise. A rule that
    matches any one reading blocks the command.
    """
    segments: list[Segment] = []
    index: dict[tuple[str, tuple[str, ...]], Segment] = {}
    for line in command.split("\n"):
        if not line.strip():
            continue
        for posix in (True, False):
            tokens = _lex(line, posix=posix)
            readings = (
                [_group(tokens, split_parens=True), _group(tokens, split_parens=False)]
                if tokens is not None
                else [_fallback_groups(line)]
            )
            for groups in readings:
                for group in groups:
                    for segment in _segments_from(group, depth=_depth):
                        key = (segment.name, tuple(segment.args))
                        known = index.get(key)
                        if known is None:
                            index[key] = segment
                            segments.append(segment)
                            continue
                        for target in segment.redirects:
                            if target not in known.redirects:
                                known.redirects.append(target)
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
    return seg.name == "dd" and any(
        a.casefold().startswith("of=/dev/") and a.casefold() not in DD_SAFE_SINKS
        for a in seg.args
    )


def rule_power(seg: Segment) -> bool:
    if seg.name in POWER:
        return True
    return seg.name == "systemctl" and any(a in ("poweroff", "reboot", "halt") for a in seg.args)


def rule_force_push_main(seg: Segment) -> bool:
    if seg.name != "git" or "push" not in seg.args:
        return False
    refs = [a for a in seg.args if not a.startswith("-")]
    main_refs = [a for a in refs if MAIN_REF.match(a.lstrip("+"))]
    if not main_refs:
        return False
    force = "--force" in seg.args or "f" in _short_flags(seg.args)
    plus_force = any(a.startswith("+") for a in main_refs)
    return force or plus_force


def rule_chmod_root(seg: Segment) -> bool:
    return seg.name in ("chmod", "chown", "chgrp") and _recursive(seg.args) and any(
        _is_root_target(t) for t in _targets(seg.args)
    )


def rule_find_delete(seg: Segment) -> bool:
    if seg.name != "find":
        return False
    targets = _targets(seg.args)
    if not targets or not _is_root_target(targets[0]):
        return False
    if "-delete" in seg.args:
        return True
    return any(
        a == "-exec" and seg.args[i + 1] == "rm" for i, a in enumerate(seg.args[:-1])
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
    Rule("find-delete", "segment", rule_find_delete),
    Rule("win-remove-root", "segment", rule_win_remove_root),
    Rule("win-format", "segment", rule_win_format),
)


def match_command(command: str, extra: Iterable[str] = ()) -> str | None:
    text = normalize(command)
    if not text:
        return None
    # The regex rules want the collapsed one-liner; the segment rules want the
    # original, whose newlines separate commands just like a `;` would.
    segments = split_segments(command)
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
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(hub) / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError):
            resolved = candidate
    except (OSError, ValueError, RuntimeError):
        # `~nobody/x` raises RuntimeError and a NUL byte raises ValueError:
        # a path we cannot even name is not one of ours.
        return False
    secrets = (Path(hub) / "secrets").resolve()
    if resolved == secrets or secrets in resolved.parents:
        return True
    name = candidate.name
    return bool(PROTECTED_NAME.match(name)) and name != ".env.example"
