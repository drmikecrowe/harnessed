"""Regression sentinels for issue #432: suite isolation from CLAUDE_CODE_OAUTH_TOKEN and HOME.

These tests assert the environmental invariants that conftest.py must enforce. They fail on the
current code (before the fix) when run on a developer machine with CLAUDE_CODE_OAUTH_TOKEN set
or when run in suite order after test_claude_container_auth.py has fired varlock.

The tests are intentionally simple: they ask about the environment, not about production code.
Both behaviors are conftest.py's responsibility; both must hold for every test in the suite.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import _REAL_HOME, _REAL_XDG_CONFIG_HOME


class TestSuiteIsolation:
    def test_oauth_token_absent_from_ambient_env(self) -> None:
        """CLAUDE_CODE_OAUTH_TOKEN must not be set in os.environ when no test fixture put it there.

        A developer shell that exports this variable — or a preceding test (test_claude_container_auth)
        that causes varlock to write it into os.environ — will cause TestShareClaudeState tests to
        fail in a suite-order-dependent way. conftest.py pops it at module level (same class as
        FORCE_COLOR) to ensure parity with CI regardless of what the developer's shell exports or
        what earlier tests left behind.

        If this test fails: conftest.py does not yet pop CLAUDE_CODE_OAUTH_TOKEN at module level.
        Fix: add os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None) after the FORCE_COLOR pop in
        tests/conftest.py.
        """
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ, (
            "CLAUDE_CODE_OAUTH_TOKEN is set in the ambient environment. "
            "This causes order-dependent failures in TestShareClaudeState when "
            "test_claude_container_auth.py runs first and varlock writes the token into os.environ. "
            "Expected: conftest.py pops it at module level before any test runs."
        )

    def test_home_is_isolated_from_real_developer_home(self) -> None:
        """Path.home() must not point to the real developer home during a unit run.

        The real ~/.config/harnessed/.env.schema declares CLAUDE_CODE_OAUTH_TOKEN. When HOME is
        the real developer home, production code (via varlock) reads the real schema and resolves
        the token from 1Password, writing it into os.environ. This causes suite-order-dependent
        failures and makes unit runs touch live credentials — a credential-leak risk on a public repo.

        If this test fails: conftest.py does not yet have a session-scoped autouse _isolated_home
        fixture. Fix: add such a fixture that redirects HOME to a tmp directory for the session.
        """
        current_home = Path.home()
        assert current_home != _REAL_HOME, (
            f"HOME is not isolated — Path.home() still returns the real developer home "
            f"({_REAL_HOME}). Tests can reach real ~/.claude and ~/.config/harnessed. "
            f"Expected: conftest.py session-scoped autouse fixture redirects HOME to a tmp dir."
        )

    def test_isolated_home_contains_no_harnessed_schema(self) -> None:
        """The isolated home must not contain the real .env.schema that would trigger varlock.

        This is the specific path that causes varlock to fire: ~/.config/harnessed/.env.schema.
        If HOME is isolated but the fixture copied the schema there, isolation would be incomplete.

        This test is weaker than test_home_is_isolated_from_real_developer_home — it validates
        the consequence rather than the mechanism — but it names the specific file that matters.
        """
        schema = Path.home() / ".config" / "harnessed" / ".env.schema"
        assert not schema.exists(), (
            f"The real .env.schema is accessible at {schema} during a unit run. "
            f"This allows varlock to resolve CLAUDE_CODE_OAUTH_TOKEN from 1Password "
            f"inside a unit test. Expected: HOME isolation makes this path unreachable."
        )

    def test_isolated_home_contains_no_dot_claude(self) -> None:
        """The isolated home must not expose real ~/.claude — the secondary defect (issue #432).

        _host_claude_source() falls back to Path.home() / ".claude" when CLAUDE_CONFIG_DIR is
        not set. If HOME is the real developer home, a failing assertion can print real
        .credentials.json fields (refreshTokenExpiresAt, subscriptionType) into pytest output
        and public CI logs.

        If this test fails: HOME is not isolated, and real credentials are potentially accessible.
        """
        dot_claude = Path.home() / ".claude"
        # We only check for .credentials.json specifically — the actual leak vector.
        credentials = dot_claude / ".credentials.json"
        assert not credentials.exists(), (
            f"Real ~/.claude/.credentials.json is accessible at {credentials} during a unit run. "
            f"A failing assertion in a test that calls _share_host_claude_state without setting "
            f"CLAUDE_CONFIG_DIR can print real credential fields into pytest output / CI logs. "
            f"Expected: HOME isolation makes this path unreachable."
        )


    def test_podman_config_guards_still_execute_under_home_isolation(self) -> None:
        """HOME isolation must not silently stop `TestPodmanConfigIsReachable` from running.

        Those two tests pin the podman-config exposure that `_isolated_user_catalog` provides, and
        both decide whether to run by looking for the real containers config. Compute that path from
        `Path.home()` and HOME isolation empties it, so they skip on every machine — a test that
        quietly stops running while the suite stays green, which is the same failure class #432
        itself reports. Measured during the spike: skips rose 45 -> 47.

        Asserted by running them, not by reading their source: what matters is that they EXECUTE
        under an isolated HOME, and any guard that gets that right passes this whichever way it is
        spelled.
        """
        if not (_REAL_XDG_CONFIG_HOME / "containers").is_dir():
            pytest.skip("no containers config on this machine — the guards have nothing to find")

        target = "tests/test_conftest_container_config.py::TestPodmanConfigIsReachable"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", target],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        assert "skipped" not in proc.stdout, (
            f"{target} skipped under an isolated HOME on a machine that HAS the real containers "
            f"config. Its skip guard is resolving from the isolated home instead of "
            f"_REAL_XDG_CONFIG_HOME, so it now skips everywhere.\n{proc.stdout[-2000:]}"
        )
        assert proc.returncode == 0, proc.stdout[-2000:]
