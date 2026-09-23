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
        assert not self._launcher_imports("console.py")

    def test_no_lazy_import_of_launcher_anywhere_in_launchenv(self):
        """A function-local `import launcher` would keep the coupling while looking clean at the
        top of the file. `ast.walk` descends into function bodies, so an import at ANY nesting
        depth is caught — including one that only fires on a branch no test happens to take.

        Deliberately NOT done by evicting modules from `sys.modules` and re-importing: that
        constructs a SECOND `console` module, and with it a second `_err` and a second warning
        counter, which then leaks into whatever test imports next. That is the exact failure
        TestSharedConsole exists to rule out — a boundary test must not manufacture it.
        """
        assert not self._launcher_imports("launchenv.py")

    @staticmethod
    def _launcher_imports(filename: str) -> list[str]:
        """Every name imported by `src/harnessed/<filename>`, at any depth, that mentions launcher."""
        src = (Path(__file__).parent.parent / "src" / "harnessed" / filename).read_text()
        imported: list[str] = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported += [node.module or ""] + [a.name for a in node.names]
        return [name for name in imported if "launcher" in name]


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


class TestVarlockTimeout:
    """`varlock load` authenticates against a secrets manager, so it can wait forever on an
    approval nobody is there to give. Every launch runs it on the critical path (bd harnessed-prf).
    """

    def test_a_hanging_varlock_degrades_instead_of_blocking(self, tmp_path, monkeypatch):
        launchenv._varlock_cache_clear()
        (tmp_path / ".env.schema").write_text("SNYK_TOKEN=op(op://v/i/f)\n")

        seen: dict = {}

        def fake_run(cmd, **kw):
            seen.update(kw)
            raise launchenv.subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0.0)

        monkeypatch.setattr(launchenv.subprocess, "run", fake_run)

        # Degrades to None, exactly like a non-zero exit — a launch must not hard-fail (or hang)
        # on secrets it may not even need.
        assert launchenv._varlock_resolve(tmp_path) is None
        assert seen.get("timeout"), "varlock load must be given a deadline, or it can block forever"

    def test_the_timeout_result_is_cached_like_any_other_failure(self, tmp_path, monkeypatch):
        """Otherwise every caller in one launch pays the full timeout again."""
        launchenv._varlock_cache_clear()
        (tmp_path / ".env.schema").write_text("SNYK_TOKEN=op(op://v/i/f)\n")
        calls: list[int] = []

        def fake_run(cmd, **kw):
            calls.append(1)
            raise launchenv.subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0.0)

        monkeypatch.setattr(launchenv.subprocess, "run", fake_run)
        launchenv._varlock_resolve(tmp_path)
        launchenv._varlock_resolve(tmp_path)
        assert len(calls) == 1


class TestMultiLineSecretsAreNotCorrupted:
    """podman reads an --env-file value to end-of-line, so a PEM block or SSH key cannot be carried
    through it. Truncated key material fails later, somewhere that gives no hint it was truncated
    here — so it is skipped with a warning instead (bd harnessed-4gk).
    """

    def _resolve(self, monkeypatch, values):
        launchenv._varlock_cache_clear()
        monkeypatch.setattr(launchenv, "_varlock_resolve", lambda d: values)

    def test_a_pem_block_is_skipped_not_truncated(self, tmp_path, monkeypatch):
        pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"
        self._resolve(monkeypatch, {"SSH_KEY": pem, "TOKEN": "single-line"})

        out = launchenv._varlock_resolve_env_file(tmp_path)
        assert out is not None
        try:
            written = out.read_text()
            # The single-line secret still gets through — this is a skip, not a bail-out.
            assert written == "TOKEN=single-line\n"
            # Nothing from the key leaks in, in whole or in part.
            assert "BEGIN PRIVATE KEY" not in written
            assert "MIIEvQIBADANBg" not in written
            # And crucially: no line of the key was reparsed as its own KEY=VALUE.
            assert len(written.splitlines()) == 1
        finally:
            out.unlink()

    def test_a_carriage_return_counts_too(self, tmp_path, monkeypatch):
        self._resolve(monkeypatch, {"CRLF": "first\r\nsecond", "OK": "fine"})
        out = launchenv._varlock_resolve_env_file(tmp_path)
        assert out is not None
        try:
            assert out.read_text() == "OK=fine\n"
        finally:
            out.unlink()

    def test_the_skip_is_announced(self, tmp_path, monkeypatch, capsys):
        """A silently dropped credential is as hard to diagnose as a truncated one."""
        self._resolve(monkeypatch, {"SSH_KEY": "a\nb"})
        before = launcher._err.warnings
        out = launchenv._varlock_resolve_env_file(tmp_path)
        assert out is not None
        out.unlink()
        assert launcher._err.warnings > before
        assert "SSH_KEY" in capsys.readouterr().err

    def test_single_line_values_are_untouched(self, tmp_path, monkeypatch):
        self._resolve(monkeypatch, {"A": "1", "B": "2"})
        out = launchenv._varlock_resolve_env_file(tmp_path)
        assert out is not None
        try:
            assert out.read_text() == "A=1\nB=2\n"
        finally:
            out.unlink()
