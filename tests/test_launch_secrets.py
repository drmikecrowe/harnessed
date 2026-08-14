"""Tests for launch-time secrets resolution (T-05).

Fast, no real varlock or podman required. The HARNESSED_PODMAN=1 end-to-end path
is NOT covered here — a fresh container would be needed for that.

Coverage:
- _resolve_launch_secrets: no-schema → None, no-varlock → None, varlock failure → None
- _resolve_launch_secrets: happy path returns a mode-0600 temp file with resolved content
- _resolve_launch_secrets: OP_SERVICE_ACCOUNT_TOKEN appended when set in host env
- emit._hatago_entry: url_env emits ${VAR} placeholder, not a literal secret value
- emit._hatago_entry: url (no url_env) unchanged (regression guard)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harnessed import emit, launcher
from harnessed.schema import McpServer
from support import patch_all


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fake_varlock_json(values: dict):
    """Fake subprocess.run result mimicking `varlock load --format json` stdout."""
    return subprocess.CompletedProcess(
        args=["varlock", "load", "--format", "json"],
        returncode=0,
        stdout=json.dumps(values),
        stderr="",
    )


# ---------------------------------------------------------------------------
# _resolve_launch_secrets
# ---------------------------------------------------------------------------

class TestResolveSecretsNoOp:
    """When no source is present → ([], []), no subprocess."""

    def test_no_schema_no_project_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # No global .env.schema, no project_path — must return empty without touching varlock.
        called = []
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: called.append(1))
        env_files, temp_files = launcher._resolve_launch_secrets()
        assert env_files == []
        assert temp_files == []
        assert called == []

    def test_no_varlock_skips_global_schema(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        schema = home / ".config" / "harnessed" / ".env.schema"
        schema.parent.mkdir(parents=True)
        schema.write_text("SNYK_TOKEN=op(op://Private/Snyk/credential)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
        called = []
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: called.append(1))
        env_files, temp_files = launcher._resolve_launch_secrets()
        assert env_files == []
        assert temp_files == []
        assert called == []


class TestResolveSecretsGlobalSchema:
    """When global schema + varlock both present, runs varlock and returns a temp file."""

    def _setup(self, monkeypatch, tmp_path, values: dict, *, op_token: str | None = None):
        home = tmp_path / "home"
        home.mkdir()
        schema = home / ".config" / "harnessed" / ".env.schema"
        schema.parent.mkdir(parents=True)
        schema.write_text("SNYK_TOKEN=op(op://Private/Snyk/credential)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: _fake_varlock_json(values),
        )
        if op_token is not None:
            monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", op_token)
        else:
            monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
        return schema

    def test_returns_temp_file(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"})
        env_files, temp_files = launcher._resolve_launch_secrets()
        assert len(env_files) == 1
        assert env_files == temp_files  # global schema temp is both an env-file and a cleanup target
        assert env_files[0].is_file()
        env_files[0].unlink()

    def test_temp_file_is_mode_600(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"})
        env_files, _ = launcher._resolve_launch_secrets()
        mode = env_files[0].stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600, got {mode:o}"
        env_files[0].unlink()

    def test_temp_file_contains_resolved_env(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123", "OTHER": "value"})
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "SNYK_TOKEN=abc123" in content
        env_files[0].unlink()

    def test_values_are_not_quoted(self, monkeypatch, tmp_path):
        """Regression: podman --env-file keeps quotes literal, so values must be written raw
        (KEY=value), never varlock's quoted `env` format (KEY="value")."""
        self._setup(monkeypatch, tmp_path, {"GEMINI_API_KEY": "xxxxxx"})
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "GEMINI_API_KEY=xxxxxx\n" in content
        assert '"' not in content  # no double quotes anywhere
        env_files[0].unlink()

    def test_typed_values_coerced_to_strings(self, monkeypatch, tmp_path):
        """JSON may carry non-string typed values (port=number, flag=boolean); coerce cleanly."""
        self._setup(monkeypatch, tmp_path, {"PORT": 3000, "FLAG": True, "OFF": False})
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "PORT=3000\n" in content
        assert "FLAG=true\n" in content
        assert "OFF=false\n" in content
        env_files[0].unlink()

    def test_null_values_skipped(self, monkeypatch, tmp_path):
        """A null (undefined @optional) value must not emit an empty KEY= line."""
        self._setup(monkeypatch, tmp_path, {"SET": "yes", "UNSET": None})
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "SET=yes\n" in content
        assert "UNSET" not in content
        env_files[0].unlink()

    def test_op_service_account_token_appended_when_set(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"}, op_token="secret-ci-token")  # noqa: S106 — fake token value in test fixture
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "OP_SERVICE_ACCOUNT_TOKEN=secret-ci-token" in content
        env_files[0].unlink()

    def test_op_service_account_token_not_added_when_absent(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"})
        env_files, _ = launcher._resolve_launch_secrets()
        content = env_files[0].read_text()
        assert "OP_SERVICE_ACCOUNT_TOKEN" not in content
        env_files[0].unlink()


class TestResolveSecretsProject:
    """Per-project env discovery, layered after (and thus overriding) the global schema."""

    def _no_global(self, monkeypatch, tmp_path):
        """Point home at an empty dir so no global schema exists."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

    def test_plain_env_normalized_into_temp(self, monkeypatch, tmp_path):
        self._no_global(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("FOO=bar\n")
        called = []
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: called.append(1))
        env_files, temp_files = launcher._resolve_launch_secrets(proj)
        # Plain .env is copied into a temp (normalized) — no varlock invocation, and the user's
        # own file is never handed to podman directly, so it's a cleanup target but the source is not.
        assert called == []
        assert env_files == temp_files and len(env_files) == 1
        assert env_files[0] != proj / ".env"          # a generated temp, not the user's file
        assert (proj / ".env").read_text() == "FOO=bar\n"  # source untouched
        assert env_files[0].read_text() == "FOO=bar\n"
        env_files[0].unlink()

    def test_plain_env_quotes_stripped(self, monkeypatch, tmp_path):
        """Regression: quoted values in a plain .env must not reach podman quoted."""
        self._no_global(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text(
            '# a comment\n'
            'GEMINI_API_KEY="xxxxxx"\n'
            "SINGLE='yyy'\n"
            "export EXPORTED=zzz\n"
            "PLAIN=raw\n"
        )
        env_files, _ = launcher._resolve_launch_secrets(proj)
        content = env_files[0].read_text()
        assert "GEMINI_API_KEY=xxxxxx\n" in content
        assert "SINGLE=yyy\n" in content
        assert "EXPORTED=zzz\n" in content        # export prefix dropped
        assert "PLAIN=raw\n" in content
        assert '"' not in content and "'" not in content
        assert "# a comment" in content           # comments pass through
        env_files[0].unlink()

    def test_project_schema_resolved_via_varlock(self, monkeypatch, tmp_path):
        self._no_global(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("FOO=op(op://Private/Foo/credential)\n")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: _fake_varlock_json({"FOO": "resolved"}),
        )
        env_files, temp_files = launcher._resolve_launch_secrets(proj)
        assert env_files == temp_files and len(env_files) == 1  # resolved → temp, cleaned up
        assert "FOO=resolved" in env_files[0].read_text()
        env_files[0].unlink()

    def test_project_schema_wins_over_plain_env(self, monkeypatch, tmp_path):
        """When both .env.schema and .env exist, the schema path is used (varlock cascades .env)."""
        self._no_global(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("FOO=op(op://Private/Foo/credential)\n")
        (proj / ".env").write_text("FOO=plain\n")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: _fake_varlock_json({"FOO": "resolved"}),
        )
        env_files, temp_files = launcher._resolve_launch_secrets(proj)
        assert len(env_files) == 1 and env_files == temp_files
        assert (proj / ".env") not in env_files
        env_files[0].unlink()

    def test_global_then_project_order(self, monkeypatch, tmp_path):
        """Global schema first, project .env second — podman applies last-wins, so project wins."""
        home = tmp_path / "home"
        home.mkdir()
        gschema = home / ".config" / "harnessed" / ".env.schema"
        gschema.parent.mkdir(parents=True)
        gschema.write_text("FOO=op(op://Private/Foo/credential)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: _fake_varlock_json({"FOO": "global"}),
        )
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("FOO=project\n")
        env_files, temp_files = launcher._resolve_launch_secrets(proj)
        assert len(env_files) == 2
        # Global schema resolved first, project .env (normalized) second → podman last-wins.
        assert env_files[0].read_text() == "FOO=global\n"
        assert env_files[1].read_text() == "FOO=project\n"
        assert temp_files == env_files                 # both are generated temps, both cleaned up
        for f in env_files:
            f.unlink()


class TestResolveSecretsVarlockFailure:
    """varlock returns non-zero → that source is dropped (returns empty when it's the only one)."""

    def test_varlock_error_drops_global(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        schema = home / ".config" / "harnessed" / ".env.schema"
        schema.parent.mkdir(parents=True)
        schema.write_text("SNYK_TOKEN=op(op://Private/Snyk/credential)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="failed to connect to 1Password"
            ),
        )
        env_files, temp_files = launcher._resolve_launch_secrets()
        assert env_files == []
        assert temp_files == []


# ---------------------------------------------------------------------------
# emit._hatago_entry with url_env
# ---------------------------------------------------------------------------

class TestHatagoEntryUrlEnv:
    """url_env → emits ${VAR} placeholder (never the resolved value)."""

    def test_url_env_emits_placeholder(self):
        server = McpServer(name="openbrain", transport="http", url_env="OB1_URL")
        entry = emit._hatago_entry(server)
        assert entry["url"] == "${OB1_URL}"
        assert entry["type"] == "http"

    def test_url_env_takes_precedence_over_url(self):
        """If both url and url_env are set, url_env wins (secret-free profile)."""
        server = McpServer(
            name="openbrain", transport="http",
            url="https://example.com/mcp?key=LITERAL_KEY",
            url_env="OB1_URL",
        )
        entry = emit._hatago_entry(server)
        assert entry["url"] == "${OB1_URL}"
        assert "LITERAL_KEY" not in entry["url"]

    def test_url_without_url_env_unchanged(self):
        """Regression: existing url-only servers are not affected."""
        server = McpServer(
            name="remote", transport="http", url="http://localhost:8080/mcp"
        )
        entry = emit._hatago_entry(server)
        assert entry["url"] == "http://localhost:8080/mcp"

    def test_url_env_placeholder_not_a_resolved_value(self):
        """The profile file must never contain the real secret."""
        server = McpServer(name="svc", transport="http", url_env="MY_SECRET_URL")
        entry = emit._hatago_entry(server)
        # The value should look like a shell variable reference, not a URL or resolved value.
        assert entry["url"].startswith("${") and entry["url"].endswith("}")


# ---------------------------------------------------------------------------
# _resolve_launch_env — the host-native twin (harnessed-36l)
# ---------------------------------------------------------------------------

class TestResolveLaunchEnvSources:
    """Same sources and same global → project precedence as _resolve_launch_secrets, returned as a
    dict. Host mode has no pod to hand an env-file to, so nothing is written to disk."""

    def _global_schema(self, monkeypatch, tmp_path, values: dict):
        home = tmp_path / "home"
        home.mkdir()
        schema = home / ".config" / "harnessed" / ".env.schema"
        schema.parent.mkdir(parents=True)
        schema.write_text("SNYK_TOKEN=op(op://Private/Snyk/credential)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
        monkeypatch.setattr(
            launcher.subprocess, "run", lambda *a, **kw: _fake_varlock_json(values)
        )

    def test_nothing_configured_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        called = []
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: called.append(1))
        assert launcher._resolve_launch_env() == {}
        assert called == []

    def test_no_varlock_skips_global_schema(self, monkeypatch, tmp_path):
        self._global_schema(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"})
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
        assert launcher._resolve_launch_env() == {}

    def test_global_schema_resolved(self, monkeypatch, tmp_path):
        self._global_schema(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123", "OTHER": "value"})
        assert launcher._resolve_launch_env() == {"SNYK_TOKEN": "abc123", "OTHER": "value"}

    def test_varlock_failure_degrades_to_empty(self, monkeypatch, tmp_path):
        self._global_schema(monkeypatch, tmp_path, {})
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="failed to connect to 1Password"
            ),
        )
        # A launch must not hard-fail on secrets it may not even need.
        assert launcher._resolve_launch_env() == {}

    def test_project_wins_over_global(self, monkeypatch, tmp_path):
        self._global_schema(monkeypatch, tmp_path, {"FOO": "global"})
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("FOO=project\n")
        assert launcher._resolve_launch_env(proj)["FOO"] == "project"

    def test_plain_env_is_normalized(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text(
            '# a comment\n'
            '\n'
            'export QUOTED="v1"\n'
            "SINGLE='v2'\n"
            "PLAIN=v3\n"
        )
        assert launcher._resolve_launch_env(proj) == {
            "QUOTED": "v1", "SINGLE": "v2", "PLAIN": "v3",
        }

    def test_writes_nothing_to_disk(self, monkeypatch, tmp_path):
        """The whole point of the host path: resolved secrets never land in a file."""
        self._global_schema(monkeypatch, tmp_path, {"SNYK_TOKEN": "abc123"})
        made = []
        monkeypatch.setattr(
            launcher.tempfile, "mkstemp", lambda *a, **kw: made.append(1) or (_ for _ in ()).throw(
                AssertionError("host path must not create a temp file")
            ),
        )
        assert launcher._resolve_launch_env()["SNYK_TOKEN"] == "abc123"  # noqa: S105 — fake token name in test assertion
        assert made == []


class TestHostLaunchAppliesSecrets:
    """The wiring: _launch_host must put resolved secrets in the env the agent is exec'd with,
    and the two precedence calls must hold (harnessed-36l)."""

    def test_secrets_reach_the_agent_with_correct_precedence(self, monkeypatch, tmp_path):
        from typer.testing import CliRunner

        from harnessed.schema import Recipe, Stack

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        # A stale export in the invoking shell — the schema must beat it.
        monkeypatch.setenv("SNYK_TOKEN", "stale-from-shell")

        patch_all(monkeypatch, "_resolve_launch_env",
            lambda project_path=None: {"SNYK_TOKEN": "from-schema", "RECIPE_OWNED": "from-schema"},
        )
        # A recipe declaring the same name must still win — mirroring `podman run -e` beating
        # --env-file in container mode.
        r = Recipe(name="envy", env={"RECIPE_OWNED": "from-recipe"})
        # `launcher` ONLY, deliberately not patch_all: this fakes what `_launch_host` LOADS, while
        # `assemble` must keep doing a real load. patch_all would also replace the binding in
        # `harnessed.assemble`, handing it this in-memory Recipe — whose `root` defaults to `.`, so
        # `validate_no_raw_npm` would then scan every vendored package.json under the CWD. That
        # fails only in a checkout that HAS those gitignored trees, which is why it passed in a
        # worktree and broke on main.
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes",
            lambda root, stack: (Stack(name="hostspike"), [r]),
        )

        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(env)
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = CliRunner().invoke(
            launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"]
        )
        assert result.exit_code == 0, result.output

        assert captured["SNYK_TOKEN"] == "from-schema"  # noqa: S105 — fake token name in test assertion; schema beats a stale shell export
        assert captured["RECIPE_OWNED"] == "from-recipe"  # recipe env beats a resolved secret
