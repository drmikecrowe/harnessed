"""Tests for containerized Claude auth: the long-lived `CLAUDE_CODE_OAUTH_TOKEN` path and the
legacy credential-file fallback it replaces.

`claude setup-token` yields a ~1-year subscription token that outranks the credentials file and
never needs in-container refresh — so when one is configured, no credential file is mounted at
all. Without one we still seed a copy (so hosts that haven't run setup-token keep working), but
unlike the original implementation that copy RE-SEEDS once expired: seeding exactly once left
instances permanently logged out, curable only by deleting the state dir by hand.
"""

import json
from datetime import datetime, timedelta, timezone

from harnessed import launcher


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

    def test_detects_token_in_env_file(self, monkeypatch, tmp_path):
        """varlock/.env is the recommended route — a long-lived token belongs in a secret store."""
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        env_file = tmp_path / "secrets.env"
        env_file.write_text("OTHER=1\nCLAUDE_CODE_OAUTH_TOKEN=abc\n")
        assert launcher._claude_oauth_token_configured("claude", [env_file]) is True

    def test_env_file_without_token_is_not_a_false_positive(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        env_file = tmp_path / "secrets.env"
        # Substring of the name must not count — only a real KEY= assignment.
        env_file.write_text("NOT_CLAUDE_CODE_OAUTH_TOKEN_HINT=1\n")
        assert launcher._claude_oauth_token_configured("claude", [env_file]) is False

    def test_unreadable_env_file_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        assert launcher._claude_oauth_token_configured("claude", [tmp_path / "missing.env"]) is False


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
