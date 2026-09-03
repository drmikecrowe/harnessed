"""Tests for the content-only host-native launch backend (`launch --host`).

Covers the materialize + seed + plan seam WITHOUT the interactive exec: the launcher copies the
assembled profile's `.claude/*` content layer + settings floor into a host CLAUDE_CONFIG_DIR,
seeds claude's own auth from the host, and deliberately drops the container-only MCP artifacts.
"""

import inspect
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import emit, hosthome, hostrun, launcher, paths
from harnessed.assemble import assemble
from support import patch_all

runner = CliRunner()


def _fake_profile(prof: Path) -> None:
    """A minimal assembled profile: content layer + container-only artifacts that must NOT leak."""
    claude = prof / ".claude"
    (claude / "skills" / "greet-helper").mkdir(parents=True)
    (claude / "skills" / "greet-helper" / "SKILL.md").write_text("# greet\n")
    (claude / "CLAUDE.md").write_text("stack identity\n")
    (prof / "settings.json").write_text('{"permissions":{"defaultMode":"acceptEdits"}}')
    # Container-only — the host backend must skip these (no hub host-side).
    (prof / ".mcp.json").write_text('{"mcpServers":{"hatago":{}}}')
    (prof / "hatago.config.json").write_text("{}")
    (prof / "Dockerfile.harnessed-x").write_text("FROM scratch\n")


class TestHostHomePaths:
    def test_host_home_is_keyed_by_stack_and_harness_only(self, monkeypatch, tmp_path):
        """bd harnessed-8px.12: --host isolates CONFIGURATION and the STACK defines it, so the
        config dir is the stack identity. Nothing project-specific lives in there."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") == tmp_path / "harnessed" / "home" / "s" / "claude"

    def test_host_home_differs_per_harness(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") != paths.host_home("s", "omp")

    def test_host_home_distinct_from_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") != paths.profile_dir("s", "claude")

    def test_shim_is_a_sibling_not_a_child(self, monkeypatch, tmp_path):
        """The shim must survive the rebuild that rmtree's the config dir, so it cannot live inside
        it — and host-gc must not mistake it for a config dir."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        home = paths.host_home("s", "claude")
        assert paths.host_home_shim(home).parent == home.parent


class TestMaterialize:
    def test_copies_content_and_drops_container_artifacts(self, tmp_path):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        launcher._materialize_host_home(prof, home)

        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()
        assert (home / "CLAUDE.md").is_file()
        assert (home / "settings.json").is_file()
        # Container-only artifacts must never reach the host config dir.
        assert not (home / ".mcp.json").exists()
        assert not (home / "hatago.config.json").exists()
        assert not (home / "Dockerfile.harnessed-x").exists()

    def test_a_running_daemons_state_survives_the_rebuild(self, tmp_path):
        """bd harnessed-8px.20. The rebuild used to rmtree the whole config dir, deleting the state
        of a daemon that was still RUNNING against it. ~200ms after losing daemon.json the daemon
        declared auth_required and the credential file was gutted; the orphaned process then held
        control.sock with nothing valid behind it, so the next launch timed out reaching the
        background service. Observed live 2026-07-21 against a daemon alive 13h53m."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        # The daemon's per-project state dir: an opaque hex key, identified by its CONTENTS.
        state = home / "51ba83b8"
        state.mkdir(parents=True)
        (state / "daemon.json").write_text('{"port":1234}')
        (state / "daemon.log").write_text("running\n")
        (home / "daemon").mkdir()
        (home / "daemon" / "sock").write_text("x")

        launcher._materialize_host_home(prof, home)

        assert (state / "daemon.json").read_text() == '{"port":1234}', (
            "the running daemon's state was deleted — this is what gutted the credentials"
        )
        assert (state / "daemon.log").is_file()
        assert (home / "daemon" / "sock").is_file()
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()  # profile still landed

    def test_dropped_recipe_content_is_still_removed(self, tmp_path):
        """The 8px.20 preserve must not weaken the 8px.12 invariant: sparing daemon state is not a
        licence to spare recipe content. A dir that merely LOOKS like state (no daemon markers) is
        content and must go, or a removed recipe could leave files behind forever."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        home.mkdir()
        (home / "skills" / "dropped-recipe-skill").mkdir(parents=True)
        (home / "skills" / "dropped-recipe-skill" / "SKILL.md").write_text("stale")
        (home / "stale-top-level.md").write_text("residue")
        # Same 8-hex shape as a daemon key, but NO daemon markers — this is not state.
        decoy = home / "deadbeef"
        decoy.mkdir()
        (decoy / "SKILL.md").write_text("recipe content wearing a hex name")

        launcher._materialize_host_home(prof, home)

        assert not (home / "skills" / "dropped-recipe-skill").exists()
        assert not (home / "stale-top-level.md").exists()
        assert not decoy.exists(), "a hex-named dir without daemon markers is content, not state"

    def test_a_state_symlink_is_removed_not_followed(self, tmp_path):
        """Selective deletion must never follow a symlink out of the config dir. _share_host_claude_state
        links projects/ etc. at the real ~/.claude — deleting through one would take the user's own
        transcripts with it."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        outside = tmp_path / "real-claude" / "projects"
        outside.mkdir(parents=True)
        (outside / "transcript.jsonl").write_text("precious")
        home.mkdir()
        (home / "projects").symlink_to(outside)

        launcher._materialize_host_home(prof, home)

        assert (outside / "transcript.jsonl").read_text() == "precious", "followed a symlink out"
        assert not (home / "projects").exists()

    @pytest.mark.parametrize("marker", launcher._DAEMON_STATE_MARKERS)
    def test_any_single_daemon_marker_spares_the_dir(self, tmp_path, marker):
        """bd harnessed-8px.20 AC4. The observed gutting ran through `daemon-auth-status.json` — the
        daemon lost its state, wrote `{"status":"auth_required"}` there, and the credential file was
        emptied ~200ms later. Only `daemon.json`/`daemon.log` were ever covered by a test, so
        trimming the marker tuple to those two would silently reopen the exact path that bit us.
        Each marker must be sufficient ON ITS OWN."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        state = home / "51ba83b8"
        state.mkdir(parents=True)
        (state / marker).write_text("{}")

        launcher._materialize_host_home(prof, home)

        assert (state / marker).is_file(), f"{marker} alone did not identify the dir as daemon state"

    def test_every_projects_daemon_state_survives_not_just_one(self, tmp_path):
        """bd harnessed-8px.20 AC3. One config dir holds a state dir PER PROJECT, so a user with
        several projects open has several live daemons behind one rebuild. Sparing only the first
        would still wedge the rest."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        keys = ("51ba83b8", "d8551d86", "0a1b2c3d")
        for key in keys:
            (home / key).mkdir(parents=True)
            (home / key / "daemon.json").write_text(f'{{"key":"{key}"}}')

        launcher._materialize_host_home(prof, home)

        for key in keys:
            assert (home / key / "daemon.json").read_text() == f'{{"key":"{key}"}}', (
                f"daemon state for {key} was deleted"
            )

    def test_rebuilding_one_stacks_config_dir_leaves_another_stacks_alone(self, tmp_path):
        """bd harnessed-8px.20 AC3. Config dirs are keyed per stack (8px.12) and sit as SIBLINGS, so
        launching stack A must not reach into stack B's dir and de-auth a daemon serving it. Nothing
        in the current code walks the parent — this pins that, because the blast radius of getting it
        wrong is another stack's live session."""
        prof = tmp_path / "prof"
        prof.mkdir()
        _fake_profile(prof)
        home_a, home_b = tmp_path / "homes" / "stack-a", tmp_path / "homes" / "stack-b"
        (home_b / "51ba83b8").mkdir(parents=True)
        (home_b / "51ba83b8" / "daemon.json").write_text('{"stack":"b"}')
        (home_b / "settings.json").write_text('{"stack":"b"}')

        launcher._materialize_host_home(prof, home_a)

        assert (home_b / "51ba83b8" / "daemon.json").read_text() == '{"stack":"b"}'
        assert (home_b / "settings.json").read_text() == '{"stack":"b"}', (
            "rebuilding stack A's config dir reached into stack B's"
        )

    def test_the_real_credentials_file_survives_a_rebuild(self, tmp_path):
        """bd harnessed-8px.20 AC4. The credential file is the thing that actually got gutted, and it
        lives OUTSIDE the config dir — reached through a symlink `_share_host_claude_state` plants.
        The generic 'do not follow a symlink' test uses projects/; this names the vector that caused
        the P0, so a regression reads as what it is rather than as an unrelated symlink bug.

        Scope: this covers the REBUILD half of the chain only. Whether a daemon that keeps its state
        also refrains from writing auth_required is the daemon's behaviour, not ours, and is not
        asserted here."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        real_claude = tmp_path / "real-claude"
        real_claude.mkdir()
        creds = real_claude / ".credentials.json"
        creds.write_text('{"accessToken":"live-token","refreshToken":"r","expiresAt":9999}')
        home.mkdir()
        (home / ".credentials.json").symlink_to(creds)

        launcher._materialize_host_home(prof, home)

        assert json.loads(creds.read_text())["accessToken"] == "live-token", (
            "the rebuild gutted the live credential file through the symlink"
        )

    def test_rebuilds_home_from_scratch(self, tmp_path):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        home.mkdir()
        (home / "stale-skill.md").write_text("removed recipe residue")
        launcher._materialize_host_home(prof, home)
        assert not (home / "stale-skill.md").exists()


class TestShareClaudeState:
    def test_symlinks_session_state_and_live_auth(self, monkeypatch, tmp_path):
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"x"}')
        (real / ".claude.json").write_text('{"account":"a"}')
        (real / "projects").mkdir()
        (real / "projects" / "p.jsonl").write_text("transcript")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        # session state: symlinked to the real ~/.claude (shared, resumable)
        assert (home / "projects").is_symlink()
        assert (home / "projects" / "p.jsonl").read_text() == "transcript"
        for name in ("file-history", "todos", "tasks", "session-env", "shell-snapshots"):
            assert (home / name).is_symlink()
        # auth token: symlinked (live refresh propagates)
        assert (home / ".credentials.json").is_symlink()
        assert (home / ".credentials.json").read_text() == '{"token":"x"}'
        # account: COPIED (isolated writes), not a symlink
        assert (home / ".claude.json").is_file()
        assert not (home / ".claude.json").is_symlink()

    def test_a_configured_oauth_token_suppresses_the_credential_symlink(self, monkeypatch, tmp_path):
        """`CLAUDE_CODE_OAUTH_TOKEN` takes precedence over the credentials file, so with one
        configured the file is dead weight — and maintaining it carries the whole 8px.10
        symlink-replacement failure mode for nothing. The container path already refuses to mount a
        credential file under a token (`_claude_creds_seed_mount`); this is the host's half."""
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"x"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-PLACEHOLDER")
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        assert not (home / ".credentials.json").exists()
        # Session state is unrelated to auth and must still be shared.
        assert (home / "projects").is_symlink()

    def test_a_stale_per_stack_credential_is_removed_under_a_token(self, monkeypatch, tmp_path):
        """A home built before the token was configured still holds a credentials file — as a
        REGULAR file, since a refresh replaces the symlink. Leaving it behind means the very stale
        copy this gate exists to retire outlives the switch to token auth."""
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"shared"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-PLACEHOLDER")
        home = tmp_path / "home"
        home.mkdir()
        (home / ".credentials.json").write_text('{"token":"stale-per-stack"}')

        launcher._share_host_claude_state(home)

        assert not (home / ".credentials.json").exists()

    def test_the_shared_credential_is_never_deleted(self, monkeypatch, tmp_path):
        """Only the per-stack copy is ours to retire. `~/.claude/.credentials.json` is the user's
        own login, outside any stack — deleting it would log them out of plain `claude` too."""
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"shared"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-PLACEHOLDER")
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        assert (real / ".credentials.json").read_text() == '{"token":"shared"}'

    def test_no_token_keeps_the_symlink(self, monkeypatch, tmp_path):
        """Regression guard: without a token the credential file is load-bearing. Removing it here
        would log the user out on every launch."""
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"x"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        assert (home / ".credentials.json").is_symlink()

    def test_an_empty_token_var_is_not_a_configured_token(self, monkeypatch, tmp_path):
        """`CLAUDE_CODE_OAUTH_TOKEN=` (exported empty) is how a shell profile disables it. Treating
        the mere presence of the name as configured would log the user out with no way back."""
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"x"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "")
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        assert (home / ".credentials.json").is_symlink()

    def test_claude_json_seeded_from_home_level_not_config_dir(self, monkeypatch, tmp_path):
        # The account file is $HOME/.claude.json — NOT ~/.claude/.claude.json. Seed from the right one.
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude.json").write_text('{"account":"real"}')            # HOME-level (correct)
        (fake_home / ".claude" / ".claude.json").write_text('{"account":"WRONG"}')  # decoy inside dir
        (fake_home / ".claude" / ".credentials.json").write_text('{"t":"x"}')
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(fake_home))
        home = tmp_path / "stackhome"
        home.mkdir()
        launcher._share_host_claude_state(home)
        assert (home / ".claude.json").read_text() == '{"account":"real"}'

    @staticmethod
    def _cred(marker: str) -> str:
        """A structurally REAL credential carrying a marker, so a test can tell which copy won.

        The bodies here used to be bare stubs carrying only a marker key. Those stopped being valid
        once _rescue_host_credentials began gating on usability (a stub has no accessToken, so it is
        indistinguishable from the gutted file the gate exists to reject). The invariants these tests
        assert are unchanged — only the fixtures had to become credential-shaped.
        """
        return json.dumps({
            "claudeAiOauth": {
                "accessToken": f"at-{marker}",
                "refreshToken": f"rt-{marker}",
                "expiresAt": 1784662315830,
                "scopes": ["user:inference"],
            }
        })

    @staticmethod
    def _gutted() -> str:
        """The real-world poison (observed 2026-07-21): envelope intact, tokens emptied, expiry 0."""
        return json.dumps({
            "claudeAiOauth": {
                "accessToken": "",
                "refreshToken": "",
                "expiresAt": 0,
                "refreshTokenExpiresAt": 1787005628797,
                "scopes": ["user:inference"],
                "subscriptionType": 3,
            }
        })

    def _shared(self, monkeypatch, tmp_path, body=None, mtime=None):
        """Point HOME at a fake home and optionally seed the SHARED ~/.claude credential."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        real = fake_home / ".claude" / ".credentials.json"
        if body is not None:
            real.write_text(body)
            assert mtime is not None, "_shared: mtime must be provided when body is set"
            os.utime(real, (mtime, mtime))
        return real

    def _stack_cred(self, stack, project, body, mtime, *, symlink_to=None):
        """A per-(stack, harness, project) config dir holding a credential file. A REGULAR file is
        what a token refresh leaves behind, having replaced the symlink we created."""
        home = paths.host_homes_root() / stack / "claude" / project
        home.mkdir(parents=True, exist_ok=True)
        cred = home / ".credentials.json"
        if symlink_to is not None:
            cred.symlink_to(symlink_to)
            return home
        cred.write_text(body)
        os.utime(cred, (mtime, mtime))
        return home

    def test_refreshed_token_is_promoted_before_the_wipe(self, monkeypatch, tmp_path):
        """bd harnessed-8px.10: Claude rewrites .credentials.json on refresh, and the rewrite
        REPLACES our symlink with a regular file — so the fresh token sits in the stack config dir
        while the shared ~/.claude copy goes stale. _materialize_host_home then rmtree's the config
        dir and we re-link to the stale copy, logging the user out every token lifetime."""
        real = self._shared(monkeypatch, tmp_path, self._cred("stale"), 100_000)
        self._stack_cred("s", "proj1", self._cred("fresh"), 200_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("fresh")
        assert oct(real.stat().st_mode)[-3:] == "600"  # never widen a credential file

    def test_rescues_across_stacks_and_projects_not_just_the_launching_one(
        self, monkeypatch, tmp_path
    ):
        """A config dir is keyed <stack>/<harness>/<project>, so one stack open in three projects has
        three. Rescuing only the launching home would converge lazily: a token refreshed in project A
        would not reach the shared copy until project A relaunched, so launching project B first
        would still restore a stale token and force a login."""
        real = self._shared(monkeypatch, tmp_path, self._cred("stale"), 100_000)
        self._stack_cred("stack-a", "proj1", self._cred("older"), 150_000)
        self._stack_cred("stack-b", "proj2", self._cred("newest"), 300_000)
        self._stack_cred("stack-b", "proj3", self._cred("middle"), 200_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("newest")

    def test_older_stack_token_never_overwrites_a_newer_shared_one(self, monkeypatch, tmp_path):
        """A stack home left over from days ago must not drag the shared token backwards."""
        # Both sides are USABLE credentials, so this exercises the mtime guard specifically — with a
        # stub body it would pass for the wrong reason (rejected as unusable, never compared).
        real = self._shared(monkeypatch, tmp_path, self._cred("current"), 200_000)
        self._stack_cred("s", "proj1", self._cred("ancient"), 100_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("current")

    def test_a_gutted_credential_never_overwrites_a_working_shared_one(self, monkeypatch, tmp_path):
        """bd harnessed-8px.10, second failure mode — observed live 2026-07-21.

        A GUTTED credential (envelope intact: scopes/subscriptionType/refreshTokenExpiresAt; but
        accessToken and refreshToken empty and expiresAt 0) sat in a stack home as the NEWEST file.
        The rescue guarded only on mtime, so it promoted the empty file over a perfectly good shared
        token — and every stack sourcing from shared was then logged out. One stack going empty
        poisoned all of them.
        """
        real = self._shared(monkeypatch, tmp_path, self._cred("good"), 100_000)
        self._stack_cred("s", "proj1", self._gutted(), 900_000)  # newest, but unusable
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("good"), (
            "an emptied credential was promoted over a working one — every stack is now logged out"
        )

    def test_a_gutted_shared_copy_is_healed_from_a_usable_home(self, monkeypatch, tmp_path):
        """The mtime guard alone would preserve an already-poisoned shared copy FOREVER: it is
        newer than every good token, so nothing may overwrite it, and every launch re-links to a
        credential with no token in it. Usability has to beat freshness in that direction too."""
        real = self._shared(monkeypatch, tmp_path, self._gutted(), 900_000)  # poisoned AND newest
        self._stack_cred("s", "proj1", self._cred("survivor"), 100_000)  # older, but real
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("survivor"), (
            "a gutted shared copy was left in place — the user stays logged out on every launch"
        )

    def test_all_candidates_gutted_leaves_the_shared_copy_untouched(self, monkeypatch, tmp_path):
        """Nothing usable anywhere is a real state (a genuine logout). Do not thrash the shared
        file — leave it exactly as found so the next real login is the thing that fixes it."""
        real = self._shared(monkeypatch, tmp_path, self._cred("good"), 100_000)
        self._stack_cred("s", "proj1", self._gutted(), 900_000)
        self._stack_cred("s", "proj2", self._gutted(), 800_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == self._cred("good")

    def test_unparseable_credential_is_not_a_candidate(self, monkeypatch, tmp_path):
        """Refusing on doubt costs nothing here — this gate only ever decides whether to overwrite
        a working file — and a truncated/corrupt write must never win on being newest."""
        real = self._shared(monkeypatch, tmp_path, self._cred("good"), 100_000)
        self._stack_cred("s", "proj1", "{not json at all", 900_000)
        launcher._rescue_host_credentials()  # must not raise
        assert real.read_text() == self._cred("good")

    def test_an_expired_access_token_is_still_worth_rescuing(self, monkeypatch, tmp_path):
        """The gate must NOT reject on expiry. An expired ACCESS token whose refresh token is still
        good is the normal healthy state — it is precisely what the refresh flow exists to renew, so
        discarding it would throw away the credential we most need to keep."""
        expired = json.dumps({"claudeAiOauth": {
            "accessToken": "at-expired", "refreshToken": "rt-still-good", "expiresAt": 1,
        }})
        real = self._shared(monkeypatch, tmp_path, self._cred("older"), 100_000)
        self._stack_cred("s", "proj1", expired, 900_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == expired

    def test_intact_symlink_is_not_a_rescue_candidate(self, monkeypatch, tmp_path):
        """A surviving symlink means that home's refresh propagated live — it already IS the shared
        copy, so treating it as a candidate would be a self-copy."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"shared"}', 100_000)
        self._stack_cred("s", "proj1", None, None, symlink_to=real)
        launcher._rescue_host_credentials()  # must not raise
        assert real.read_text() == '{"token":"shared"}'

    def test_first_ever_launch_has_nothing_to_rescue(self, monkeypatch, tmp_path):
        real = self._shared(monkeypatch, tmp_path)
        launcher._rescue_host_credentials()  # no homes on disk at all — must not raise
        assert not real.exists()

    def test_a_configured_token_skips_the_rescue_entirely(self, monkeypatch, tmp_path):
        """Under a token the credential file is ignored by the harness, so promoting a per-stack
        copy into the shared one is pure risk: the rescue's whole job is keeping a file alive that
        nothing reads, and a gutted candidate would be written over the user's real login."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"shared"}', 100_000)
        self._stack_cred("s", "proj1", self._cred("newer"), 900_000)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-PLACEHOLDER")

        launcher._rescue_host_credentials()

        assert real.read_text() == '{"token":"shared"}'  # untouched — no promotion happened

    def test_plan_rescues_before_materialize_wipes_the_home(self, monkeypatch, tmp_path):
        """The ordering IS the fix: run the rescue after the rmtree and the fresh token is gone."""
        src = inspect.getsource(launcher._host_launch_plan)
        assert src.index("_rescue_host_credentials") < src.index("_materialize_host_home")

    def test_missing_source_creates_dirs_no_crash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fresh"))
        home = tmp_path / "home"
        home.mkdir()
        launcher._share_host_claude_state(home)  # must not raise
        assert (home / "projects").is_symlink()          # created + linked
        assert not (home / ".credentials.json").exists()  # no token to share


class TestLaunchPlan:
    def test_plan_materializes_and_returns_argv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)

        home, argv, cwd, _rebuilt = launcher._host_launch_plan("s", "claude", tmp_path)

        assert home == paths.host_home("s", "claude")
        assert argv == ["claude"]  # content-only: no --mcp-config
        assert cwd == tmp_path
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()


class TestHostAssembleIntegration:
    """The bug that shipped in the first spike: `--host` required `harnessed build` (a full container
    image build). Host mode must assemble the real catalog stack IN-PROCESS with no pre-build and no
    podman — this guards that the greet skill lands from a cold start."""

    def test_hostspike_assembles_and_plans_without_prebuild(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        assert not paths.is_built("hostspike", "claude")  # cold: nothing pre-built

        assemble(None, "hostspike", paths.profiles_root().parent, "claude", strict=True)
        home, argv, cwd, _rebuilt = launcher._host_launch_plan("hostspike", "claude", tmp_path)

        assert cwd == tmp_path
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()
        assert (home / "CLAUDE.md").is_file()
        assert argv == ["claude"]
        # No container/MCP artifacts leak from a real assemble either.
        assert not (home / ".mcp.json").exists()


class TestHostCliRouting:
    def test_launch_host_flag_assembles_and_execs_claude(self, monkeypatch, tmp_path):
        """End-to-end CLI path: `launch <stack> claude --host` must assemble in-process (no
        pre-build, no podman) and hand off to claude with CLAUDE_CONFIG_DIR — captured here instead
        of actually exec'ing."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(file=file, argv=argv, ccd=env.get("CLAUDE_CONFIG_DIR"))
            raise SystemExit(0)  # execvpe would replace the process; halt cleanly instead

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"]
        )

        assert result.exit_code == 0, result.output
        assert captured["file"] == "claude"
        # Always --strict-mcp-config (even content-only) so global .claude.json servers never leak.
        assert captured["argv"][0] == "claude"
        assert "--strict-mcp-config" in captured["argv"]
        assert captured["ccd"] == str(paths.host_home("hostspike", "claude"))
        assert paths.is_built("hostspike", "claude")  # profile assembled during the launch itself

    def test_host_run_brings_up_the_stacks_sidecars(self, monkeypatch, tmp_path):
        """bd harnessed-2sm: `services:` is a property of the STACK, not of the backend.

        `launch` ensured them; `_launch_host` did not, so every beads stack under `host-run` came up
        with no server, no socket and no data dir — and nothing in the output said a declared service
        had been skipped. A socket-backed sidecar composes with a host agent for free: the socket is
        a filesystem object in the persist dir the service bind-mounts, so the host process dials the
        same path the container serves it on.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        ensured: list = []

        patch_all(monkeypatch, "_service_refs", lambda _s: ["ping"])
        patch_all(monkeypatch, "_runtime", lambda: "podman")
        monkeypatch.setattr(
            launcher, "_ensure_services", lambda rt, stack, **kw: ensured.append((rt, stack))
        )
        # hostspike declares no recipe owning ping's data dir, so resolving it against that stack is a
        # genuine SchemaError — the fake service ref above is only here to prove the CALL happens.
        # Socket resolution has its own coverage in test_project_scoped_services.py.
        patch_all(monkeypatch, "svc_socket_env", lambda *_a, **_k: {})
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])

        assert result.exit_code == 0, result.output
        assert ensured == [("podman", "hostspike")]

    def test_host_run_runs_recipe_init(self, monkeypatch, tmp_path):
        """Recipe `init:` was wired only into the container attach shell, so declaring it was a
        silent no-op under `host-run` — the same container-only wiring as harnessed-2sm/-162/-5ek."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        ran: list = []

        patch_all(monkeypatch, "_service_refs", lambda _s: [])
        patch_all(monkeypatch, "_host_run_inits", lambda *a, **k: ran.append(a[0]))
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])
        assert result.exit_code == 0, result.output
        assert ran == ["hostspike"]

    def test_host_init_runs_the_command_and_fails_fast(self, monkeypatch, tmp_path):
        import typer

        from harnessed.schema import InitSpec, Recipe

        marker = tmp_path / "ran"
        ok = Recipe(name="r-ok", init=InitSpec(run=f"touch {marker}"))
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [ok]))
        launcher._host_run_inits("s", tmp_path, harness="claude")
        assert marker.is_file()

        bad = Recipe(name="r-bad", init=InitSpec(run="exit 3"))
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [bad]))
        with pytest.raises(typer.Exit):  # an agent must not start on a half-initialized tool
            launcher._host_run_inits("s", tmp_path, harness="claude")

    def test_host_run_needs_no_runtime_when_the_stack_has_no_services(self, monkeypatch, tmp_path):
        """A service-less host launch must not require podman to be installed — `_runtime()` is only
        touched when the stack actually declares something to start."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))

        def boom():
            raise AssertionError("_runtime() must not be called for a service-less stack")

        patch_all(monkeypatch, "_service_refs", lambda _s: [])
        patch_all(monkeypatch, "_runtime", boom)
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])
        assert result.exit_code == 0, result.output

    def test_host_settings_inherit_the_host_claude_default_mode(self, monkeypatch, tmp_path):
        """bd harnessed-8px.8, found by a REAL --host launch: the session came up in acceptEdits
        even though the host ~/.claude declared `auto`.

        `launch` diverted to _launch_host and returned BEFORE the container path's
        _merge_host_claude_settings call, so _materialize_host_home copied the bare assemble-time
        FLOOR into the config dir and the host's own mode never crossed over. Container mode was
        unaffected, which is why unit tests on the container path stayed green.
        """
        fake_home = tmp_path / "fakehome"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"defaultMode": "auto", "mode": "auto"}})
        )
        monkeypatch.setenv("HOME", str(fake_home))  # _merge_host_claude_settings reads Path.home()
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"]
        )

        assert result.exit_code == 0, result.output
        home = paths.host_home("hostspike", "claude")
        settings = json.loads((home / "settings.json").read_text())
        # The host's mode wins: merge_settings applies required.defaultMode with setdefault, so the
        # harnessed floor is a floor, not an override.
        assert settings["permissions"]["defaultMode"] == "auto"

    def test_agent_process_inherits_the_folder_env_contract(self, monkeypatch, tmp_path):
        """bd harnessed-0tk.7: a container launch sets the contract box-wide (`podman run -e`), so
        every process in it agrees. The host has no box — os.environ IS the box. Before the fix
        _host_run_setups built a private env copy and the exec'd agent saw none of it."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(env=env)
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"]
        )

        assert result.exit_code == 0, result.output
        env = captured["env"]
        assert env["HARNESS"] == "claude"
        assert env["PROJECT_DIR"] == str(tmp_path.resolve())
        for var in ("MAIN_REPO_DIR", "HARNESSED_GIT_COMMON_DIR", "HOST_WORKSPACE_DIR",
                    "CONTAINER_WORKSPACE_DIR", "HOST_HOME"):
            assert env[var]
        # git consumes GIT_COMMON_DIR itself — exporting it would hijack common-dir resolution.
        assert "GIT_COMMON_DIR" not in env




class TestStackFingerprintGate:
    """bd harnessed-8px.12. The materialize used to rmtree the config dir on EVERY launch. That one
    behaviour caused three separate problems: it forced the project into the config-dir key (so a
    second launch could not wipe a live one), it made every install script re-run per project per
    launch, and it reset `.claude.json` so approvals never persisted.

    The rebuild is still WHOLESALE — the dir stays a pure function of (profile + installs), so a
    recipe dropped from the stack still cannot leave files behind — it just happens only when the
    stack actually changed.
    """

    def _prof(self, tmp_path):
        prof = tmp_path / "prof"
        prof.mkdir()
        _fake_profile(prof)
        return prof

    def test_unchanged_fingerprint_leaves_the_home_untouched(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is True
        launcher._stamp_host_home(home, "fp-1")  # the caller stamps, AFTER installs succeed
        # Something the AGENT wrote after the build — it must survive an unchanged relaunch.
        (home / "runtime-state.json").write_text("session data")
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is False
        assert (home / "runtime-state.json").is_file()

    def test_changed_fingerprint_rebuilds_wholesale(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        launcher._stamp_host_home(home, "fp-1")
        (home / "stale-recipe-leftover.md").write_text("from a recipe no longer in the stack")
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-2") is True
        # The whole point of keeping a wholesale wipe: a departed recipe leaves nothing behind.
        assert not (home / "stale-recipe-leftover.md").exists()
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()

    def test_missing_stamp_rebuilds(self, tmp_path):
        """A hand-deleted or half-written dir must not be trusted."""
        prof, home = self._prof(tmp_path), tmp_path / "home"
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        launcher._stamp_host_home(home, "fp-1")
        (home / launcher._HOST_STACK_FINGERPRINT).unlink()
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is True

    def test_stamp_is_written_after_the_installs(self, tmp_path):
        """The stamp certifies content that is not complete until every install.script has run."""
        src = inspect.getsource(launcher.HostBackend.provision_tools)
        assert src.index("_host_run_installs(") < src.index("_stamp_host_home(")

    def test_no_fingerprint_keeps_unconditional_rebuild(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        assert launcher._materialize_host_home(prof, home) is True
        assert launcher._materialize_host_home(prof, home) is True

    def test_fingerprint_includes_the_harnessed_version(self):
        """A host launch has no image build to force a refresh, so a change to what emit writes —
        with a byte-identical recipe closure — would otherwise serve stale content forever."""
        from harnessed import __version__
        src = inspect.getsource(launcher._host_stack_fingerprint)
        assert "__version__" in src and __version__


class TestLegacyPerProjectMigration:
    """The old key was <stack>/<harness>/<project_hash>; the new config dir IS <stack>/<harness>, so
    every old per-project dir is now a child of it. They hold real tokens (bd harnessed-8px.10), so
    the rmtree must not be what removes them."""

    def _legacy(self, home, name, cred_body="tok"):
        d = home / name
        d.mkdir(parents=True)
        (d / "settings.json").write_text("{}")
        (d / ".credentials.json").write_text(cred_body)
        return d

    def test_legacy_dir_is_scrubbed_not_just_wiped(self, tmp_path, monkeypatch):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        legacy = self._legacy(home, "a1b2c3d4")
        scrubbed = []
        real_scrub = launcher._scrub_host_home
        patch_all(monkeypatch, "_scrub_host_home",
            lambda p: (scrubbed.append(p.name), real_scrub(p))[1],
        )
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        assert scrubbed == ["a1b2c3d4"], "legacy dir must go through the scrub path, not the rmtree"
        assert not legacy.exists()

    def test_non_config_eight_hex_dir_is_left_alone(self, tmp_path):
        """Matched narrowly: an 8-hex name alone is not enough to delete something."""
        home = tmp_path / "home"
        d = home / "deadbeef"
        d.mkdir(parents=True)
        (d / "notes.md").write_text("a recipe's own data")
        launcher._migrate_legacy_host_homes(home)
        assert d.exists()


class TestHostGC:
    """host-gc under the per-stack layout: an orphan is a config dir whose STACK is gone from the
    catalog — a far better signal than the old one-way project_hash, which could not be resolved
    back to anything."""

    def _home(self, stack, harness="claude", *, cred=None, legacy=None):
        home = paths.host_homes_root() / stack / harness
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text("{}")
        if cred is not None:
            (home / ".credentials.json").write_text(cred)
        if legacy:
            d = home / legacy
            d.mkdir(exist_ok=True)
            (d / "settings.json").write_text("{}")
        return home

    def _run(self, monkeypatch, tmp_path, *args):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        return runner.invoke(launcher.app, ["host-gc", *args])

    def test_lists_real_stack_as_ok_and_unknown_stack_as_orphan(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike")          # a real catalog stack
        self._home("deleted-stack-xyz")  # not in any catalog root
        r = self._run(monkeypatch, tmp_path)
        assert r.exit_code == 0, r.output
        assert "hostspike/claude" in r.output and "deleted-stack-xyz/claude" in r.output
        assert "ORPHAN" in r.output

    def test_shim_sibling_is_not_listed_as_a_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        home = self._home("hostspike")
        paths.host_home_shim(home).mkdir(parents=True, exist_ok=True)
        r = self._run(monkeypatch, tmp_path)
        assert "claude.home" not in r.output

    def test_flags_a_real_credential_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike", cred="tok")
        assert "REAL-FILE" in self._run(monkeypatch, tmp_path).output

    def test_surfaces_legacy_per_project_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike", legacy="a1b2c3d4")
        assert "legacy" in self._run(monkeypatch, tmp_path).output

    def test_prune_removes_only_the_orphan(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        live = self._home("hostspike")
        gone = self._home("deleted-stack-xyz")
        r = self._run(monkeypatch, tmp_path, "--prune")
        assert r.exit_code == 0, r.output
        assert live.exists(), "a stack still in the catalog must never be removed"
        assert not gone.exists()

    def test_dry_run_deletes_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        gone = self._home("deleted-stack-xyz")
        r = self._run(monkeypatch, tmp_path, "--prune", "--dry-run")
        assert "would remove" in r.output
        assert gone.exists()

    def test_prune_scrubs_the_credential_before_deleting(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("deleted-stack-xyz", cred="a-real-token")
        scrubbed = []
        patch_all(monkeypatch, "_scrub_host_home", lambda p: scrubbed.append(p))
        self._run(monkeypatch, tmp_path, "--prune")
        assert len(scrubbed) == 1, "removal must go through the scrub path, never a bare rmtree"


class TestSecondLaunchSkipsInstalls:
    """bd harnessed-8px.12 acceptance: an install is logically once per STACK. It only ever ran on
    every launch because the materialize wiped its output on every launch."""

    def _launch(self, tmp_path, monkeypatch, calls):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        patch_all(monkeypatch, "_host_run_installs",
            lambda stack, project_path, *, harness, home: calls.append(stack),
        )
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        return runner.invoke(
            launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"]
        )

    def test_installs_run_on_first_launch_and_are_skipped_on_the_second(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        first = self._launch(tmp_path, monkeypatch, calls)
        assert first.exit_code == 0, first.output
        assert calls == ["hostspike"], "first launch must build the home and run installs"

        second = self._launch(tmp_path, monkeypatch, calls)
        assert second.exit_code == 0, second.output
        assert calls == ["hostspike"], "unchanged stack must not re-run installs"
        assert "installs skipped" in second.output

    def test_a_changed_stack_fingerprint_reruns_installs(self, monkeypatch, tmp_path):
        calls: list[str] = []
        self._launch(tmp_path, monkeypatch, calls)
        assert calls == ["hostspike"]
        # Simulate a recipe edit: the stamp no longer matches the stack's recipe closure.
        home = paths.host_home("hostspike", "claude")
        (home / launcher._HOST_STACK_FINGERPRINT).write_text("something-else\n")
        self._launch(tmp_path, monkeypatch, calls)
        assert calls == ["hostspike", "hostspike"], "a changed stack must rebuild and re-install"


class TestHostHomeLock:
    """bd harnessed-8px.12 criterion 4. The gate makes contention rare — an unchanged stack never
    rebuilds — but two launches that both see a CHANGED fingerprint must not rebuild concurrently."""

    def test_lock_actually_excludes_a_second_holder(self, tmp_path):
        import fcntl as _f
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            other = open(home.parent / f"{home.name}.lock", "w")
            try:
                with pytest.raises(BlockingIOError):
                    _f.flock(other.fileno(), _f.LOCK_EX | _f.LOCK_NB)
            finally:
                other.close()

    def test_lock_is_released_on_exit(self, tmp_path):
        import fcntl as _f
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            pass
        other = open(home.parent / f"{home.name}.lock", "w")
        try:
            _f.flock(other.fileno(), _f.LOCK_EX | _f.LOCK_NB)  # must not raise
        finally:
            other.close()

    def test_lock_file_is_a_sibling_so_the_rebuild_cannot_delete_it(self, tmp_path):
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            pass
        assert (home.parent / "claude.lock").is_file()
        assert not home.exists(), "the lock must not create the config dir it guards"

    def test_lock_spans_the_installs_not_just_the_rebuild(self):
        """Releasing after the rebuild would let a second launch see a matching stamp, skip
        installs, and exec the agent while the first launch's scripts were still writing."""
        src = inspect.getsource(launcher._launch_host)
        # Match the CALL sites, not the prose — an earlier comment names the operations too.
        # Both operations are the backend seam's (HostBackend.materialize_config runs the plan,
        # provision_tools(FIRST_START) runs the installs); the lock stays in the sequencer because
        # it spans BOTH, and neither op can re-acquire it (flock on a second fd would deadlock).
        lock_at = src.index("with _host_home_lock(")
        assert lock_at < src.index("backend.materialize_config(")
        assert lock_at < src.index("backend.provision_tools(spec, FIRST_START)")
        # ...and the attach phase is OUTSIDE it: a setup script can prompt, and holding an
        # exclusive flock across a TTY prompt would hang any concurrent launch of the same stack.
        assert src.index("backend.provision_tools(spec, ATTACH)") > src.index(
            "backend.provision_tools(spec, FIRST_START)"
        )


class TestFailedInstallDoesNotStamp:
    """bd harnessed-8px.15, found by a REAL host launch. The stamp was written at the end of the
    content copy, but installs run AFTER that — so an install that failed left a matching stamp on
    disk. The next launch then saw "unchanged", skipped the rebuild AND the installs, and started
    the agent against a permanently half-installed stack. Silently: the exact failure mode this
    whole epic exists to remove, reintroduced by its own optimisation."""

    def _launch(self, tmp_path, monkeypatch, *, install_fails):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))

        def _installs(stack, project_path, *, harness, home):
            if install_fails:
                raise SystemExit(1)  # what _host_run_installs does on a failed script

        patch_all(monkeypatch, "_host_run_installs", _installs)
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        return runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])

    def test_a_failed_install_leaves_no_stamp(self, monkeypatch, tmp_path):
        self._launch(tmp_path, monkeypatch, install_fails=True)
        home = paths.host_home("hostspike", "claude")
        assert not (home / launcher._HOST_STACK_FINGERPRINT).exists(), (
            "a stamp after a failed install makes the next launch skip the retry"
        )

    def test_the_next_launch_retries_after_a_failure(self, monkeypatch, tmp_path):
        self._launch(tmp_path, monkeypatch, install_fails=True)
        calls: list[str] = []
        patch_all(monkeypatch, "_host_run_installs",
            lambda stack, project_path, *, harness, home: calls.append(stack),
        )
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        r = runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])
        assert r.exit_code == 0, r.output
        assert calls == ["hostspike"], "the retry must actually re-run the installs"


class TestSettingsPropagateWithoutARebuild:
    """bd harnessed-8px.18. The 8px.12 fingerprint gate skips _materialize_host_home when the stack
    is unchanged — but that is what copies settings.json into the config dir. settings.json is NOT a
    pure function of the recipe closure the fingerprint covers: _merge_host_claude_settings folds in
    the host's live ~/.claude preferences and re-applies harnessed's required grants every launch.

    Caught on a real third launch: the 8px.17 duplicate-hook fix reached the profile and the live
    config dir kept running the doubled hooks, because nothing had changed the stack.
    """

    def test_settings_reach_the_home_even_when_the_stack_is_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")

        home, _a, _c, rebuilt = launcher._host_launch_plan("s", "claude", tmp_path, recipes=[])
        assert rebuilt is True
        # _host_launch_plan deliberately does NOT stamp — _launch_host does, only after the installs
        # succeed, so a failed install can never leave a matching stamp behind (70fb163).
        launcher._stamp_host_home(home, "fp-1")

        # A launch-time settings change: host prefs merged, or harnessed fixing what it emits.
        (prof / "settings.json").write_text('{"permissions":{"defaultMode":"auto"}}')

        home, _a, _c, rebuilt = launcher._host_launch_plan("s", "claude", tmp_path, recipes=[])
        assert rebuilt is False, "unchanged stack must not rebuild"
        assert json.loads((home / "settings.json").read_text())["permissions"]["defaultMode"] == "auto"

    def test_install_written_keys_survive_the_propagation(self, tmp_path, monkeypatch):
        """The 8px.18 propagation must not delete what an `install:` script wrote into the LIVE home.

        install scripts write into $HARNESSED_CONFIG_DIR — the home, not the profile (ccstatusline's
        `statusLine` block). 8px.12 skips those installs when the fingerprint matches, so a plain
        copy of the profile over the home destroyed the only copy and nothing put it back: the
        status line survived the first launch after a stack change and vanished on every restart.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s-ccsl", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")

        home, _a, _c, rebuilt = launcher._host_launch_plan("s-ccsl", "claude", tmp_path, recipes=[])
        assert rebuilt is True
        launcher._stamp_host_home(home, "fp-1")

        # What ccstatusline's install.sh does, into the home the installs actually target.
        live = home / "settings.json"
        data = json.loads(live.read_text())
        data["statusLine"] = {"type": "command", "command": "/cache/ccstatusline", "padding": 0}
        live.write_text(json.dumps(data))

        # Restart on an unchanged stack: installs are skipped, settings still propagate.
        home, _a, _c, rebuilt = launcher._host_launch_plan("s-ccsl", "claude", tmp_path, recipes=[])
        assert rebuilt is False, "unchanged stack must not rebuild"
        final = json.loads((home / "settings.json").read_text())
        assert final.get("statusLine", {}).get("command") == "/cache/ccstatusline", (
            "the install-written statusLine was wiped by the profile copy — ccstatusline is dead "
            "on every launch after the first"
        )

    def test_the_profile_still_wins_on_keys_it_defines(self, tmp_path, monkeypatch):
        """Carrying install-written keys over must not resurrect STALE values for keys the profile
        does define — that would defeat 8px.18 (live host prefs stop reaching the config dir)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s-win", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")

        home, _a, _c, _r = launcher._host_launch_plan("s-win", "claude", tmp_path, recipes=[])
        launcher._stamp_host_home(home, "fp-1")
        (home / "settings.json").write_text('{"permissions":{"defaultMode":"stale"}}')
        (prof / "settings.json").write_text('{"permissions":{"defaultMode":"auto"}}')

        home, _a, _c, _r = launcher._host_launch_plan("s-win", "claude", tmp_path, recipes=[])
        got = json.loads((home / "settings.json").read_text())["permissions"]["defaultMode"]
        assert got == "auto", "profile must win for keys it defines"

    def test_content_is_still_gated(self, tmp_path, monkeypatch):
        """Only settings.json is exempt — skills/rules ARE a function of the recipe closure, so a
        skipped rebuild must not resurrect them (that would defeat the gate entirely)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s2", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")
        home, *_ = launcher._host_launch_plan("s2", "claude", tmp_path, recipes=[])
        launcher._stamp_host_home(home, "fp-1")
        (prof / ".claude" / "skills" / "late-skill").mkdir(parents=True)
        (prof / ".claude" / "skills" / "late-skill" / "SKILL.md").write_text("# late\n")
        launcher._host_launch_plan("s2", "claude", tmp_path, recipes=[])
        assert not (home / "skills" / "late-skill").exists()


class TestHostRunVerb:
    """bd harnessed-ltj. `--host` was scaffolding bolted onto the container `launch` verb, where
    most flags (--fresh/--no-firewall/--shell/--mount-folder/--agent-start-folder) describe a pod
    that does not exist host-side. `host-run` is the first-class host entry point."""

    def _stub(self, monkeypatch, calls):
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: calls.append((stack, harness, path, rm)),
        )

    def test_host_run_dispatches_to_the_host_backend(self, monkeypatch, tmp_path):
        calls: list = []
        self._stub(monkeypatch, calls)
        r = runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike"])
        assert r.exit_code == 0, r.output
        assert calls == [("hostspike", "claude", str(tmp_path), False)]

    def test_the_harness_is_required(self, monkeypatch, tmp_path):
        """It used to default to claude, back when the stack led the positionals.

        It cannot now: `path` is the second positional, so a defaulted harness would make
        `host-run .` bind `.` as the harness and silently launch against the wrong directory —
        `_require_supported_harness` would reject it, but only after the user had typed something
        that reads correct. Requiring it keeps one grammar across both verbs, where the container
        backend has five harnesses and no sane default at all.
        """
        calls: list = []
        self._stub(monkeypatch, calls)
        r = runner.invoke(launcher.app, ["host-run", "--stack", "hostspike"])
        assert r.exit_code != 0
        assert calls == [], "must not reach the backend without a harness"

    def test_rm_is_forwarded(self, monkeypatch, tmp_path):
        calls: list = []
        self._stub(monkeypatch, calls)
        runner.invoke(launcher.app, ["host-run", "claude", str(tmp_path), "--stack", "hostspike", "--rm"])
        assert calls[0][3] is True

    def test_unsupported_harness_is_rejected(self, monkeypatch):
        calls: list = []
        self._stub(monkeypatch, calls)
        r = runner.invoke(launcher.app, ["host-run", "nosuchharness", "--stack", "hostspike"])
        assert r.exit_code == 1
        assert calls == [], "must not reach the backend with an unsupported harness"

    def test_container_only_flags_are_not_offered(self):
        """The whole point of the split: these cannot be passed to host-run at all."""
        r = runner.invoke(launcher.app, ["host-run", "claude", "--stack", "hostspike", "--fresh"])
        assert r.exit_code != 0


# --- omp host mode (#307) -------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_passthrough(monkeypatch):
    """`launcher._passthrough` is module-level and only `main()` clears it, so args one test sets
    otherwise leak into every later `CliRunner` invocation in the process.

    Autouse rather than pinned per test: the leak is invisible until some assertion happens to be
    exact about argv, which is how it reached CI green once already. A fixture makes the next CLI
    test here immune without its author having to know any of this.
    """
    monkeypatch.setattr(launcher, "_passthrough", [])


@pytest.fixture
def omp_real(monkeypatch, tmp_path):
    """A stand-in for the user's real `~/.omp/agent`, addressed via `PI_CODING_AGENT_DIR`."""
    real = tmp_path / "host-omp-agent"
    real.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
    return real


class TestHostOmpSource:
    def test_the_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "elsewhere"))
        assert hosthome._host_omp_source() == tmp_path / "elsewhere"

    def test_pi_config_dir_is_a_name_under_home_not_a_path(self, monkeypatch, tmp_path):
        """omp resolves it as `join(homedir(), PI_CONFIG_DIR || '.omp')`, so it can only ever RENAME
        the config root. Reading it as a path is the trap the issue flagged — it would send the
        share-back target somewhere omp never looks."""
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CONFIG_DIR", ".omp-alt")
        assert hosthome._host_omp_source() == tmp_path / ".omp-alt" / "agent"

    def test_defaults_to_dot_omp_agent(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        monkeypatch.delenv("PI_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert hosthome._host_omp_source() == tmp_path / ".omp" / "agent"

    def test_a_nested_launch_does_not_treat_the_parent_stack_as_the_user_store(
        self, monkeypatch, tmp_path
    ):
        """`_launch_host` exports `PI_CODING_AGENT_DIR` to the agent, so a stack launched from
        INSIDE a host omp session inherits the PARENT stack's agent dir — the same inheritance bd
        harnessed-8px.26 documents for `CLAUDE_CONFIG_DIR`.

        `_share_host_omp_state`'s self-link guard cannot catch it: parent and child homes differ, so
        it would link the child's shared state at the parent's. Those links resolve transitively
        right up until the parent's fingerprint changes and its rebuild unlinks them — after which
        the next omp to open the dangling `agent.db` creates a REAL database at the parent's path,
        silently taking that stack off the shared login.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
        monkeypatch.delenv("PI_CONFIG_DIR", raising=False)
        parent_home = paths.host_home("parent-stack", "omp")
        parent_home.mkdir(parents=True)
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(parent_home))

        # Falls through to the real user store, NOT the parent stack's home.
        assert hosthome._host_omp_source() == tmp_path / "userhome" / ".omp" / "agent"

    def test_a_user_override_outside_the_homes_root_is_still_honored(self, monkeypatch, tmp_path):
        """The guard suppresses another STACK's dir, never a dir the user genuinely runs under."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "my-own-omp"))
        assert hosthome._host_omp_source() == tmp_path / "my-own-omp"

    def test_the_nested_child_shares_with_the_real_store_not_the_parent(
        self, monkeypatch, tmp_path
    ):
        """The end-to-end consequence: a nested launch still gets ONE login."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
        monkeypatch.delenv("PI_CONFIG_DIR", raising=False)
        real = tmp_path / "userhome" / ".omp" / "agent"
        real.mkdir(parents=True)
        (real / "agent.db").write_text("the one login")
        parent_home = paths.host_home("parent-stack", "omp")
        parent_home.mkdir(parents=True)
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(parent_home))
        child_home = paths.host_home("child-stack", "omp")
        child_home.mkdir(parents=True)

        launcher._share_host_omp_state(child_home)

        assert (child_home / "agent.db").resolve() == (real / "agent.db").resolve()
        assert not (parent_home / "agent.db").exists()


class TestRenderOmpIdentityWhole:
    def test_the_files_are_whole_not_delimiter_marked_blocks(self, tmp_path):
        """#307 finding 7. The `<!-- BEGIN harnessed:<stack> -->` markers exist ONLY to let one
        stack's content be replaced inside a SHARED file. A per-stack agent dir has no other stack
        to share with, so the markers would be noise the model reads."""
        prof = tmp_path / "prof"
        rules = prof / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "a.md").write_text("do the thing\n")

        out = emit.render_omp_identity(prof, "you are the tracer", [rules / "a.md"])

        assert out["APPEND_SYSTEM.md"] == "you are the tracer\n"
        assert out["RULES.md"] == "## Rule: a.md\n\ndo the thing\n"
        assert "BEGIN harnessed:" not in "".join(out.values())

    def test_nothing_to_say_writes_no_file(self, tmp_path):
        assert emit.render_omp_identity(tmp_path / "prof", None, []) == {}

    def test_an_empty_rule_file_is_not_an_empty_section(self, tmp_path):
        prof = tmp_path / "prof"
        rules = prof / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "empty.md").write_text("   \n")
        assert "RULES.md" not in emit.render_omp_identity(prof, None, [rules / "empty.md"])

    def test_the_shared_block_path_renders_the_same_rule_text(self, tmp_path):
        """Both paths go through `_render_omp_rules`, so container and host agree on rule text.
        Divergence here would mean the same stack said different things on the two backends."""
        prof = tmp_path / "prof"
        rules = prof / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "a.md").write_text("do the thing\n")
        agent_dir = tmp_path / "shared"

        emit.write_omp_identity(prof, "s", None, [rules / "a.md"], agent_dir=agent_dir)

        whole = emit.render_omp_identity(prof, None, [rules / "a.md"])["RULES.md"]
        assert whole.strip() in (agent_dir / "RULES.md").read_text()


class TestMaterializeOmpHome:
    def test_writes_the_identity_surface_whole(self, tmp_path):
        home = tmp_path / "agentdir"
        identity = {"APPEND_SYSTEM.md": "ident\n", "RULES.md": "## Rule: a.md\n\nbody\n"}

        assert launcher._materialize_host_omp_home(home, identity=identity) is True

        assert (home / "APPEND_SYSTEM.md").read_text() == "ident\n"
        assert (home / "RULES.md").read_text() == "## Rule: a.md\n\nbody\n"

    def test_a_stack_with_no_identity_gets_no_files(self, tmp_path):
        home = tmp_path / "agentdir"
        launcher._materialize_host_omp_home(home, identity={})
        assert not (home / "APPEND_SYSTEM.md").exists()
        assert not (home / "RULES.md").exists()

    def test_dropped_rule_content_is_removed_on_a_rebuild(self, tmp_path):
        """Wholesale, like the claude path: a rule the stack no longer carries must not survive in
        the agent dir, or the model keeps reading an instruction nobody can find in the catalog."""
        home = tmp_path / "agentdir"
        launcher._materialize_host_omp_home(home, identity={"RULES.md": "old\n"})
        launcher._materialize_host_omp_home(home, identity={"APPEND_SYSTEM.md": "new\n"})
        assert not (home / "RULES.md").exists()
        assert (home / "APPEND_SYSTEM.md").read_text() == "new\n"

    def test_the_fingerprint_gate_skips_an_unchanged_stack(self, tmp_path):
        home = tmp_path / "agentdir"
        launcher._materialize_host_omp_home(home, identity={"RULES.md": "a\n"}, fingerprint="fp1")
        launcher._stamp_host_home(home, "fp1")

        assert launcher._materialize_host_omp_home(
            home, identity={"RULES.md": "b\n"}, fingerprint="fp1"
        ) is False
        assert (home / "RULES.md").read_text() == "a\n"
        assert launcher._materialize_host_omp_home(
            home, identity={"RULES.md": "b\n"}, fingerprint="fp2"
        ) is True
        assert (home / "RULES.md").read_text() == "b\n"

    def test_a_live_terminal_resume_pointer_survives_the_rebuild(self, tmp_path):
        """omp's twin of the claude daemon-state exception (bd harnessed-8px.20).

        `terminal-sessions/pts-N` is written by a RUNNING session — the cwd plus the session jsonl
        to resume, keyed by TTY. A rebuild that deletes it strips a live session of its resume path.
        """
        home = tmp_path / "agentdir"
        (home / "terminal-sessions").mkdir(parents=True)
        (home / "terminal-sessions" / "pts-0").write_text("/proj\n/sessions/x.jsonl\n")
        (home / "RULES.md").write_text("old\n")

        launcher._materialize_host_omp_home(home, identity={"RULES.md": "new\n"})

        assert (home / "terminal-sessions" / "pts-0").is_file()
        assert (home / "RULES.md").read_text() == "new\n"

    def test_refetchable_caches_are_still_wiped(self, tmp_path):
        """The keep-set is for live state, not for whatever is expensive to rebuild. `cache/` and
        `models.db` are refetchable, and the wholesale wipe is what stops a dropped recipe leaving
        content behind — widening it to "anything costly" is how that guarantee erodes."""
        home = tmp_path / "agentdir"
        (home / "cache").mkdir(parents=True)
        (home / "cache" / "conv.bin").write_text("x")
        (home / "models.db").write_text("cached models")

        launcher._materialize_host_omp_home(home, identity={})

        assert not (home / "cache").exists()
        assert not (home / "models.db").exists()

    def test_the_rebuild_unlinks_shared_state_instead_of_following_it(self, tmp_path, omp_real):
        """The agent dir is full of symlinks INTO the user's real one. A rebuild that followed them
        would delete the user's sessions and login database, not the stack's content."""
        home = tmp_path / "agentdir"
        (omp_real / "agent.db").write_text("real db")
        (omp_real / "sessions").mkdir()
        (omp_real / "sessions" / "s.json").write_text("session")
        launcher._materialize_host_omp_home(home, identity={"RULES.md": "a\n"})
        launcher._share_host_omp_state(home)

        launcher._materialize_host_omp_home(home, identity={"RULES.md": "b\n"})

        assert (omp_real / "agent.db").read_text() == "real db"
        assert (omp_real / "sessions" / "s.json").read_text() == "session"


class TestShareOmpState:
    def test_symlinks_the_shared_db_and_session_state(self, tmp_path, omp_real):
        (omp_real / "agent.db").write_text("db")
        (omp_real / "history.db").write_text("hist")
        home = tmp_path / "agentdir"
        home.mkdir()

        launcher._share_host_omp_state(home)

        # auth + usage ledger: REFERENCED, so one login and one ledger serve every stack.
        assert (home / "agent.db").is_symlink()
        assert (home / "agent.db").read_text() == "db"
        assert (home / "history.db").is_symlink()
        for name in ("sessions", "blobs", "memories"):
            assert (home / name).is_symlink(), name
            assert (home / name).resolve() == (omp_real / name).resolve()

    def test_config_and_identity_stay_per_stack(self, tmp_path, omp_real):
        """The whole point of the per-stack dir: what isolates must not be linked back.

        The user's dir must HOLD each of these first. `is_symlink()` is False for a path that does
        not exist, so against an empty `omp_real` every assertion below passes vacuously and the
        test would stay green even if the implementation started linking them.
        """
        isolated = ("config.yml", "settings.json", "RULES.md", "APPEND_SYSTEM.md", "mcp.json",
                    "models.db")
        for name in isolated:
            (omp_real / name).write_text("user's own\n")
        (omp_real / "managed-skills").mkdir()
        home = tmp_path / "agentdir"
        home.mkdir()

        launcher._share_host_omp_state(home)

        for name in (*isolated, "managed-skills"):
            assert not (home / name).is_symlink(), name
            assert not (home / name).exists(), name

    def test_first_run_without_a_host_login_is_a_note_not_a_dangling_link(self, tmp_path, omp_real):
        """Linking at a missing `agent.db` would have omp create its database THROUGH the link,
        writing a stack's login into the user's agent dir sideways. omp prompting a per-stack login
        on a first run is expected, not an error — mirrors `mounts._omp_agent_mount`."""
        home = tmp_path / "agentdir"
        home.mkdir()

        launcher._share_host_omp_state(home)

        assert not (home / "agent.db").exists()
        assert not (home / "agent.db").is_symlink()
        assert not (omp_real / "agent.db").exists()

    def test_nothing_is_written_into_the_real_agent_dir_except_the_shared_dirs(
        self, tmp_path, omp_real
    ):
        """#307 acceptance criterion 6. Everything the stack owns lands in its own dir; the only
        things that appear in the user's is the shared-state containers the symlinks need."""
        (omp_real / "agent.db").write_text("db")
        home = tmp_path / "agentdir"
        launcher._materialize_host_omp_home(
            home, identity={"RULES.md": "r\n", "APPEND_SYSTEM.md": "i\n"}
        )
        launcher._share_host_omp_state(home)

        assert sorted(p.name for p in omp_real.iterdir()) == [
            "agent.db", "blobs", "memories", "sessions"
        ]

    def test_a_second_run_repoints_an_existing_link(self, tmp_path, omp_real):
        (omp_real / "agent.db").write_text("db")
        home = tmp_path / "agentdir"
        home.mkdir()
        launcher._share_host_omp_state(home)
        launcher._share_host_omp_state(home)
        assert (home / "agent.db").read_text() == "db"

    def test_a_regular_file_left_by_an_earlier_run_is_replaced_by_the_link(self, tmp_path, omp_real):
        (omp_real / "agent.db").write_text("shared")
        home = tmp_path / "agentdir"
        home.mkdir()
        (home / "agent.db").write_text("stale per-stack")

        launcher._share_host_omp_state(home)

        assert (home / "agent.db").is_symlink()
        assert (home / "agent.db").read_text() == "shared"

    def test_launching_the_users_own_agent_dir_is_a_no_op(self, tmp_path, omp_real):
        """Guard against linking a directory at itself."""
        launcher._share_host_omp_state(omp_real)
        assert not (omp_real / "sessions").is_symlink()


class TestPropagateOmpConfig:
    def test_the_host_preferences_are_seeded_into_the_stack(self, tmp_path, omp_real):
        """A per-stack agent dir means a per-stack config.yml, and omp resolves config at exactly
        one level. Without this the stack runs on omp's shipped defaults — no model roles, no
        provider order — which is a factory reset, not isolation."""
        (omp_real / "config.yml").write_text("modelRoles:\n  default: anthropic/claude-opus-5\n")
        home = tmp_path / "agentdir"
        home.mkdir()

        launcher._propagate_host_omp_config(home)

        assert "anthropic/claude-opus-5" in (home / "config.yml").read_text()

    def test_host_keys_win_on_every_launch(self, tmp_path, omp_real):
        """The 8px.18 rule, in YAML: a preference the user changes in their own omp must reach the
        stack without waiting for something unrelated to change the fingerprint."""
        (omp_real / "config.yml").write_text("theme:\n  dark: new-theme\n")
        home = tmp_path / "agentdir"
        home.mkdir()
        (home / "config.yml").write_text("theme:\n  dark: stale-theme\n")

        launcher._propagate_host_omp_config(home)

        assert "new-theme" in (home / "config.yml").read_text()
        assert "stale-theme" not in (home / "config.yml").read_text()

    def test_keys_only_the_stack_has_survive(self, tmp_path, omp_real):
        """An `install:` script writing into `$PI_CODING_AGENT_DIR/config.yml` must not be silently
        undone the next launch — the same collision `_propagate_host_settings` resolves."""
        (omp_real / "config.yml").write_text("theme:\n  dark: t\n")
        home = tmp_path / "agentdir"
        home.mkdir()
        (home / "config.yml").write_text("theme:\n  dark: old\nextensions:\n  - stack-tool\n")

        launcher._propagate_host_omp_config(home)

        text = (home / "config.yml").read_text()
        assert "stack-tool" in text
        assert "dark: t" in text

    def test_no_host_config_is_a_clean_no_op(self, tmp_path, omp_real):
        home = tmp_path / "agentdir"
        home.mkdir()
        launcher._propagate_host_omp_config(home)
        assert not (home / "config.yml").exists()

    def test_invalid_yaml_falls_back_to_the_plain_copy(self, tmp_path, omp_real):
        """A config hand-edited into invalid YAML must not take the whole launch down."""
        (omp_real / "config.yml").write_text("theme:\n  dark: t\n")
        home = tmp_path / "agentdir"
        home.mkdir()
        (home / "config.yml").write_text("[not: valid: yaml\n")

        launcher._propagate_host_omp_config(home)

        assert (home / "config.yml").read_text() == "theme:\n  dark: t\n"


class TestOmpLaunchPlan:
    def test_plan_materializes_the_agent_dir_and_returns_omp_argv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "host-omp"))
        assemble(None, "hostspike", paths.profiles_root().parent, "omp", strict=True,
                 shared_identity=False)

        home, argv, cwd, rebuilt = launcher._host_launch_plan("hostspike", "omp", tmp_path)

        assert home == paths.host_home("hostspike", "omp")
        assert argv == ["omp"]
        assert cwd == tmp_path
        assert rebuilt is True
        assert "hostspike tracer agent" in (home / "APPEND_SYSTEM.md").read_text()
        # The claude content layer goes in the nested bridge surface, never loose in the agent dir
        # where omp would be reading files it has no format for.
        assert not (home / "skills").exists()
        assert not (home / "CLAUDE.md").exists()
        assert (hosthome._host_omp_claude_dir(home) / "settings.json").is_file()

    def test_assembly_can_skip_the_shared_block_write(self, monkeypatch, tmp_path):
        """#307 acceptance criterion 6. `assemble` is the ONE emit step that writes outside the
        profile; on the host path its output would land where nothing reads."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        shared = tmp_path / "host-omp"
        shared.mkdir()
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(shared))
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        assemble(None, "hostspike", paths.profiles_root().parent, "omp", strict=True,
                 shared_identity=False)

        assert not (shared / "APPEND_SYSTEM.md").exists()
        assert not (tmp_path / "fakehome" / ".omp").exists()

    def test_two_stacks_get_distinct_identity_but_one_login(self, monkeypatch, tmp_path):
        """#307 acceptance criterion 7."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        real = tmp_path / "host-omp"
        real.mkdir()
        (real / "agent.db").write_text("one login")
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
        a, b = paths.host_home("sa", "omp"), paths.host_home("sb", "omp")

        for home, ident in ((a, "stack A\n"), (b, "stack B\n")):
            launcher._materialize_host_omp_home(home, identity={"APPEND_SYSTEM.md": ident})
            launcher._share_host_omp_state(home)

        assert (a / "APPEND_SYSTEM.md").read_text() != (b / "APPEND_SYSTEM.md").read_text()
        assert (a / "agent.db").resolve() == (b / "agent.db").resolve()


class TestOmpHostCliRouting:
    def test_host_run_omp_execs_omp_with_the_agent_dir_env(self, monkeypatch, tmp_path):
        """#307 acceptance criterion 1 + 2: no `_HOST_HARNESS` error, and the agent dir omp is
        pointed at is the per-stack one, never the user's own `~/.omp/agent`."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        real = tmp_path / "host-omp"
        real.mkdir()
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(file=file, argv=argv, agent_dir=env.get("PI_CODING_AGENT_DIR"))
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "omp", str(tmp_path), "--stack", "hostspike"]
        )

        assert result.exit_code == 0, result.output
        assert captured["file"] == "omp"
        assert captured["argv"] == ["omp"]  # no --mcp-config: omp reads mcp.json from the agent dir
        home = paths.host_home("hostspike", "omp")
        assert captured["agent_dir"] == str(home)
        assert captured["agent_dir"] != str(real)
        # MCP is wired through the agent dir's own file, isolated to this stack.
        assert json.loads((home / "mcp.json").read_text()) == {"mcpServers": {}}

    def test_no_strict_mcp_config_says_it_does_nothing_for_omp(self, monkeypatch, tmp_path):
        """`host-run` accepts the flag for any harness and records it in `lastrun`, but omp has no
        strict/non-strict mode — it reads its agent dir's mcp.json and nothing else. Accepted and
        silently inert is the case this codebase names rather than tolerates."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        real = tmp_path / "host-omp"
        real.mkdir()
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app,
            ["host-run", "omp", str(tmp_path), "--stack", "hostspike", "--no-strict-mcp-config"],
        )

        assert result.exit_code == 0, result.output
        assert "no effect for omp" in result.output

    def test_the_note_is_absent_when_the_flag_is_not_passed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        real = tmp_path / "host-omp"
        real.mkdir()
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "omp", str(tmp_path), "--stack", "hostspike"]
        )

        assert "no effect for omp" not in result.output

    def test_an_unsupported_host_harness_still_names_what_is_supported(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        r = runner.invoke(launcher.app, ["host-run", "codex", str(tmp_path), "--stack", "hostspike"])
        assert r.exit_code == 1
        assert "claude" in r.output and "omp" in r.output

    def test_an_install_runs_pinned_at_the_stacks_agent_dir(self, tmp_path):
        """bd harnessed-8px.26, omp's half: inherited, `PI_CODING_AGENT_DIR` would redirect an
        install into the PARENT stack's dir; unset, into the user's own — the exact leak the
        per-stack dir exists to end (#307 finding 6).

        A claude-shaped installer honouring `CLAUDE_CONFIG_DIR` must land in the BRIDGE surface,
        not loose in the agent dir and never in the user's real `~/.claude`."""
        home = tmp_path / "agentdir"
        assert hostrun._harness_config_env("omp", home) == {
            "PI_CODING_AGENT_DIR": str(home),
            "CLAUDE_CONFIG_DIR": str(hosthome._host_omp_claude_dir(home)),
        }

    def test_the_claude_path_still_pins_only_its_own_var(self, tmp_path):
        home = tmp_path / "claudehome"
        assert hostrun._harness_config_env("claude", home) == {"CLAUDE_CONFIG_DIR": str(home)}


class TestOmpHooksBridgeSurface:
    """The claude-hooks bridge reads hooks from `$CLAUDE_CONFIG_DIR/settings.json`
    (`index.ts:100`, merged with the project's `.claude/settings.json`), and it is a USER-installed
    omp plugin — present on a host that installed it, absent otherwise.

    Leaving `CLAUDE_CONFIG_DIR` unset is therefore NOT the neutral choice it looks like: the bridge
    falls back to the real `~/.claude` and fires the user's GLOBAL hooks inside a stack session
    while the stack's own never run. That inverts the one thing this backend isolates.
    """

    def test_the_bridge_surface_is_nested_not_a_sibling(self, tmp_path):
        """`host-gc` reads every dir at the `<stack>/<harness>` level as a config dir, so a sibling
        would surface as a phantom harness. A child is one dir to the same eyes."""
        home = paths.host_home("s", "omp")
        assert hosthome._host_omp_claude_dir(home).parent == home

    def test_it_is_not_the_claude_host_home(self, monkeypatch, tmp_path):
        """That dir is a real claude session's, with claude's credential and session-state symlinks
        in it. Sharing one would put omp's launches inside claude's auth wiring for nothing."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        omp_home = paths.host_home("s", "omp")
        assert hosthome._host_omp_claude_dir(omp_home) != paths.host_home("s", "claude")

    def test_the_launch_points_claude_config_dir_at_the_stack(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "REAL-user-claude"))
        real = tmp_path / "host-omp"
        real.mkdir()
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(real))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(ccd=env.get("CLAUDE_CONFIG_DIR"))
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["host-run", "omp", str(tmp_path), "--stack", "hostspike"]
        )

        assert result.exit_code == 0, result.output
        home = paths.host_home("hostspike", "omp")
        assert captured["ccd"] == str(hosthome._host_omp_claude_dir(home))
        # The user's own claude config must NOT be what the bridge reads inside a stack session.
        assert captured["ccd"] != str(tmp_path / "REAL-user-claude")

    def test_the_stacks_hooks_land_where_the_bridge_reads_them(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "host-omp"))
        prof = paths.profile_dir("hostspike", "omp")
        prof.mkdir(parents=True)
        _fake_profile(prof)

        home, _argv, _cwd, _rebuilt = launcher._host_launch_plan("hostspike", "omp", tmp_path)

        bridge = hosthome._host_omp_claude_dir(home)
        assert json.loads((bridge / "settings.json").read_text())["permissions"]["defaultMode"] == (
            "acceptEdits"
        )
        # Container-only artifacts stay out of it, exactly as on the claude path.
        assert not (bridge / ".mcp.json").exists()

    def test_settings_reach_the_bridge_even_when_the_stack_is_unchanged(self, monkeypatch, tmp_path):
        """bd harnessed-8px.18 applies here too, and here settings.json is the ONLY file that
        matters: the bridge reads hooks from it and nothing else."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "host-omp"))
        prof = paths.profile_dir("hostspike", "omp")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        home = paths.host_home("hostspike", "omp")
        launcher._materialize_host_omp_home(home, identity={}, fingerprint="fp")
        launcher._stamp_host_home(home, "fp")
        (prof / "settings.json").write_text('{"hooks":{"SessionStart":[]}}')

        launcher._plan_host_omp("hostspike", prof, home, fingerprint="fp")  # gate: "unchanged"

        bridge = hosthome._host_omp_claude_dir(home)
        assert "SessionStart" in (bridge / "settings.json").read_text()

