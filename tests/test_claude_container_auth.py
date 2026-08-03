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

from harnessed import launcher
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
        patch_all(monkeypatch, "_varlock_resolve", lambda d: {"CLAUDE_CODE_OAUTH_TOKEN": "secret-token"}
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
        patch_all(monkeypatch, "_varlock_resolve", lambda d: {"CLAUDE_CODE_OAUTH_TOKEN": ""}
        )
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

    def _stub_varlock(self, monkeypatch, calls: list[str], *, returncode: int = 0, stdout: str = "{}"):
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
