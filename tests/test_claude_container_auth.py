"""Tests for containerized Claude auth: the long-lived `CLAUDE_CODE_OAUTH_TOKEN` path and the
legacy credential-file fallback it replaces.

`claude setup-token` yields a ~1-year subscription token that outranks the credentials file and
never needs in-container refresh — so when one is configured, no credential file is mounted at
all. Without one we still seed a copy (so hosts that haven't run setup-token keep working), but
unlike the original implementation that copy RE-SEEDS once expired: seeding exactly once left
instances permanently logged out, curable only by deleting the state dir by hand.
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

from harnessed import launcher
from harnessed.backend import LaunchSpec
from support import patch_all


def _home(monkeypatch, tmp_path):
    """Point HOME at an empty tmp dir so ~/.config/harnessed never interferes with the test."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def _creds(expires_in: timedelta) -> str:
    """A credentials payload whose access token expires `expires_in` from now."""
    expires_at = (datetime.now(timezone.utc) + expires_in).timestamp() * 1000
    return json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": expires_at}})


class TestOauthTokenDetection:
    def test_host_env_token_is_forwarded_by_name_not_value(self, monkeypatch):
        """Bare `-e NAME` keeps the secret off the command line (podman reads its own env)."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret-value")
        args = launcher._claude_oauth_token_args("claude")
        assert args == ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]
        assert "secret-value" not in " ".join(args)

    def test_no_token_emits_nothing(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        assert launcher._claude_oauth_token_args("claude") == []

    def test_other_harnesses_unaffected(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
        assert launcher._claude_oauth_token_args("codex") == []

    def test_detects_token_in_plain_env_file(self, monkeypatch, tmp_path):
        """Plain .env in project_path is the non-varlock fallback (Route 3)."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("OTHER=1\nCLAUDE_CODE_OAUTH_TOKEN=abc\n")
        assert launcher._claude_oauth_token_configured("claude", proj) is True

    def test_env_without_token_is_not_a_false_positive(self, monkeypatch, tmp_path):
        """A plain .env that lacks the token must not count as configured."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        # Substring of the name must not count — only a real KEY=<value> assignment.
        (proj / ".env").write_text("NOT_CLAUDE_CODE_OAUTH_TOKEN_HINT=1\n")
        assert launcher._claude_oauth_token_configured("claude", proj) is False

    def test_no_project_path_and_no_global_config_returns_false(self, monkeypatch, tmp_path):
        """No project_path and an empty home → definitively no token."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        assert launcher._claude_oauth_token_configured("claude") is False

    # --- regression tests (harnessed-9hp.3) ---

    def test_detects_token_via_varlock_structured(self, monkeypatch, tmp_path):
        """Route 2: _varlock_resolve (structured) finds the token without scanning text."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("")  # triggers the varlock branch
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(
            monkeypatch, "_varlock_resolve", lambda d: {"CLAUDE_CODE_OAUTH_TOKEN": "secret-token"}
        )
        assert launcher._claude_oauth_token_configured("claude", proj) is True

    def test_varlock_failure_warns_not_silently_remounts(self, monkeypatch, tmp_path):
        """When varlock fails the function must WARN (not silently fall through) so the
        operator can distinguish 'varlock failure' from 'genuinely no token' before the
        credential-file mount fires (harnessed-9hp.3)."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("")
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(monkeypatch, "_varlock_resolve", lambda d: None)  # varlock failure

        before = launcher._err.warnings
        result = launcher._claude_oauth_token_configured("claude", proj)
        assert result is False
        assert launcher._err.warnings > before, "expected a warning when varlock fails"

    def test_global_varlock_failure_does_not_warn_when_project_supplies_the_token(
        self, monkeypatch, tmp_path
    ):
        """A varlock failure in ONE dir must not warn if a later dir still supplies the token.

        The warning promises "Mounting a credential file as fallback". When global varlock is down
        but the project has the token, we return True and mount nothing — so warning there would
        describe something that never happens.
        """
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        home = _home(monkeypatch, tmp_path)
        gdir = home / ".config" / "harnessed"
        gdir.mkdir(parents=True)
        (gdir / ".env.schema").write_text("")  # global takes the varlock branch...
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=from-project\n")  # ...project does not
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(monkeypatch, "_varlock_resolve", lambda d: None)  # global varlock fails

        before = launcher._err.warnings
        assert launcher._claude_oauth_token_configured("claude", proj) is True
        assert launcher._err.warnings == before, "must not warn when the token was found anyway"

    def test_all_varlock_failures_warn_once_listing_every_dir(self, monkeypatch, tmp_path):
        """Two failed dirs produce ONE warning naming both, not one warning per dir."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        home = _home(monkeypatch, tmp_path)
        gdir = home / ".config" / "harnessed"
        gdir.mkdir(parents=True)
        (gdir / ".env.schema").write_text("")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("")
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(monkeypatch, "_varlock_resolve", lambda d: None)

        before = launcher._err.warnings
        assert launcher._claude_oauth_token_configured("claude", proj) is False
        assert launcher._err.warnings == before + 1, "expected exactly one warning for both dirs"

    def test_empty_value_in_env_not_configured(self, monkeypatch, tmp_path):
        """export CLAUDE_CODE_OAUTH_TOKEN= turns the token OFF; empty must not count as configured."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")
        assert launcher._claude_oauth_token_configured("claude", proj) is False

    def test_empty_varlock_value_not_configured(self, monkeypatch, tmp_path):
        """Varlock returning an empty string for the key must not count as configured."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("")
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(monkeypatch, "_varlock_resolve", lambda d: {"CLAUDE_CODE_OAUTH_TOKEN": ""})
        assert launcher._claude_oauth_token_configured("claude", proj) is False


class TestCredsMountSupersededByToken:
    def test_token_configured_mounts_no_credential_file(self, monkeypatch, tmp_path):
        """The whole point: a configured token means we never mount host credentials at all."""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert launcher._claude_creds_seed_mount("claude", "inst", token_configured=True) == []

    def test_without_token_still_mounts(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        host = tmp_path / "home" / ".claude"
        host.mkdir(parents=True)
        (host / ".credentials.json").write_text(_creds(timedelta(hours=8)))
        args = launcher._claude_creds_seed_mount("claude", "inst", token_configured=False)
        assert args and args[0] == "-v"


class TestOmpConsumesNoClaudeCredential:
    """#314: every Claude-credential path was gated on `harness in ("claude", "omp")`, so an omp
    launch copied the host's live OAuth credential into a pod that cannot read it and printed two
    warnings about doing so. omp authenticates from the `auth_credentials` table of the
    ~/.omp/agent/agent.db that `_omp_agent_mount` bind-mounts; its Anthropic env names are
    ANTHROPIC_OAUTH_TOKEN/ANTHROPIC_API_KEY, and the omp image ships no `claude` CLI."""

    def test_no_token_forward(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret-value")
        assert launcher._claude_oauth_token_args("omp") == []

    def test_never_reports_a_token_configured(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret-value")
        _home(monkeypatch, tmp_path)
        assert launcher._claude_oauth_token_configured("omp", tmp_path) is False

    def test_varlock_failure_warns_for_claude_but_not_for_omp(self, monkeypatch, tmp_path):
        """The user-visible half of #314: the harness gate must short-circuit BEFORE the varlock
        probe, or omp keeps emitting the 'could not resolve CLAUDE_CODE_OAUTH_TOKEN' warning."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        _home(monkeypatch, tmp_path)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("")
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock")
        patch_all(monkeypatch, "_varlock_resolve", lambda d: None)  # varlock failure

        before = launcher._err.warnings
        launcher._claude_oauth_token_configured("omp", proj)
        assert launcher._err.warnings == before, "omp warned about a token it cannot use"

        launcher._claude_oauth_token_configured("claude", proj)
        assert launcher._err.warnings > before, "claude must still warn"

    def test_no_credential_file_is_copied(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        host = tmp_path / "home" / ".claude"
        host.mkdir(parents=True)
        (host / ".credentials.json").write_text(_creds(timedelta(hours=8)))

        before = launcher._err.warnings
        assert launcher._claude_creds_seed_mount("omp", "inst", token_configured=False) == []
        assert not (tmp_path / "harnessed" / "inst" / "credentials.json").exists(), (
            "the host credential was copied into per-instance state for a harness that cannot use it"
        )
        assert launcher._err.warnings == before


class TestExpiredCopyReseeds:
    """The seed-once ratchet: an aged-out copy was never refreshed, so relaunching a stale
    instance stayed logged out forever."""

    def _setup(self, monkeypatch, tmp_path, stub_creds: str):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        host = tmp_path / "home" / ".claude"
        host.mkdir(parents=True)
        (host / ".credentials.json").write_text(_creds(timedelta(hours=8)))
        state = tmp_path / "harnessed" / "inst"
        state.mkdir(parents=True)
        stub = state / "credentials.json"
        stub.write_text(stub_creds)
        return stub

    def test_expired_copy_is_reseeded_from_host(self, monkeypatch, tmp_path):
        stub = self._setup(monkeypatch, tmp_path, _creds(timedelta(hours=-3)))
        launcher._claude_creds_seed_mount("claude", "inst", token_configured=False)
        expires_at = json.loads(stub.read_text())["claudeAiOauth"]["expiresAt"] / 1000
        assert expires_at > datetime.now(timezone.utc).timestamp()  # refreshed, not left dead

    def test_valid_copy_is_never_clobbered(self, monkeypatch, tmp_path):
        """The original guard's real purpose: don't overwrite a token the container refreshed."""
        original = _creds(timedelta(hours=5))
        stub = self._setup(monkeypatch, tmp_path, original)
        launcher._claude_creds_seed_mount("claude", "inst", token_configured=False)
        assert stub.read_text() == original

    def test_malformed_copy_is_replaced(self, monkeypatch, tmp_path):
        stub = self._setup(monkeypatch, tmp_path, "{not json")
        launcher._claude_creds_seed_mount("claude", "inst", token_configured=False)
        assert json.loads(stub.read_text())["claudeAiOauth"]["expiresAt"]  # parseable again


class TestExpiryHelper:
    def test_future_expiry_is_not_expired(self, tmp_path):
        f = tmp_path / "c.json"
        f.write_text(_creds(timedelta(hours=1)))
        assert launcher._claude_creds_expired(f) is False

    def test_past_expiry_is_expired(self, tmp_path):
        f = tmp_path / "c.json"
        f.write_text(_creds(timedelta(hours=-1)))
        assert launcher._claude_creds_expired(f) is True

    def test_epoch_zero_is_expired(self, tmp_path):
        """Observed on real instances: expiresAt=0 (never-valid/cleared) must count as expired."""
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"claudeAiOauth": {"expiresAt": 0}}))
        assert launcher._claude_creds_expired(f) is True

    def test_missing_or_unparseable_is_expired(self, tmp_path):
        missing = tmp_path / "nope.json"
        assert launcher._claude_creds_expired(missing) is True
        bad = tmp_path / "bad.json"
        bad.write_text("{}")
        assert launcher._claude_creds_expired(bad) is True


class TestVarlockResolveMemo:
    """`_varlock_resolve` shells out to `varlock load`, which may authenticate against a secrets
    manager. Several callers resolve the SAME dir in one launch (env-file build, then the token
    presence check), so the result is memoized per dir for the process lifetime.
    """

    def _stub_varlock(
        self, monkeypatch, calls: list[str], *, returncode: int = 0, stdout: str = "{}"
    ):
        launcher._varlock_cache_clear()

        def fake_run(cmd, **kwargs):
            calls.append(kwargs.get("cwd", ""))
            return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    def test_same_dir_resolves_once(self, monkeypatch, tmp_path):
        """The second call for a dir must NOT spawn another varlock subprocess."""
        calls: list[str] = []
        self._stub_varlock(monkeypatch, calls, stdout='{"CLAUDE_CODE_OAUTH_TOKEN": "tok"}')

        first = launcher._varlock_resolve(tmp_path)
        second = launcher._varlock_resolve(tmp_path)

        assert first == second == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}
        assert len(calls) == 1, f"expected 1 varlock invocation, got {len(calls)}"

    def test_distinct_dirs_each_resolve(self, monkeypatch, tmp_path):
        """Memoization is per dir — global and project must both still be resolved."""
        calls: list[str] = []
        self._stub_varlock(monkeypatch, calls)
        a = tmp_path / "global"
        b = tmp_path / "project"
        a.mkdir()
        b.mkdir()

        launcher._varlock_resolve(a)
        launcher._varlock_resolve(b)

        assert len(calls) == 2

    def test_failure_is_cached_and_reported_once(self, monkeypatch, tmp_path):
        """A failing varlock must not be retried once per caller.

        The error is printed inside `_varlock_resolve`, so a single invocation is also proof it is
        reported exactly once — no need to reach into the console's internals to count it.
        """
        calls: list[str] = []
        self._stub_varlock(monkeypatch, calls, returncode=1)

        assert launcher._varlock_resolve(tmp_path) is None
        assert launcher._varlock_resolve(tmp_path) is None

        assert len(calls) == 1, f"failure should be cached, got {len(calls)} invocations"

    def test_cache_clear_forces_reresolution(self, monkeypatch, tmp_path):
        calls: list[str] = []
        self._stub_varlock(monkeypatch, calls)

        launcher._varlock_resolve(tmp_path)
        launcher._varlock_cache_clear()
        launcher._varlock_resolve(tmp_path)

        assert len(calls) == 2


class TestEnvFileBeatsShellExport:
    """A token supplied by an --env-file outranks one exported in the invoking shell.

    `podman run -e` beats `--env-file`, so forwarding the host value unconditionally made a stale
    shell export outrank every declared source — and a per-project token for a DIFFERENT account
    (a client's, resolved into <project>/.env.schema) could never take effect. Host mode already
    resolved this the other way (bd harnessed-36l); this is the container half.
    """

    def test_env_file_token_suppresses_the_host_forward(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "mine-from-shell")
        env_file = tmp_path / "resolved.env"
        env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=clients-token\n")
        # No `-e`, so podman applies only the env-file → the client's token is what lands.
        assert launcher._claude_oauth_token_args("claude", [env_file]) == []

    def test_host_forward_survives_an_env_file_without_the_token(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "mine-from-shell")
        env_file = tmp_path / "resolved.env"
        env_file.write_text("SOMETHING_ELSE=1\n")
        assert launcher._claude_oauth_token_args("claude", [env_file]) == [
            "-e",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ]

    def test_a_blank_env_file_value_also_suppresses_the_host_forward(self, monkeypatch, tmp_path):
        """An explicit blank is a declaration too — it means "declared, and turned off". Forwarding
        the host value over the top would override the very intent that declared it, since `-e`
        beats `--env-file`. The credential-file fallback is what covers the launch from there."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "mine-from-shell")
        env_file = tmp_path / "resolved.env"
        env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")
        assert launcher._claude_oauth_token_args("claude", [env_file]) == []

    def test_missing_env_file_does_not_break_the_launch(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "mine-from-shell")
        assert launcher._claude_oauth_token_args("claude", [tmp_path / "gone.env"]) == [
            "-e",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ]

    def test_default_argument_preserves_the_old_call_shape(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
        assert launcher._claude_oauth_token_args("claude") == ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]


class TestIsolatedAuthStore:
    """`isolated_auth: true` — a stack with its OWN Claude identity (a client's account).

    Nothing is seeded from the host and no host token reaches the container, so the agent comes up
    logged out and `/login` writes the client's credentials into a per-instance host file.
    """

    def test_store_is_seeded_logged_out_and_mounted_rw(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        args = launcher._claude_isolated_auth_mount("claude", "inst-a")
        assert args[0] == "-v"
        src, dst, mode = args[1].split(":")
        assert dst.endswith("/.claude/.credentials.json")
        assert mode == "rw", "a ro mount would block the in-container login this exists for"
        # `{}` parses as "no claudeAiOauth" — logged out. A MISSING source would make podman create
        # an empty directory Claude cannot read.
        assert json.loads(Path(src).read_text()) == {}
        assert Path(src).stat().st_mode & 0o777 == 0o600

    def test_nothing_is_copied_from_the_host(self, monkeypatch, tmp_path):
        """The SOP bans copying the host store; this path must not touch it even when it exists."""
        home = _home(monkeypatch, tmp_path)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        (home / ".claude").mkdir()
        (home / ".claude" / ".credentials.json").write_text(_creds(timedelta(hours=5)))

        args = launcher._claude_isolated_auth_mount("claude", "inst-b")
        src = Path(args[1].split(":")[0])
        assert json.loads(src.read_text()) == {}, "host credentials must never be seeded here"

    def test_an_existing_login_is_never_overwritten(self, monkeypatch, tmp_path):
        """Unlike the legacy path, an EXPIRED store is not re-seeded: expiry means the client's own
        token should refresh in place, and rewriting it would throw their login away."""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        launcher._claude_isolated_auth_mount("claude", "inst-c")
        store = Path(launcher._claude_isolated_auth_mount("claude", "inst-c")[1].split(":")[0])
        store.write_text(_creds(timedelta(hours=-5)))

        launcher._claude_isolated_auth_mount("claude", "inst-c")
        assert json.loads(store.read_text()) != {}, "an expired client login must survive relaunch"

    def test_fresh_wipes_the_login(self, monkeypatch, tmp_path):
        """The store survives a normal recreate on purpose, so --fresh is the only way back to
        logged-out (mirrors _keyring_fresh_wipe)."""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        store = Path(launcher._claude_isolated_auth_mount("claude", "inst-d")[1].split(":")[0])
        store.write_text(_creds(timedelta(hours=5)))

        launcher._isolated_auth_fresh_wipe("claude", "inst-d")
        assert not store.exists()

    def test_fresh_wipe_is_a_noop_for_other_harnesses_and_missing_stores(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        launcher._isolated_auth_fresh_wipe("codex", "inst-e")
        launcher._isolated_auth_fresh_wipe("claude", "never-launched")

    def test_other_harnesses_get_no_mount(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        for harness in ("codex", "omp", "opencode", "antigravity"):
            assert launcher._claude_isolated_auth_mount(harness, "inst-f") == []


class TestIsolatedAuthStripsTheEnvFileToken:
    """Suppressing the `-e` forward is not enough: --env-file is passed unconditionally, so a token
    in the user-global ~/.config/harnessed/.env.schema would walk straight past it."""

    def test_token_assignment_is_removed_and_the_rest_survives(self, tmp_path):
        f = tmp_path / "resolved.env"
        f.write_text("KEEP=1\nCLAUDE_CODE_OAUTH_TOKEN=mine\n# a comment\nALSO=2\n")

        launcher._strip_var_from_env_files("CLAUDE_CODE_OAUTH_TOKEN", [f])

        body = f.read_text()
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in body
        assert "KEEP=1" in body and "ALSO=2" in body and "# a comment" in body

    def test_export_prefixed_and_quoted_forms_are_caught(self, tmp_path):
        f = tmp_path / "resolved.env"
        f.write_text('export CLAUDE_CODE_OAUTH_TOKEN="mine"\nKEEP=1\n')

        launcher._strip_var_from_env_files("CLAUDE_CODE_OAUTH_TOKEN", [f])

        assert "CLAUDE_CODE_OAUTH_TOKEN" not in f.read_text()

    def test_a_name_that_merely_contains_the_var_is_left_alone(self, tmp_path):
        f = tmp_path / "resolved.env"
        f.write_text("MY_CLAUDE_CODE_OAUTH_TOKEN_BACKUP=x\n")

        launcher._strip_var_from_env_files("CLAUDE_CODE_OAUTH_TOKEN", [f])

        assert "MY_CLAUDE_CODE_OAUTH_TOKEN_BACKUP=x" in f.read_text()

    def test_missing_file_is_tolerated(self, tmp_path):
        launcher._strip_var_from_env_files("CLAUDE_CODE_OAUTH_TOKEN", [tmp_path / "gone.env"])


class TestEffectiveTokenAcrossEnvFiles:
    """Presence must agree with the precedence the VALUES follow (bd harnessed-7bk).

    `_resolve_launch_secrets` orders env-files global → project and `--env-file` is last-wins, so a
    project-level `VAR=` written to disable a global token really does reach the container empty.
    Answering from the first hit meant no `-e` forward AND no credential file: logged out, with no
    recovery path from inside the pod.
    """

    def test_project_blank_overrides_a_global_token(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "mine-from-shell")
        glob = tmp_path / "global.env"
        glob.write_text("CLAUDE_CODE_OAUTH_TOKEN=global-token\n")
        proj = tmp_path / "project.env"
        proj.write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")
        # Declared-and-disabled: the host value must NOT be forwarded over the top, because `-e`
        # would beat the --env-file that expressed the intent.
        assert launcher._claude_oauth_token_args("claude", [glob, proj]) == []
        assert launcher._env_files_value("CLAUDE_CODE_OAUTH_TOKEN", [glob, proj]) == ""

    def test_project_token_overrides_a_global_one(self, tmp_path):
        glob = tmp_path / "global.env"
        glob.write_text("CLAUDE_CODE_OAUTH_TOKEN=global-token\n")
        proj = tmp_path / "project.env"
        proj.write_text("CLAUDE_CODE_OAUTH_TOKEN=clients-token\n")
        assert launcher._env_files_value("CLAUDE_CODE_OAUTH_TOKEN", [glob, proj]) == "clients-token"

    def test_unassigned_reads_as_none_not_empty(self, tmp_path):
        f = tmp_path / "e.env"
        f.write_text("OTHER=1\n")
        assert launcher._env_files_value("CLAUDE_CODE_OAUTH_TOKEN", [f]) is None

    def test_configured_honors_a_project_blank_over_a_global_token(self, monkeypatch, tmp_path):
        """The credential-file decision half: with the token disabled at project level, the legacy
        credentials mount must come BACK, or the container has neither."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        home = _home(monkeypatch, tmp_path)
        cfg = home / ".config" / "harnessed"
        cfg.mkdir(parents=True)
        (cfg / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=global-token\n")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")

        assert launcher._claude_oauth_token_configured("claude", proj) is False

    def test_a_global_token_still_counts_when_the_project_is_silent(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        home = _home(monkeypatch, tmp_path)
        cfg = home / ".config" / "harnessed"
        cfg.mkdir(parents=True)
        (cfg / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=global-token\n")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env").write_text("SOMETHING=1\n")

        assert launcher._claude_oauth_token_configured("claude", proj) is True


class TestIsolatedAuthDoesNotLeakHostAccountMetadata:
    """`oauthAccount` carries the host account's email/uuid/organization and `userID` its account
    id. Seeding them into a stack that authenticates as somebody ELSE hands your account metadata
    to a client-facing container and pairs a stub identifying you with their credentials."""

    def _host_config(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        (home / ".claude.json").write_text(
            json.dumps(
                {
                    "oauthAccount": {"emailAddress": "me@example.com", "organizationName": "Mine"},
                    "userID": "host-user-id",
                }
            )
        )

    def test_isolated_seed_omits_account_identity(self, monkeypatch, tmp_path):
        self._host_config(monkeypatch, tmp_path)
        args = launcher._claude_config_seed_mount("claude", "inst-i", isolated_auth=True)
        stub = json.loads(Path(args[1].split(":")[0]).read_text())

        assert stub["oauthAccount"] == {} and stub["userID"] == ""
        assert "me@example.com" not in json.dumps(stub)
        # The onboarding half is the whole point of the stub and must survive.
        assert stub["hasCompletedOnboarding"] is True

    def test_shared_identity_still_seeds_it(self, monkeypatch, tmp_path):
        """The default path is unchanged — this stub exists to skip the login-method screen."""
        self._host_config(monkeypatch, tmp_path)
        args = launcher._claude_config_seed_mount("claude", "inst-j")
        stub = json.loads(Path(args[1].split(":")[0]).read_text())

        assert stub["oauthAccount"]["emailAddress"] == "me@example.com"
        assert stub["userID"] == "host-user-id"


class TestIsolatedAuthIsGatedOnTheHarness:
    """`isolated_auth` warns that non-claude harnesses keep the host identity — the code must
    actually honor that. omp authenticates from the SAME CLAUDE_CODE_OAUTH_TOKEN, so suppressing
    the forward and stripping it from the env-files left an omp launch with no auth at all while
    the warning promised the opposite.
    """

    def _backend(self, tmp_path, isolated: bool):
        stk = SimpleNamespace(isolated_auth=isolated)
        b = launcher.ContainerBackend(
            "podman",
            "inst-x",
            "pod-x",
            tmp_path,
            "img",
            tmp_path,
            [],
            [],
            stk,
            stack_from_overlay=False,
            headless=True,
        )
        b.mount_args = []  # stand in for materialize_config having run
        return b

    def _env_file(self, tmp_path, name="resolved.env"):
        f = tmp_path / name
        f.write_text("CLAUDE_CODE_OAUTH_TOKEN=host-token\n")
        return f

    def test_a_claude_only_flag_does_not_rewrite_a_shared_env_file_for_omp(
        self, monkeypatch, tmp_path
    ):
        """`isolated_auth` strips the token from the resolved env-file so a client-identity stack
        cannot fall back to the host account. That file is SHARED with everything else the stack
        runs, so the strip must not fire for a harness the flag does not govern. omp reads no
        Claude token itself (#314) — the invariant is about not mutating shared state."""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        _home(monkeypatch, tmp_path)
        env_file = self._env_file(tmp_path)
        monkeypatch.setattr(
            launcher,
            "_resolve_launch_secrets",
            lambda p: ([env_file], [env_file]),
        )
        b = self._backend(tmp_path, isolated=True)

        b.seed_auth(LaunchSpec(stack="s", harness="omp", project_path=tmp_path))

        assert "CLAUDE_CODE_OAUTH_TOKEN=host-token" in env_file.read_text(), (
            "a claude-only flag rewrote the shared env-file on an omp launch"
        )
        assert not any("isolated-auth" in a for a in b.mount_args)

    def test_claude_still_gets_the_isolated_treatment(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        _home(monkeypatch, tmp_path)
        env_file = self._env_file(tmp_path)
        monkeypatch.setattr(
            launcher,
            "_resolve_launch_secrets",
            lambda p: ([env_file], [env_file]),
        )
        b = self._backend(tmp_path, isolated=True)

        b.seed_auth(LaunchSpec(stack="s", harness="claude", project_path=tmp_path))

        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env_file.read_text()
        assert any("isolated-auth" in a for a in b.mount_args)
