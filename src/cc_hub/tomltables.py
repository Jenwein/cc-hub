# -*- coding: utf-8 -*-
"""Edit one table of a TOML file in place.

hub.toml belongs to the user, so a change is a text edit of one table that leaves every other
byte alone, line endings included. An edit that would not parse back to exactly the intended
data is refused instead of guessed at.
"""

from __future__ import annotations

import copy
import re
import tomllib

import tomli_w

_PART = r'(?:"[^"]+"|[A-Za-z0-9_-]+)'
HEADER = re.compile(rf"^\s*\[\s*({_PART}(?:\s*\.\s*{_PART})*)\s*\](?:\s*#.*)?$")
PART = re.compile(r'"([^"]+)"|([A-Za-z0-9_-]+)')
# a line with its own ending, so that rejoining the lines gives the text back unchanged
LINE = re.compile(r"[^\n]*\n|[^\n]+")
BARE = re.compile(r"[A-Za-z0-9_-]+")
UNUSABLE = re.compile(r'[\x00-\x1f\x7f"\\]')

CANNOT_EDIT = "cannot edit in place"


class TableEditError(ValueError):
    """The edit is not possible, or would not leave the file as intended."""


def header_path(line: str) -> tuple[str, ...] | None:
    """The table path a header line names: `[a."x/y"]  # c` gives ("a", "x/y"); None otherwise.

    Only bare and double-quoted parts are read, and `[[array]]` headers are not tables.
    """
    m = HEADER.match(line.rstrip("\r\n"))
    if m is None:
        return None
    return tuple(p.group(1) or p.group(2) for p in PART.finditer(m.group(1)))


def _header(path: tuple[str, ...]) -> str:
    """`[a."x/y"]`: the first part bare when it can be, every later one quoted."""
    parts = [p if i == 0 and BARE.fullmatch(p) else f'"{p}"' for i, p in enumerate(path)]
    return "[" + ".".join(parts) + "]"


def _spacing(line: str) -> bool:
    """A blank line or a comment line: what trails a table without belonging to its keys."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _find(lines: list[str], path: tuple[str, ...]) -> tuple[int, int] | None:
    """Line range [start, end) of the table headed `path`, up to the next header line, or None."""
    for start, line in enumerate(lines):
        if header_path(line) == path:
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
                len(lines),
            )
            return start, end
    return None


def _is_table(value) -> bool:
    return isinstance(value, dict) or (
        isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)
    )


def _children(table) -> dict:
    """The entries of a table that are themselves tables."""
    return {k: v for k, v in table.items() if _is_table(v)} if isinstance(table, dict) else {}


def _lookup(data: dict, path: tuple[str, ...]):
    """The value at `path`, or None when a part of it is missing or not a table."""
    node = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _expected(before: dict, path: tuple[str, ...], values: dict | None) -> dict:
    """`before` with the table at `path` holding `values` as its own keys, or removed."""
    out = copy.deepcopy(before)
    node = out
    for part in path[:-1]:
        child = node.get(part)
        if child is None:
            if values is None:
                return out  # nothing there to remove
            child = node[part] = {}
        elif not isinstance(child, dict):
            raise TableEditError(CANNOT_EDIT)
        node = child
    key = path[-1]
    if values is None:
        node.pop(key, None)
    else:
        old = node.get(key)
        if old is not None and not isinstance(old, dict):
            raise TableEditError(CANNOT_EDIT)
        node[key] = {**values, **_children(old)}
    return out


def _without_empty_ancestors(data: dict, path: tuple[str, ...]) -> dict:
    """`data` without the tables along `path[:-1]` that hold nothing: no header, no data."""
    out = copy.deepcopy(data)
    chain = [out]
    for part in path[:-1]:
        child = chain[-1].get(part)
        if not isinstance(child, dict):
            break
        chain.append(child)
    for depth in range(len(chain) - 1, 0, -1):
        if chain[depth]:
            break
        del chain[depth - 1][path[depth - 1]]
    return out


def edit_table(text: str, path: tuple[str, ...], values: dict | None) -> str:
    """`text` with the table `path` holding exactly `values` as its own keys.

    The table is the one whose header parses to `path`; it is added at the end of the file when
    there is none. Keys whose values are tables (child tables such as `[a."b"]` under `[a]`)
    are kept. `None` removes the header and its keys, which needs the table to have no child
    tables. Only that table changes. TableEditError when `text` is not TOML, when `path` or
    `values` cannot be written, or when the result would not parse to the old data apart from
    this one table.
    """
    if not path or any(not part or UNUSABLE.search(part) for part in path):
        raise TableEditError(f"{path!r} is not a usable table path")
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TableEditError(f"not valid TOML: {exc}") from None
    if values is None and _children(_lookup(before, path)):
        raise TableEditError(f"cannot remove [{'.'.join(path)}]: it has child tables")

    lines = LINE.findall(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    body = [line + eol for line in (tomli_w.dumps(values) if values else "").splitlines()]
    span = _find(lines, path)
    if span is None:
        if values is not None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += eol
            if lines and lines[-1].strip():
                lines.append(eol)
            lines += [_header(path) + eol, *body]
    else:
        start, end = span
        last = end  # one past the table's last line that is not blank or a comment
        while last > start + 1 and _spacing(lines[last - 1]):
            last -= 1
        if values is None:
            # blank lines that end the file go with the table; a comment there stays
            stop = len(lines) if all(not line.strip() for line in lines[last:]) else last
            first = start - 1 if start > 0 and not lines[start - 1].strip() else start
            del lines[first:stop]
        else:
            if not lines[start].endswith("\n"):
                lines[start] += eol
            lines[start + 1 : last] = body

    new_text = "".join(lines)
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        raise TableEditError(CANNOT_EDIT) from None
    expected = _expected(before, path, values)
    if after != expected and (
        values is not None or after != _without_empty_ancestors(expected, path)
    ):
        raise TableEditError(CANNOT_EDIT)
    return new_text
