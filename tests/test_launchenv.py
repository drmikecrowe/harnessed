"""`launchenv` — launch-time environment resolution, extracted from launcher.py (bd harnessed-4l8).

The end-to-end behaviour of `_resolve_launch_secrets` / `_resolve_launch_env` is covered by
tests/test_launch_secrets.py, and the varlock memo by tests/test_claude_container_auth.py; both
still exercise them through `launcher`, which is the point of the re-export. What lives HERE is what
the extraction itself put at risk: the direction of the dependency, the single shared console, and
the small parsing units the two resolvers are built out of.
"""

from __future__ import annotations

import ast
import os
import stat

from pathlib import Path

import pytest

from harnessed import console, launcher, launchenv


class TestModuleBoundary:
    """The direction rule from the dynstack exemplar — see
    tests/test_dynstack.py::TestModuleBoundary. Pure, derivable logic lives in a focused module;
    launcher.py keeps the Typer surface and podman orchestration; dependencies point INTO the
    module and never back out.
    """

    def test_launchenv_does_not_import_launcher(self):
        src = (Path(__file__).parent.parent / "src" / "harnessed" / "launchenv.py").read_text()
        assert "launcher" not in src, (
            "launchenv must not depend on launcher — the dependency points INTO modules, never "
            "back out (bd harnessed-4l8)"
        )

    def test_console_does_not_import_launcher(self):
        """`launchenv` reaches the shared console through `console`, so the boundary above is only
        real if THAT module is clean too — a cycle one hop away is still a cycle.

        Checked over the parsed IMPORTS rather than the raw text, because this module's docstring
        has to name `launcher` to explain why it was carved out of it.
        """
        src = (Path(__file__).parent.parent / "src" / "harnessed" / "console.py").read_text()
        imported: list[str] = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported += [node.module or ""] + [a.name for a in node.names]
        assert not any("launcher" in name for name in imported), imported

    def test_no_lazy_import_of_launcher_at_call_time(self):
        """A function-local `import launcher` would pass the source check above while keeping the
        coupling. Resolve the whole module graph and assert launcher is genuinely not in it."""
        import importlib
        import sys

        for name in ("harnessed.launcher", "harnessed.launchenv", "harnessed.console"):
            sys.modules.pop(name, None)
        mod = importlib.import_module("harnessed.launchenv")
        # Touch every public entry point so a lazy import inside one of them would fire.
        mod._parse_plain_env_line("A=b")
        mod._varlock_cache_clear()
        assert "harnessed.launcher" not in sys.modules


class TestSharedConsole:
    """The reason `console.py` exists at all: one console instance, one warning counter.

    `_acknowledge_warnings` reads `launcher._err.warnings` just before os.execvp hands the terminal
    over. If `launchenv` had constructed its own console, a warning it printed would be counted on
    an object nobody reads and the acknowledgement prompt would be skipped.
    """

    def test_launcher_and_launchenv_share_one_error_console(self):
        assert launchenv._err is launcher._err is console._err

    def test_a_warning_printed_from_launchenv_reaches_the_counter_launcher_reads(self):
        before = launcher._err.warnings
        launchenv._err.print("[yellow]warning:[/yellow] resolved from the extracted module")
        assert launcher._err.warnings == before + 1


class TestParsePlainEnvLine:
    """One dotenv line -> (key, value). The unit both resolvers are built out of: the container
    path writes it back out as an env-file, the host path puts it straight into `os.environ`."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("PLAIN=v3", ("PLAIN", "v3")),
            ('QUOTED="v1"', ("QUOTED", "v1")),
            ("SINGLE='v2'", ("SINGLE", "v2")),
            ('export EXPORTED="v4"', ("EXPORTED", "v4")),
            ("  SPACED  =  v5  ", ("SPACED", "v5")),
            # Only ONE pair of surrounding quotes comes off, and only a MATCHED pair.
            ('NESTED=""v6""', ("NESTED", '"v6"')),
            ("MISMATCHED=\"v7'", ("MISMATCHED", "\"v7'")),
            # An empty value is a value: `KEY=` unsets rather than being skipped.
            ("EMPTY=", ("EMPTY", "")),
            # A `=` in the value is not a second separator.
            ("URL=postgres://u:p@h/db?a=1", ("URL", "postgres://u:p@h/db?a=1")),
        ],
    )
    def test_values_are_parsed(self, raw, expected):
        assert launchenv._parse_plain_env_line(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "# a comment", "  # indented comment", "NOEQUALS"])
    def test_nothing_to_set_returns_none(self, raw):
        assert launchenv._parse_plain_env_line(raw) is None


class TestPlainEnvValues:
    def test_later_lines_win(self, tmp_path):
        src = tmp_path / ".env"
        src.write_text("FOO=first\nFOO=second\n")
        assert launchenv._plain_env_values(src) == {"FOO": "second"}

    def test_comments_and_blanks_are_dropped(self, tmp_path):
        src = tmp_path / ".env"
        src.write_text("# header\n\nFOO=bar\n\nNOEQUALS\n")
        assert launchenv._plain_env_values(src) == {"FOO": "bar"}


class TestNormalizePlainEnvFile:
    """The container half: a copy podman can read, with the quoting podman would otherwise take
    literally already stripped. The user's own `.env` must never be the file handed to podman."""

    def test_quotes_are_stripped_and_comments_pass_through(self, tmp_path):
        src = tmp_path / ".env"
        src.write_text('# keep me\n\nexport QUOTED="v1"\nSINGLE=\'v2\'\nPLAIN=v3\nNOEQUALS\n')
        out = launchenv._normalize_plain_env_file(src)
        try:
            assert out != src
            assert out.read_text().splitlines() == [
                "# keep me", "", "QUOTED=v1", "SINGLE=v2", "PLAIN=v3", "NOEQUALS",
            ]
            # The source is copied, never rewritten — the caller unlinks the temp, not the user's file.
            assert '"v1"' in src.read_text()
        finally:
            out.unlink()

    def test_the_temp_file_is_not_world_readable(self, tmp_path):
        """It can hold resolved secrets, so mode 0600 is the point of the file, not a detail."""
        src = tmp_path / ".env"
        src.write_text("SECRET=hunter2\n")
        out = launchenv._normalize_plain_env_file(src)
        try:
            assert stat.S_IMODE(out.stat().st_mode) == 0o600
        finally:
            out.unlink()

    def test_a_write_failure_leaves_no_temp_behind(self, tmp_path, monkeypatch):
        """The failure path must not strand a file that may already hold secret bytes."""
        src = tmp_path / ".env"
        src.write_text("SECRET=hunter2\n")
        leaked: list[str] = []
        real_mkstemp = launchenv.tempfile.mkstemp

        def _mkstemp(*a, **kw):
            fd, path = real_mkstemp(*a, **kw)
            leaked.append(path)
            return fd, path

        monkeypatch.setattr(launchenv.tempfile, "mkstemp", _mkstemp)
        monkeypatch.setattr(launchenv.os, "chmod", lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))

        with pytest.raises(OSError):
            launchenv._normalize_plain_env_file(src)
        assert leaked and not os.path.exists(leaked[0])
