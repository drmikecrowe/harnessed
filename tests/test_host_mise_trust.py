"""mise trust survives a host launch, and the suite writes no state into the developer's home.

Two regressions found together while debugging why every `--last` aoe row was failing. They are
independent, and both are about a directory harnessed redirects that it should not have.
"""
from __future__ import annotations

import json
import os

from pathlib import Path

import pytest

# `differing_executors` is suppressed on the properties below: mutmut re-runs one test method across
# several executors, which trips the check without saying anything about the property. It guards
# reproducibility of hypothesis's own replay database, not any assertion here.
from hypothesis import HealthCheck, given, settings, strategies as st

from harnessed import hostrun, paths


def _write_user_mise_config(body: str) -> Path:
    """Write the config the user's own mise would read — $XDG_CONFIG_HOME is isolated per test."""
    cfg = paths.xdg_config_home() / "mise" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _trusted(env: dict[str, str]) -> str | None:
    return env.get("MISE_TRUSTED_CONFIG_PATHS")


_PATH_CHARS = st.characters(min_codepoint=32, max_codepoint=126, exclude_characters=':"\\')


def _toml_trusted_config_paths(paths_: list[str]) -> str:
    """Serialise `paths_` as a TOML `trusted_config_paths` array.

    `json.dumps` and not `repr`, because Python's `repr` emits `\\x08` and TOML has no `\\x` escape.

    SCOPE, stated because it bounds what the properties below prove. `_PATH_CHARS` keeps the
    generator inside printable ASCII, so this stays a two-line serialiser instead of a hand-rolled
    TOML writer. Hypothesis walked me through three separate escaping rules — `\\x08`, an astral
    character as a surrogate pair, then a raw DEL — each of which produced an UNPARSEABLE config
    that the property then blamed on the merge. The subject here is the merge, not TOML escaping,
    and `tomllib` is read-only so the stdlib offers no writer to defer to. Exotic-codepoint configs
    are therefore covered by `test_malformed_toml_fails_closed`, which asserts the behaviour that
    actually matters for them: harnessed grants nothing and the launch survives.
    """
    return "[settings]\ntrusted_config_paths = [" + ", ".join(
        json.dumps(p, ensure_ascii=False) for p in paths_
    ) + "]\n"


class TestHostLaunchKeepsTheUsersMiseTrustStore:
    """mise keeps `trusted-configs` in MISE_STATE_DIR, so redirecting that dir per stack throws the
    user's trust away.

    The symptom is not obviously about trust. mise reports an untrusted config as

        mise ERROR error parsing config file: <path>

    with the actual reason on the following line, so it reads as a TOML syntax error in a file that
    parses fine — and the config is then not loaded, which silently drops whatever `[env]` it
    carried. Verified against mise 2026.8.2.
    """

    def test_the_state_dir_is_not_redirected(self):
        assert "MISE_STATE_DIR" not in hostrun._host_mise_env("s"), (
            "MISE_STATE_DIR holds mise's trust store. Redirecting it per stack gives every stack an "
            "empty one, so every project mise.toml the user already trusted reads as untrusted "
            "inside every harnessed session — and each new stack re-breaks the one they just fixed."
        )

    def test_the_data_and_config_dirs_are_still_redirected(self):
        # The isolation that MUST survive the fix: shims resolve against the data dir, and the
        # stack's own tool list lives in the config dir. Dropping either is a different bug.
        env = hostrun._host_mise_env("s")
        assert set(env) == {"MISE_DATA_DIR", "MISE_CONFIG_DIR"}

    def test_a_state_dir_inherited_from_another_stack_is_actively_removed(self):
        """Not setting it is not enough — a previous release DID set it.

        Launching a stack from inside another stack's host session is routine, and both consumers
        merge this over an inherited environment. Left in place, the outer session's redirect keeps
        the empty trust store alive in the inner one and the bug survives the release that fixed it.

        The value is the OUTER stack's, which this process cannot name — so the removal has to
        recognise the shape, not a known stack.
        """
        outer = paths.xdg_data_home() / "harnessed" / "tools" / "some-other-stack" / "mise" / "state"
        env = {"MISE_STATE_DIR": str(outer), "PATH": "/usr/bin"}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_STATE_DIR" not in env
        assert env["PATH"] == "/usr/bin", "unrelated variables must be left alone"
        assert env["MISE_DATA_DIR"] == hostrun._host_mise_env("s")["MISE_DATA_DIR"]

    def test_a_state_dir_the_user_set_themselves_is_left_alone(self):
        """The removal must not reach past what harnessed itself wrote.

        MISE_STATE_DIR is an ordinary mise variable. Dropping a user's own value puts them on
        mise's DEFAULT state dir — a different trust store than the one they picked, which is this
        module's own bug pointed at a different victim.
        """
        env = {"MISE_STATE_DIR": "/srv/shared/mise-state"}
        hostrun._apply_host_mise_env(env, "s")
        assert env["MISE_STATE_DIR"] == "/srv/shared/mise-state"

    def test_a_harnessed_looking_path_that_is_not_a_state_dir_is_left_alone(self):
        # The tools root itself, and a stack dir without the mise/state tail, are not values we
        # ever wrote — matching them would be the same over-reach with a narrower blast radius.
        for value in (
            str(paths.xdg_data_home() / "harnessed" / "tools"),
            str(paths.xdg_data_home() / "harnessed" / "tools" / "s"),
            str(paths.xdg_data_home() / "harnessed" / "tools" / "s" / "mise"),
        ):
            env = {"MISE_STATE_DIR": value}
            hostrun._apply_host_mise_env(env, "s")
            assert env["MISE_STATE_DIR"] == value, f"{value} is not a state dir harnessed wrote"


class TestHostLaunchCarriesTheUsersOwnTrustedConfigPaths:
    """bd harnessed-67u. Redirecting MISE_CONFIG_DIR hides the user's global mise config, so every
    SETTING in it is discarded along with the tool list the redirect exists to isolate.

    `trusted_config_paths` is the setting that matters, because it is the only mechanism that
    survives a NEW git worktree: the trust STORE is keyed per config file and does not cascade from
    an ancestor, while `trusted_config_paths` is a path-PREFIX rule. A user who fixes worktree trust
    the only way that works has that fix silently dropped inside every harnessed host session.

    Propagating it is not harnessed GRANTING trust — the thing `_host_mise_env` is careful never to
    do. It is harnessed declining to discard a decision the user already made.
    """

    def test_a_user_setting_is_propagated(self):
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/repo"]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/w/repo"

    def test_several_paths_join_with_a_colon_in_order(self):
        """Colon is the delimiter mise accepts; a comma is not split and reads as one bogus path."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/a", "/w/b"]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/w/a:/w/b"

    def test_an_inherited_value_is_preserved_and_leads(self):
        """A value already in the environment is the user's too, and must not be overwritten."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/repo"]\n')
        env = {"MISE_TRUSTED_CONFIG_PATHS": "/pre"}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/pre:/w/repo"

    def test_applying_twice_does_not_duplicate_entries(self):
        """Launching a stack from inside another stack's host session is routine, so the merge has
        to be idempotent or the variable grows one copy per nesting level."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/a", "/w/b"]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        once = _trusted(env)
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == once

    def test_no_user_setting_sets_no_variable(self):
        """Not set, rather than set to empty: an empty value is a value, and mise would read it."""
        _write_user_mise_config("[settings]\nexperimental = true\n")
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_TRUSTED_CONFIG_PATHS" not in env

    def test_a_missing_config_file_is_silent(self):
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_TRUSTED_CONFIG_PATHS" not in env

    def test_malformed_toml_fails_closed(self):
        """A config harnessed cannot parse grants nothing, and never aborts the launch."""
        _write_user_mise_config("[settings\ntrusted_config_paths = [")
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_TRUSTED_CONFIG_PATHS" not in env
        assert env["MISE_DATA_DIR"], "the launch env must still be built"

    def test_a_non_list_setting_fails_closed(self):
        _write_user_mise_config('[settings]\ntrusted_config_paths = "/w/repo"\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_TRUSTED_CONFIG_PATHS" not in env

    def test_non_string_entries_are_dropped(self):
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/a", 7, true]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/w/a"

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads a 0000 file regardless of its mode")
    def test_an_unreadable_file_is_silent(self):
        cfg = _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/repo"]\n')
        cfg.chmod(0o000)
        try:
            env: dict[str, str] = {}
            hostrun._apply_host_mise_env(env, "s")
            assert "MISE_TRUSTED_CONFIG_PATHS" not in env
        finally:
            cfg.chmod(0o600)

    def test_a_path_containing_the_delimiter_is_dropped(self):
        """Colon separates entries, so such a path cannot be represented. Emitting it would grant
        trust to two paths the user never wrote — the exact over-grant this design forbids."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/a", "/w/od:d"]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/w/a"

    def test_an_inherited_stack_config_dir_is_not_treated_as_the_users(self):
        """The MISE_STATE_DIR inheritance trap, one variable over. An inner launch that read the
        inherited MISE_CONFIG_DIR naively would take the OUTER STACK's config as "the user's" and
        propagate stack-level trust as though the user had chosen it."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/from/user"]\n')
        outer = paths.xdg_data_home() / "harnessed" / "tools" / "other-stack" / "mise" / "config"
        outer.mkdir(parents=True, exist_ok=True)
        (outer / "config.toml").write_text(
            '[settings]\ntrusted_config_paths = ["/from/stack"]\n', encoding="utf-8"
        )
        env = {"MISE_CONFIG_DIR": str(outer)}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/from/user"

    def test_a_user_chosen_config_dir_is_honoured(self, tmp_path):
        """Same narrowness rule as the state dir: only values harnessed itself wrote are ignored."""
        chosen = tmp_path / "my-mise"
        chosen.mkdir()
        (chosen / "config.toml").write_text(
            '[settings]\ntrusted_config_paths = ["/from/chosen"]\n', encoding="utf-8"
        )
        env = {"MISE_CONFIG_DIR": str(chosen)}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/from/chosen"

    def test_the_config_is_resolved_from_the_env_it_was_handed(self, tmp_path, monkeypatch):
        """The whole function takes an `env` mapping, so it must READ that mapping — resolving
        XDG_CONFIG_HOME from the process instead means the env being built and the config being
        consulted can disagree. Found by the real-execution check, which handed the constructed env
        to a live mise and got the wrong user's config back.
        """
        handed = tmp_path / "handed"
        (handed / "mise").mkdir(parents=True)
        (handed / "mise" / "config.toml").write_text(
            '[settings]\ntrusted_config_paths = ["/from/handed"]\n', encoding="utf-8"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "process"))
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/from/process"]\n')

        env = {"XDG_CONFIG_HOME": str(handed)}
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == "/from/handed"

    def test_no_path_is_invented_by_harnessed(self):
        """Every entry traces to the user's config or the inherited env. Nothing else qualifies —
        not the stack dir, not the tools root, not a repo or project path."""
        _write_user_mise_config('[settings]\ntrusted_config_paths = ["/w/repo"]\n')
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert (_trusted(env) or "").split(":") == ["/w/repo"]

    def test_the_users_config_is_never_written(self, monkeypatch):
        """harnessed reads this file and never writes it, and grants trust via no subprocess."""
        body = '[settings]\ntrusted_config_paths = ["/w/repo"]\n'
        cfg = _write_user_mise_config(body)
        before = cfg.stat().st_mtime_ns

        def _no_subprocess(*a, **k):
            raise AssertionError(
                f"a host launch must run no subprocess to grant trust: {a!r} {k!r}"
            )

        monkeypatch.setattr(hostrun.subprocess, "run", _no_subprocess)
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        assert cfg.read_text(encoding="utf-8") == body
        assert cfg.stat().st_mtime_ns == before


class TestTheTrustedPathMergeHoldsForAnyUserConfig:
    """Invariants over inputs nobody enumerated, for the merge `_apply_host_mise_env` performs.

    The scenario tests pin specific strings; these pin the PROPERTIES those strings stand for, so a
    rewrite of the merge that happens to satisfy the examples still has to satisfy the rule.
    """

    @settings(suppress_health_check=[HealthCheck.differing_executors])
    @given(st.lists(st.text(alphabet=_PATH_CHARS, min_size=1), max_size=6))
    def test_every_emitted_path_came_from_the_user(self, wanted):
        """harnessed invents nothing: the emitted set is a subset of what the user's config held."""
        _write_user_mise_config(_toml_trusted_config_paths(wanted))
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        emitted = [p for p in (_trusted(env) or "").split(":") if p]
        assert set(emitted) <= set(wanted)

    @settings(suppress_health_check=[HealthCheck.differing_executors])
    @given(st.lists(st.text(alphabet=_PATH_CHARS, min_size=1), max_size=6))
    def test_the_merge_is_idempotent_and_order_preserving(self, wanted):
        """Nested host launches re-apply this. Twice must equal once, and first-seen order stands."""
        _write_user_mise_config(_toml_trusted_config_paths(wanted))
        env: dict[str, str] = {}
        hostrun._apply_host_mise_env(env, "s")
        once = _trusted(env)
        hostrun._apply_host_mise_env(env, "s")
        assert _trusted(env) == once
        emitted = [p for p in (once or "").split(":") if p]
        assert emitted == list(dict.fromkeys(wanted)), "deduped, in the user's own order"


class TestTheSuiteWritesNoStateIntoTheDevelopersHome:
    """`conftest._isolated_user_state` is autouse, and this is what it is for.

    Everything durable harnessed records — `lastrun` replay records, project-env dotenvs holding
    live service passwords, per-instance dirs, `svc-secrets` — is keyed off `paths.xdg_state_home()`.
    Unset, that is the developer's real `~/.local/state`, and the launcher tests reach all of it.
    """

    def test_the_state_root_is_not_the_real_one(self):
        assert paths.xdg_state_home() != Path.home() / ".local" / "state", (
            "XDG_STATE_HOME is not isolated, so this test run is writing lastrun records and "
            "project-env dotenvs into the developer's own harnessed state"
        )

    def test_writing_a_lastrun_record_stays_inside_the_tmp_root(self, tmp_path):
        from harnessed import lastrun

        lastrun.record("host-run", "s", "claude", tmp_path)
        written = list((paths.xdg_state_home() / "harnessed" / "last-run").glob("*.json"))
        assert written, "the record went somewhere other than $XDG_STATE_HOME"
        assert all(str(p).startswith(os.environ["XDG_STATE_HOME"]) for p in written)
