"""Set one member of a JSON-with-comments file and keep every other byte (GH-569).

Zed and VS Code settings files hold `//` and `/* */` comments and trailing commas. `json` rejects
both, and a load-and-dump would delete every comment the user wrote. This parser records where each
value sits in the text, so `set_value` replaces one value's bytes or inserts one member, and the rest
of the file stays as written. A new member goes FIRST in its object, at the start of its own line,
so no existing line changes: appending would put a comma on the line above.

JSON5 forms (unquoted keys, single quotes) are refused as invalid. Standard library only (SPEC
Decide 3). The integrations call it as a script:

    python -m harnessed.jsonc set <file> <key>... <json-value>
    python -m harnessed.jsonc setdefault <file> <key>... <json-value>

`setdefault` writes only when the member is missing. A file that does not parse is never written,
and a write replaces the file whole (`write`), so a crash leaves the old file.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class JsoncError(ValueError):
    """Text that is not JSON with comments, or a key path that cannot be set. Carries the line."""

    def __init__(self, message: str, text: str, pos: int) -> None:
        self.line = text.count("\n", 0, pos) + 1
        super().__init__(f"line {self.line}: {message}")


@dataclass
class _Node:
    start: int
    end: int  # one past the value's last byte
    value: Any
    members: Optional[list[tuple[str, int, "_Node"]]] = None  # (key, key offset, value): objects only


_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"')
_LITERALS = ("true", "false", "null")


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 1 if text.startswith("﻿") else 0

    def fail(self, message: str, pos: Optional[int] = None) -> JsoncError:
        return JsoncError(message, self.text, self.pos if pos is None else pos)

    def skip(self) -> None:
        """Step over whitespace and comments."""
        t = self.text
        while self.pos < len(t):
            if t[self.pos] in " \t\r\n":
                self.pos += 1
            elif t.startswith("//", self.pos):
                nl = t.find("\n", self.pos)
                self.pos = len(t) if nl < 0 else nl + 1
            elif t.startswith("/*", self.pos):
                end = t.find("*/", self.pos + 2)
                if end < 0:
                    raise self.fail("a /* comment is not closed")
                self.pos = end + 2
            else:
                return

    def document(self) -> _Node:
        node = self.value()
        self.skip()
        if self.pos < len(self.text):
            raise self.fail("unexpected text after the value")
        return node

    def value(self) -> _Node:
        self.skip()
        t, start = self.text, self.pos
        if start >= len(t):
            raise self.fail("unexpected end of file")
        if t[start] == "{":
            return self.container("}")
        if t[start] == "[":
            return self.container("]")
        if t[start] == '"':
            m = _STRING.match(t, start)
            if m is None:
                raise self.fail("a string is not valid JSON")
            return self.leaf(m.end())
        for word in _LITERALS:
            if t.startswith(word, start):
                return self.leaf(start + len(word))
        m = _NUMBER.match(t, start)
        if m is None:
            raise self.fail(f"unexpected {t[start]!r}")
        return self.leaf(m.end())

    def leaf(self, end: int) -> _Node:
        start, self.pos = self.pos, end
        return _Node(start, end, json.loads(self.text[start:end]))

    def container(self, close: str) -> _Node:
        """An object (`close` is `}`) or an array. A trailing comma is allowed; an empty slot is not."""
        t, start = self.text, self.pos
        self.pos += 1
        members: list[tuple[str, int, _Node]] = []
        items: list[_Node] = []
        after_comma = True
        while True:
            self.skip()
            if self.pos >= len(t):
                raise self.fail("unexpected end of file: a `" + close + "` is missing")
            if t[self.pos] == close:
                self.pos += 1
                break
            if not after_comma:
                raise self.fail(f"expected ',' or '{close}'")
            if close == "}":
                if t[self.pos] != '"':
                    raise self.fail("expected a key in double quotes")
                key = self.value()
                self.skip()
                if self.pos >= len(t) or t[self.pos] != ":":
                    raise self.fail("expected ':'")
                self.pos += 1
                members.append((key.value, key.start, self.value()))
            else:
                items.append(self.value())
            self.skip()
            after_comma = self.pos < len(t) and t[self.pos] == ","
            if after_comma:
                self.pos += 1
        if close == "]":
            return _Node(start, self.pos, [item.value for item in items])
        return _Node(start, self.pos, {k: v.value for k, _, v in members}, members)


def parse(text: str) -> Any:
    """The value `text` holds. Raises `JsoncError` naming the line when it is not JSON with comments."""
    return _Parser(text).document().value


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _indent(text: str, pos: int) -> str:
    """The whitespace that opens the line `pos` is on."""
    line = text[_line_start(text, pos):pos]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _starts_line(text: str, pos: int) -> bool:
    """Whether only whitespace precedes `pos` on its line."""
    return text[_line_start(text, pos):pos].strip(" \t") == ""


def _dump(value: Any, indent: str, unit: str, *, multiline: bool, nl: str = "\n") -> str:
    if not multiline:
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, indent=unit).replace("\n", nl + indent)


def _unit(text: str, root: _Node) -> str:
    """The file's own indent step: the indent of the first top-level member on its own line."""
    outer = _indent(text, root.start)
    for _, key_at, _ in root.members or []:
        inner = _indent(text, key_at)
        if _starts_line(text, key_at) and len(inner) > len(outer) and inner.startswith(outer):
            return inner[len(outer):]
    return "  "


def _insert(
    text: str, obj: _Node, members: list[tuple[str, int, _Node]], key: str, value: Any, unit: str,
    nl: str,
) -> str:
    """`text` with `"key": value` as the first member of `obj`, whose members are `members`. `nl` is
    the file's own line end, so a CRLF file gets CRLF lines."""
    if members:
        first = members[0][1]
        if _starts_line(text, first):
            indent = _indent(text, first)
            at = _line_start(text, first)
            member = f"{indent}{json.dumps(key, ensure_ascii=False)}: {_dump(value, indent, unit, multiline=True, nl=nl)},{nl}"
        else:
            at = first
            member = f"{json.dumps(key, ensure_ascii=False)}: {_dump(value, '', unit, multiline=False)}, "
        return text[:at] + member + text[at:]
    outer = _indent(text, obj.start)
    indent = outer + unit
    member = f"{nl}{indent}{json.dumps(key, ensure_ascii=False)}: {_dump(value, indent, unit, multiline=True, nl=nl)}"
    inside = text[obj.start + 1 : obj.end - 1]
    if inside.strip(" \t\r\n") == "":
        return text[: obj.start + 1] + member + nl + outer + text[obj.end - 1 :]
    return text[: obj.start + 1] + member + text[obj.start + 1 :]


def set_value(text: str, keys: list[str], value: Any, *, only_missing: bool = False) -> str:
    """`text` with `value` at the key path `keys`, every other byte kept.

    Objects missing along the path are created. With `only_missing`, a member that exists is left as
    it is. Raises `JsoncError` when `text` does not parse or a step on the path is not an object.
    """
    if not keys:
        raise ValueError("set_value needs at least one key")
    if text.strip(" \t\r\n") == "":
        for key in reversed(keys):
            value = {key: value}
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    root = _Parser(text).document()
    unit = _unit(text, root)
    nl = "\r\n" if "\r\n" in text else "\n"
    node = root
    for i, key in enumerate(keys):
        members = node.members
        if members is None:
            where = "the top level" if i == 0 else repr(keys[i - 1])
            raise JsoncError(f"{where} is not an object", text, node.start)
        found = [m for m in members if m[0] == key]
        if not found:
            for rest in reversed(keys[i + 1 :]):
                value = {rest: value}
            return _insert(text, node, members, key, value, unit, nl)
        _, key_at, child = found[-1]  # the last duplicate is the one a reader sees, as in `json`
        if i == len(keys) - 1:
            if only_missing:
                return text
            multiline = _starts_line(text, key_at)
            dumped = _dump(value, _indent(text, key_at), unit, multiline=multiline, nl=nl)
            return text[: child.start] + dumped + text[child.end :]
        node = child
    raise AssertionError("unreachable")  # pragma: no cover


def read(path: Path) -> Optional[str]:
    """The file's text with its line ends as written, or None when it does not exist."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write(path: Path, text: str) -> None:
    """Replace `path` with `text` whole: a temporary file in the same directory, then a rename.

    Through a symlink, the link's target is written and the link kept. An existing file keeps its
    mode. The temporary file is removed when anything fails, and the old file is left as it was.
    """
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o7777 if target.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_USAGE = "usage: python -m harnessed.jsonc set|setdefault <file> <key>... <json-value>"


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 4 or args[0] not in ("set", "setdefault"):
        print(_USAGE, file=sys.stderr)
        return 2
    op, file, *keys, raw = args
    try:
        value = json.loads(raw)
    except ValueError as exc:
        print(f"error: the value is not JSON: {exc}", file=sys.stderr)
        return 2
    path = Path(file)
    try:
        old = read(path)
        new = set_value(old or "", keys, value, only_missing=op == "setdefault")
        if new != old:
            write(path, new)
    except JsoncError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as exc:
        print(f"error: {path}: not UTF-8 text ({exc.reason} at byte {exc.start})", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
