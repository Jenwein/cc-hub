# -*- coding: utf-8 -*-
"""Edit one table of a TOML file in place.

hub.toml belongs to the user, so a change is a text edit of one table that leaves every other
byte alone, line endings included. An edit that would not parse back to exactly the intended
data is refused instead of guessed at. `edit_table` replaces the own keys of a table;
`set_key` changes one key of it and leaves the table's other lines, comments included.
"""

from __future__ import annotations

import copy
import re
import tomllib

import tomli_w

_PART = r'(?:"[^"]+"|[A-Za-z0-9_-]+)'
_PARTS = rf"({_PART}(?:\s*\.\s*{_PART})*)"
HEADER = re.compile(rf"^\s*\[\s*{_PARTS}\s*\](?:\s*#.*)?$")
ARRAY_HEADER = re.compile(rf"^\s*\[\[\s*{_PARTS}\s*\]\](?:\s*#.*)?$")
PART = re.compile(r'"([^"]+)"|([A-Za-z0-9_-]+)')
# a line with its own ending, so that rejoining the lines gives the text back unchanged
LINE = re.compile(r"[^\n]*\n|[^\n]+")
BARE = re.compile(r"[A-Za-z0-9_-]+")
UNUSABLE = re.compile(r'[\x00-\x1f\x7f"\\]')

CANNOT_EDIT = "cannot edit in place"


class TableEditError(ValueError):
    """The edit is not possible, or would not leave the file as intended."""


def _path(pattern: re.Pattern, line: str) -> tuple[str, ...] | None:
    m = pattern.match(line.rstrip("\r\n"))
    if m is None:
        return None
    return tuple(p.group(1) or p.group(2) for p in PART.finditer(m.group(1)))


def header_path(line: str) -> tuple[str, ...] | None:
    """The table path a header line names: `[a."x/y"]  # c` gives ("a", "x/y"); None otherwise.

    Only bare and double-quoted parts are read, and `[[array]]` headers are not tables.
    """
    return _path(HEADER, line)


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


def _children(lines: list[str], path: tuple[str, ...], table) -> dict:
    """The child tables of the table at `path`: those a header line puts directly under it.

    A child is found by its header, `[a.b]` or `[[a.b]]` under `[a]`, not by the data: an inline
    table or a dotted key is one of the table's own keys, and goes with them.
    """
    if not isinstance(table, dict):
        return {}
    depth = len(path)
    names = set()
    for line in lines:
        found = header_path(line) or _path(ARRAY_HEADER, line)
        if found is not None and len(found) > depth and found[:depth] == path:
            names.add(found[depth])
    return {name: table[name] for name in names if name in table}


def _lookup(data: dict, path: tuple[str, ...]):
    """The value at `path`, or None when a part of it is missing or not a table."""
    node = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _expected(before: dict, path: tuple[str, ...], values: dict | None, children: dict) -> dict:
    """`before` with the table at `path` holding `values` and its `children`, or removed."""
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
        node[key] = {**values, **children}
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


def edit_table(
    text: str, path: tuple[str, ...], values: dict | None, *, allow_children: bool = True
) -> str:
    """`text` with the table `path` holding exactly `values` as its own keys.

    The table is the one whose header parses to `path`; it is added at the end of the file when
    there is none. Its child tables, the ones headed `[a."b"]` or `[[a.b]]` under `[a]`, are
    kept; `allow_children=False` refuses a table that has any. `None` removes the header and
    its keys, which needs the table to have no child tables. Only that table changes.
    TableEditError when `text` is not TOML, when `path` or `values` cannot be written, or when
    the result would not parse to the old data apart from this one table.
    """
    if not path or any(not part or UNUSABLE.search(part) for part in path):
        raise TableEditError(f"{path!r} is not a usable table path")
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TableEditError(f"not valid TOML: {exc}") from None

    lines = LINE.findall(text)
    children = _children(lines, path, _lookup(before, path))
    if children and (values is None or not allow_children):
        raise TableEditError(f"{_header(path)} has child tables")
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
    expected = _expected(before, path, values, children)
    if after != expected and (
        values is not None or after != _without_empty_ancestors(expected, path)
    ):
        raise TableEditError(CANNOT_EDIT)
    return new_text


def _value_end(s: str) -> int | None:
    """Where the TOML value that starts `s` ends, when it is complete on this line; else None.

    A multi-line string or array, and a comment inside an array, give None. Bare values (numbers,
    booleans, dates without a space) end at the first space or `#`.
    """
    if s.startswith(('"""', "'''")):
        return None
    if s.startswith('"'):
        i = 1
        while i < len(s):
            if s[i] == "\\":
                i += 2
            elif s[i] == '"':
                return i + 1
            else:
                i += 1
        return None
    if s.startswith("'"):
        end = s.find("'", 1)
        return None if end < 0 else end + 1
    if s.startswith(("[", "{")):
        depth = 0
        i = 0
        while i < len(s):
            ch = s[i]
            if ch in "\"'":
                end = _value_end(s[i:])
                if end is None:
                    return None
                i += end
                continue
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    return i + 1
            elif ch == "#":
                return None
            i += 1
        return None
    m = re.match(r"[^\s#]+", s)
    return m.end() if m else None


def _toml_value(value: str | int | bool) -> str:
    if not isinstance(value, str | int):  # bool is an int
        raise TableEditError(f"{value!r} is not a usable value")
    return tomli_w.dumps({"v": value}).strip()[len("v = ") :]


def set_key(text: str, path: tuple[str, ...], key: str, value: str | int | bool) -> str:
    """`text` with `key = value` set among the own keys of the table `path`, all else unchanged.

    A one-line `key = ...` line of the table gets only its value replaced; the indentation,
    spacing and a trailing comment stay. Without the key it is added after the table's last own
    key (or right after its header). A table that is not there is appended, as `edit_table`
    does. Other keys, comments and child tables are never rewritten.
    TableEditError when `text` is not TOML, when `path`, `key` or `value` cannot be written,
    or when the result would not parse to the old data plus this one key, as with a value
    that spans lines.
    """
    if not path or any(not part or UNUSABLE.search(part) for part in path):
        raise TableEditError(f"{path!r} is not a usable table path")
    if not key or UNUSABLE.search(key):
        raise TableEditError(f"{key!r} is not a usable key")
    literal = _toml_value(value)
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TableEditError(f"not valid TOML: {exc}") from None

    lines = LINE.findall(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    name = key if BARE.fullmatch(key) else f'"{key}"'
    span = _find(lines, path)
    if span is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += eol
        if lines and lines[-1].strip():
            lines.append(eol)
        lines += [_header(path) + eol, f"{name} = {literal}{eol}"]
    else:
        start, end = span
        last = end  # one past the table's last line that is not blank or a comment
        while last > start + 1 and _spacing(lines[last - 1]):
            last -= 1
        names = rf'(?:"{re.escape(key)}"|{re.escape(key)})'
        own = re.compile(rf"(?P<head>[ \t]*{names}[ \t]*=[ \t]*)(?P<rest>[^\r\n]*)")
        for i in range(start + 1, last):
            m = own.fullmatch(lines[i].rstrip("\r\n"))
            if m is None:
                continue
            rest = m.group("rest")
            stop = _value_end(rest)
            if stop is None or not re.fullmatch(r"[ \t]*(?:#.*)?", rest[stop:]):
                raise TableEditError(CANNOT_EDIT)
            ending = lines[i][len(lines[i].rstrip("\r\n")) :]
            lines[i] = m.group("head") + literal + rest[stop:] + ending
            break
        else:
            if not lines[last - 1].endswith("\n"):
                lines[last - 1] += eol
            lines.insert(last, f"{name} = {literal}{eol}")

    new_text = "".join(lines)
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        raise TableEditError(CANNOT_EDIT) from None
    expected = copy.deepcopy(before)
    node = expected
    for part in path:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise TableEditError(CANNOT_EDIT)
        node = child
    node[key] = value
    if after != expected:
        raise TableEditError(CANNOT_EDIT)
    return new_text
