"""`jsonc` — set one member of a JSON-with-comments file and keep every other byte (GH-569).

Zed and VS Code settings files hold `//` and `/* */` comments and trailing commas. `json` rejects
them, and a load-and-dump would delete them. The properties pinned here are the ones that make
editing a user's settings file safe: the edit lands, nothing else moves, and a file that does not
parse is never written.
"""

import json
import os
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harnessed import jsonc

ZED = """// Zed settings
{
  /* the theme */
  "theme": "One Dark", // a note
  "agent_servers": {
    "other": {"type": "custom", "command": "/bin/other", "args": [],},
  },
  "vim_mode": true,
}
"""


class TestParse:
    def test_reads_comments_and_trailing_commas(self):
        assert jsonc.parse(ZED) == {
            "theme": "One Dark",
            "agent_servers": {"other": {"type": "custom", "command": "/bin/other", "args": []}},
            "vim_mode": True,
        }

    @pytest.mark.parametrize(
        ("text", "line"),
        [
            ('{\n  "a": 1\n', 3),  # a missing `}`
            ('{\n  "a": 1\n  "b": 2\n}', 3),  # a missing `,`
            ('{\n  a: 1\n}', 2),  # JSON5: an unquoted key
            ("{\n  'a': 1\n}", 2),  # JSON5: single quotes
            ('{\n  "a": 1,,\n}', 2),
            ('{\n  "a": tru\n}', 2),
            ('{\n  "a": 01\n}', 2),
            ('{\n  /* open\n}', 2),
            ('{"a": 1} x', 1),
            ('{"a": "\n"}', 1),  # a raw newline inside a string
        ],
    )
    def test_invalid_text_names_the_line(self, text, line):
        with pytest.raises(jsonc.JsoncError) as exc:
            jsonc.parse(text)
        assert exc.value.line == line
        assert str(exc.value).startswith(f"line {line}: ")

    def test_reads_a_leading_byte_order_mark(self):
        assert jsonc.parse('﻿{"a": 1}') == {"a": 1}

    def test_the_last_duplicate_key_wins_as_in_json(self):
        assert jsonc.parse('{"a": 1, "a": 2}') == json.loads('{"a": 1, "a": 2}')


# JSON values, the shape a settings file holds. Strings include quotes, backslashes, `//` and `/*`,
# so a tokenizer that reads a comment inside a string fails here.
_SCALARS = st.one_of(
    st.none(), st.booleans(), st.integers(-(10**12), 10**12),
    st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=12),
)
_VALUES = st.recursive(
    _SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4), st.dictionaries(st.text(max_size=6), inner, max_size=4)
    ),
    max_leaves=12,
)
_OBJECTS = st.dictionaries(st.text(max_size=6), _VALUES, max_size=5)
_KEYS = st.lists(st.sampled_from(["a", "b", "", "/*", "x\"y"]), min_size=1, max_size=3)


def _with_comments(text: str) -> str:
    """`text` with a numbered comment at the end of every line. A line of `json.dumps` output never
    ends inside a string, so each comment sits between tokens."""
    return "\n".join(
        f"{line} // c{i}" if i % 2 else f"{line} /* c{i} */" for i, line in enumerate(text.split("\n"))
    )


def _markers(text: str) -> list[str]:
    return re.findall(r"(?://|/\*) c\d+", text)


def _expected(doc: dict, keys: list[str], value):
    """`doc` with `value` set at `keys`, missing objects created; None when a step is not an object."""
    out = json.loads(json.dumps(doc))
    node = out
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            return None
    node[keys[-1]] = value
    return out


def _replaces_a_container(doc: dict, keys: list[str]) -> bool:
    """Whether `keys` names a non-empty object or array: replacing it replaces its comments too."""
    node = doc
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return isinstance(node, (dict, list)) and bool(node)


class TestParseProperties:
    @given(_VALUES)
    def test_agrees_with_json_on_plain_json(self, value):
        assert jsonc.parse(json.dumps(value)) == value
        assert jsonc.parse(json.dumps(value, indent=2)) == value

    @given(_VALUES)
    def test_comments_change_no_value(self, value):
        assert jsonc.parse(_with_comments(json.dumps(value, indent=2))) == value


class TestSetProperties:
    @settings(max_examples=300)
    @given(_OBJECTS, _KEYS, _VALUES, st.booleans())
    def test_the_edit_lands_and_every_comment_survives(self, doc, keys, value, indented):
        old = _with_comments(json.dumps(doc, indent=2 if indented else None))
        want = _expected(doc, keys, value)
        if want is None:
            with pytest.raises(jsonc.JsoncError):
                jsonc.set_value(old, keys, value)
            return
        new = jsonc.set_value(old, keys, value)
        assert jsonc.parse(new) == want
        if not _replaces_a_container(doc, keys):
            assert _markers(new) == _markers(old), "a comment was lost or moved past another"

    @given(_OBJECTS, _KEYS, _VALUES)
    def test_setting_the_same_value_twice_changes_nothing(self, doc, keys, value):
        old = _with_comments(json.dumps(doc, indent=2))
        if _expected(doc, keys, value) is None:
            return
        once = jsonc.set_value(old, keys, value)
        assert jsonc.set_value(once, keys, value) == once

    @given(_OBJECTS, _KEYS, _VALUES)
    def test_setdefault_never_changes_a_member_that_exists(self, doc, keys, value):
        old = json.dumps(doc, indent=2)
        want = _expected(doc, keys, value)
        if want is None:
            return
        new = jsonc.set_value(old, keys, value, only_missing=True)
        node = doc
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                assert jsonc.parse(new) == want
                return
            node = node[key]
        assert new == old


class TestSet:
    def test_replacing_a_value_changes_only_its_bytes(self):
        old = '{\n  "w": "/old", // keep\n  "x": 1\n}\n'
        assert jsonc.set_value(old, ["w"], "/new") == '{\n  "w": "/new", // keep\n  "x": 1\n}\n'

    def test_a_new_member_is_a_new_line_and_no_line_changes(self):
        new = jsonc.set_value(ZED, ["agent_servers", "mine"], {"type": "custom", "args": []})
        old_lines = ZED.splitlines()
        new_lines = new.splitlines()
        added = [line for line in new_lines if line not in old_lines]
        assert [line for line in new_lines if line in old_lines] == old_lines
        assert added == [
            '    "mine": {',
            '      "type": "custom",',
            '      "args": []',
            "    },",
        ]

    def test_a_missing_object_is_created(self):
        new = jsonc.set_value('{\n  "theme": "x"\n}\n', ["agent_servers", "k"], {"a": 1})
        assert jsonc.parse(new) == {"theme": "x", "agent_servers": {"k": {"a": 1}}}
        assert new.endswith('  "theme": "x"\n}\n')

    def test_an_empty_object_gets_one_member(self):
        assert jsonc.set_value("{}\n", ["k"], 1) == '{\n  "k": 1\n}\n'

    def test_a_one_line_object_keeps_its_line(self):
        assert jsonc.set_value('{"a": 1}', ["k"], 2) == '{"k": 2, "a": 1}'

    @pytest.mark.parametrize("text", ["", "  \n"])
    def test_empty_text_becomes_an_object(self, text):
        assert jsonc.set_value(text, ["a", "b"], 1) == '{\n  "a": {\n    "b": 1\n  }\n}\n'

    def test_a_step_that_is_not_an_object_is_refused(self):
        with pytest.raises(jsonc.JsoncError, match="not an object"):
            jsonc.set_value('{\n  "a": [1]\n}', ["a", "b"], 1)

    def test_a_top_level_that_is_not_an_object_is_refused(self):
        with pytest.raises(jsonc.JsoncError, match="not an object"):
            jsonc.set_value("[1]", ["a"], 1)

    def test_the_tab_indent_of_the_file_is_kept(self):
        new = jsonc.set_value('{\n\t"a": 1\n}\n', ["k"], {"b": 2})
        assert new == '{\n\t"k": {\n\t\t"b": 2\n\t},\n\t"a": 1\n}\n'

    def test_no_key_is_refused(self):
        with pytest.raises(ValueError):
            jsonc.set_value("{}", [], 1)


class TestCli:
    def _run(self, *args: str) -> int:
        return jsonc.main(list(args))

    def test_set_writes_the_file(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text('{\n  // c\n  "a": 1\n}\n')
        assert self._run("set", str(f), "b", '"x"') == 0
        assert f.read_text() == '{\n  // c\n  "b": "x",\n  "a": 1\n}\n'

    def test_a_missing_file_and_its_directory_are_created(self, tmp_path):
        f = tmp_path / "d" / "e" / "s.json"
        assert self._run("set", str(f), "a", "1") == 0
        assert json.loads(f.read_text()) == {"a": 1}

    def test_setdefault_keeps_an_existing_member(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text('{"a": 1}')
        assert self._run("setdefault", str(f), "a", "2") == 0
        assert f.read_text() == '{"a": 1}'

    def test_an_invalid_file_is_refused_and_left_as_it_was(self, tmp_path, capsys):
        f = tmp_path / "s.json"
        f.write_bytes(b'{\n  "a": 1\n')
        assert self._run("set", str(f), "b", "1") == 1
        assert f.read_bytes() == b'{\n  "a": 1\n'
        err = capsys.readouterr().err
        assert str(f) in err and "line 3" in err

    def test_an_unchanged_file_is_not_rewritten(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text('{"a": 1}')
        os.utime(f, (1, 1))
        assert self._run("set", str(f), "a", "1") == 0
        assert f.stat().st_mtime == 1

    def test_crlf_line_ends_are_kept(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
        assert self._run("set", str(f), "a", "2") == 0
        assert f.read_bytes() == b'{\r\n  "a": 2\r\n}\r\n'

    def test_the_mode_of_the_file_is_kept(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text("{}")
        f.chmod(0o600)
        assert self._run("set", str(f), "a", "1") == 0
        assert f.stat().st_mode & 0o777 == 0o600

    def test_a_symlinked_file_is_edited_through_the_link(self, tmp_path):
        real = tmp_path / "real.json"
        real.write_text("{}")
        link = tmp_path / "link.json"
        link.symlink_to(real)
        assert self._run("set", str(link), "a", "1") == 0
        assert link.is_symlink()
        assert json.loads(real.read_text()) == {"a": 1}

    def test_a_failed_rename_leaves_the_old_file(self, tmp_path, monkeypatch):
        f = tmp_path / "s.json"
        f.write_text('{"a": 1}')

        def boom(*_a):
            raise OSError("disk full")

        monkeypatch.setattr(jsonc.os, "replace", boom)
        with pytest.raises(OSError):
            jsonc.write(f, '{"a": 2}')
        assert f.read_text() == '{"a": 1}'
        assert [p.name for p in tmp_path.iterdir()] == ["s.json"], "the temporary file was left"

    @pytest.mark.parametrize(
        "args", [[], ["set"], ["set", "f"], ["set", "f", "k"], ["nope", "f", "k", "1"]]
    )
    def test_a_usage_error_exits_2(self, args, capsys):
        assert self._run(*args) == 2
        assert "usage" in capsys.readouterr().err

    def test_a_value_that_is_not_json_exits_2(self, tmp_path, capsys):
        assert self._run("set", str(tmp_path / "s.json"), "k", "not json") == 2
        assert "not JSON" in capsys.readouterr().err
        assert not (tmp_path / "s.json").exists()

    def test_an_unreadable_file_exits_1(self, tmp_path, capsys):
        d = tmp_path / "dir.json"
        d.mkdir()
        assert self._run("set", str(d), "k", "1") == 1
        assert str(d) in capsys.readouterr().err


def test_the_module_runs_as_a_script(tmp_path):
    import subprocess
    import sys

    f = tmp_path / "s.json"
    proc = subprocess.run(
        [sys.executable, "-m", "harnessed.jsonc", "set", str(f), "k", "true"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(Path(f).read_text()) == {"k": True}
