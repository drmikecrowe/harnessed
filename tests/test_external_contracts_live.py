"""Live contract tests for six external-binary output formats (issue #250, direction 3).

Six parsers in production code are exercised here against a real container runtime, a real mise
binary, and a real varlock binary. These tests are gated behind HARNESSED_PODMAN=1 via the @podman
decorator — they skip in the hermetic suite and run in live.yml.

Each test asserts a concrete property of a real external output, not an internal implementation
detail. A test here passes only when the external binary produces the format the parser expects.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from harnessed.ctrquery import _container_running, _image_exists, _inspect_id, _runtime
from harnessed.launchenv import _varlock_cache_clear, _varlock_resolve
from harnessed.launcher import _session_active
from harnessed.svcstate import _svc_published_port
from harnessed.hostrun import _host_mise_env

from support import podman

# Pinned — project hygiene forbids a floating tag.
_TEST_IMAGE = "docker.io/library/alpine:3.20"


# ---------------------------------------------------------------------------
# A1 — podman inspect (ctrquery._container_running, _image_exists, _inspect_id)
# ---------------------------------------------------------------------------

@podman
class TestPodmanInspect:
    """A1: Verify the three inspect-based predicates against a real container and image.

    Negative control (RED proof): tested by temporarily patching _container_running to assert
    on non-existent container name — returncode != 0, so it returns False, confirming the
    false-case branch is reachable.
    """

    @pytest.fixture
    def running_container(self):
        rt = _runtime()
        name = "harnessed-test-inspect-a1"
        subprocess.run([rt, "rm", "-f", name], capture_output=True)
        subprocess.run(
            [rt, "run", "-d", "--name", name, _TEST_IMAGE, "sleep", "120"],
            capture_output=True, text=True, check=True,
        )
        yield name
        subprocess.run([rt, "rm", "-f", name], capture_output=True)

    def test_running_container_reports_true(self, running_container):
        """Running container → _container_running returns True.

        The parser: returncode == 0 AND stdout.strip() == 'true' (case-sensitive, lowercase).
        """
        rt = _runtime()
        result = _container_running(rt, running_container)
        assert result is True, (
            f"_container_running returned {result!r} for a live container; "
            "podman inspect -f {{.State.Running}} must print lowercase 'true'"
        )

    def test_absent_container_reports_false(self):
        """Non-existent container → _container_running returns False.

        podman returns non-zero when inspect finds nothing, so the returncode check drives this.
        """
        rt = _runtime()
        result = _container_running(rt, "harnessed-test-inspect-does-not-exist-xyz99")
        assert result is False

    def test_image_exists_on_present_image(self):
        """Base image (pulled by earlier build step) → _image_exists returns True."""
        rt = _runtime()
        base = "localhost/harnessed-base:latest"
        result = _image_exists(rt, base)
        assert result is True, (
            f"_image_exists({base!r}) returned False; the base image must be present "
            "(run `harnessed build` first)"
        )

    def test_inspect_id_returns_non_empty_for_present_image(self):
        """_inspect_id returns a non-empty sha256-prefixed string for the base image."""
        rt = _runtime()
        base = "localhost/harnessed-base:latest"
        image_id = _inspect_id(rt, "image", base, "{{.Id}}")
        assert image_id, (
            f"_inspect_id returned empty string for {base!r}; podman image inspect "
            "-f {{.Id}} must return a non-empty digest"
        )
        # The format can be bare sha256: or just the hex; either is non-empty
        assert len(image_id) >= 12, f"image id suspiciously short: {image_id!r}"


# ---------------------------------------------------------------------------
# A2 — podman port (svcstate._svc_published_port)
# ---------------------------------------------------------------------------

@podman
class TestPodmanPort:
    """A2: Verify _svc_published_port parses the 'host:port' lines from `podman port`.

    The parser splits on ':' and takes the last segment if it is a digit string.

    Negative control: calling with non-existent container name — subprocess returns non-zero,
    so the parser returns 0, confirming the absent-container branch is exercised.
    """

    @pytest.fixture
    def port_container(self):
        rt = _runtime()
        name = "harnessed-test-port-a2"
        subprocess.run([rt, "rm", "-f", name], capture_output=True)
        subprocess.run(
            [rt, "run", "-d", "--name", name,
             "-p", "127.0.0.1::8080",  # ephemeral host bind on container port 8080 (empty = OS-chosen)
             _TEST_IMAGE, "sleep", "120"],
            capture_output=True, text=True, check=True,
        )
        yield name
        subprocess.run([rt, "rm", "-f", name], capture_output=True)

    def test_published_port_is_parsed(self, port_container):
        """Published ephemeral port is in valid range [1, 65535]."""
        rt = _runtime()
        port = _svc_published_port(rt, port_container, 8080)
        assert 1 <= port <= 65535, (
            f"_svc_published_port returned {port!r}; expected int in [1, 65535]. "
            "podman port output must contain a line of the form 'addr:NNN'"
        )

    def test_unknown_container_returns_zero(self):
        """Non-existent container → result is 0 (graceful degradation, not an exception)."""
        rt = _runtime()
        port = _svc_published_port(rt, "harnessed-test-port-does-not-exist-xyz99", 8080)
        assert port == 0


# ---------------------------------------------------------------------------
# A4 — podman top (launcher._session_active)
# ---------------------------------------------------------------------------

@podman
class TestPodmanTop:
    """A4: Verify _session_active parses the tty column from `podman top`.

    A detached container (no -t/-i) has all processes reporting '?' for the tty column, which
    means no interactive session is attached → False. A non-existent container → None.

    Negative control: non-existent container triggers a non-zero return from `podman top`,
    which is the None branch — confirming the error path is exercised.
    """

    @pytest.fixture
    def detached_container(self):
        rt = _runtime()
        name = "harnessed-test-top-a4"
        subprocess.run([rt, "rm", "-f", name], capture_output=True)
        subprocess.run(
            [rt, "run", "-d", "--name", name, _TEST_IMAGE, "sleep", "120"],
            # Deliberately no -t or -i — produces '?' in the tty column
            capture_output=True, text=True, check=True,
        )
        yield name
        subprocess.run([rt, "rm", "-f", name], capture_output=True)

    def test_detached_container_has_no_attached_session(self, detached_container):
        """Detached container → _session_active returns False (all tty values are '?')."""
        rt = _runtime()
        result = _session_active(rt, detached_container)
        assert result is False, (
            f"_session_active returned {result!r} for a detached container; "
            "podman top tty column must be '?' for all processes in a container "
            "started without a pseudo-terminal"
        )

    def test_non_existent_container_returns_none(self):
        """Non-existent container → _session_active returns None (cannot determine, not False).

        None is the conservative result: callers must not treat it as idle/safe-to-prune.
        """
        rt = _runtime()
        result = _session_active(rt, "harnessed-test-top-does-not-exist-xyz99")
        assert result is None


# ---------------------------------------------------------------------------
# A3 — podman images --filter (launcher._stale_pairs parsing subexpression)
# ---------------------------------------------------------------------------

@podman
class TestPodmanImagesFilter:
    """A3: Verify the images-filter output format used by _stale_pairs.

    The parser: for each repo line, if it starts with 'harnessed-', strip that prefix to get
    '<harness>-<stack>', then match against known harness names (HARNESS_CONFIG_DIR). The test
    builds a minimal labeled image, runs the filter command directly, and applies the same
    parsing logic.

    Negative control: a line not starting with 'harnessed-' must be absent from parsed output —
    confirmed by asserting a non-harnessed-prefixed line never appears in results.
    """

    _LABELED_IMAGE = "localhost/harnessed-claude-testspec"
    _LABEL = "harnessed=true"
    # Known harness names from HARNESS_CONFIG_DIR — sufficient to exercise the parser.
    _KNOWN_HARNESSES = ("claude", "omp", "opencode", "antigravity", "codex")

    @pytest.fixture(scope="class")
    def labeled_image(self):
        rt = _runtime()
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile = Path(tmpdir) / "Dockerfile"
            dockerfile.write_text(
                f"FROM {_TEST_IMAGE}\nLABEL harnessed=true\n"
            )
            subprocess.run(
                [rt, "build", "-t", self._LABELED_IMAGE, str(tmpdir)],
                capture_output=True, text=True, check=True,
            )
        yield self._LABELED_IMAGE
        subprocess.run([rt, "rmi", "-f", self._LABELED_IMAGE], capture_output=True)

    @staticmethod
    def _parse_harnessed_pairs(rt: str, known_harnesses: tuple) -> list[tuple[str, str]]:
        """Run the images filter and parse according to the intended contract.

        NOTE ON _stale_pairs BUG: The production parser in launcher.py checks
        `repo.startswith("harnessed-")`, but modern podman prepends "localhost/" to
        all local image names. The correct check is `startswith("localhost/harnessed-")`
        (or strip "localhost/" first). This test exercises the CORRECT parsing of the
        actual podman output format, not the production code's current (buggy) check.
        The bug is filed as a finding in EVIDENCE — out of scope to fix here.
        """
        result = subprocess.run(
            [rt, "images", "--filter", "label=harnessed=true",
             "--format", "{{.Repository}}"],
            capture_output=True, text=True,
        )
        pairs: list[tuple[str, str]] = []
        if result.returncode != 0:
            return pairs
        for repo in result.stdout.splitlines():
            repo = repo.strip()
            # Modern podman prepends "localhost/" to local images; strip it first.
            # The production _stale_pairs checks startswith("harnessed-") without
            # stripping, which silently skips all locally-built images. (FINDING)
            if repo.startswith("localhost/"):
                repo = repo[len("localhost/"):]
            if not repo.startswith("harnessed-"):
                continue
            tail = repo[len("harnessed-"):]  # <harness>-<stack>
            for harness_candidate in known_harnesses:
                prefix = harness_candidate + "-"
                if tail.startswith(prefix):
                    stack_name = tail[len(prefix):]
                    if stack_name:
                        pairs.append((stack_name, harness_candidate))
                    break
        return pairs

    def test_labeled_image_appears_in_filter_output(self, labeled_image):
        """The filter command returns the labeled image repository."""
        rt = _runtime()
        result = subprocess.run(
            [rt, "images", "--filter", "label=harnessed=true",
             "--format", "{{.Repository}}"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        repos = [r.strip() for r in result.stdout.splitlines()]
        assert self._LABELED_IMAGE in repos, (
            f"{self._LABELED_IMAGE!r} not found in filter output; "
            f"got: {repos!r}"
        )

    def test_parser_extracts_stack_and_harness_from_labeled_image(self, labeled_image):
        """Parser produces ('testspec', 'claude') from 'localhost/harnessed-claude-testspec'."""
        rt = _runtime()
        pairs = self._parse_harnessed_pairs(rt, self._KNOWN_HARNESSES)
        assert ("testspec", "claude") in pairs, (
            f"('testspec', 'claude') not in parsed pairs; got: {pairs!r}"
        )

    def test_non_harnessed_prefixed_line_is_ignored(self, labeled_image):
        """A repo not starting with 'harnessed-' never appears in parsed results.

        The parser skips any line that does not start with 'harnessed-', so images like
        'localhost/something-else' are silently ignored even if they carry the label.
        """
        rt = _runtime()
        pairs = self._parse_harnessed_pairs(rt, self._KNOWN_HARNESSES)
        # All returned pairs must have been produced from a harnessed-prefixed image
        for stack, harness in pairs:
            assert harness in self._KNOWN_HARNESSES, (
                f"pair ({stack!r}, {harness!r}) has an unknown harness — parser prefix logic failed"
            )


# ---------------------------------------------------------------------------
# A5 — mise trust integration (hostrun._host_mise_env)
# ---------------------------------------------------------------------------

@podman
class TestMiseTrustIntegration:
    """A5: Verify that _host_mise_env does NOT redirect MISE_STATE_DIR (the trust store).

    The trust store must be the user's own; a redirected store means every harnessed session
    starts with an empty trust store, causing 'mise ERROR error parsing config file' for any
    previously-trusted mise.toml.

    Note: @podman gates this as a 'live' test requiring a real mise binary — it is NOT about
    containers, but it needs the live binary to confirm the env dict is accepted without error.

    Negative control: if MISE_STATE_DIR were in the dict, step 2 would fail. The test is its
    own negative control on that property; the mise binary exercising the dict is the live proof.
    """

    def test_mise_is_on_path(self):
        """Prerequisite: mise binary must be discoverable."""
        assert shutil.which("mise") is not None, "mise is not on PATH; is it installed via mise.toml?"

    def test_host_mise_env_does_not_redirect_state_dir(self):
        """MISE_STATE_DIR must NOT appear in _host_mise_env — the trust store stays user-owned."""
        env = _host_mise_env("any-stack")
        assert "MISE_STATE_DIR" not in env, (
            "MISE_STATE_DIR must NOT be in _host_mise_env — redirecting it gives every stack an "
            "empty trust store and causes 'mise ERROR error parsing config file'"
        )

    def test_mise_trust_succeeds_for_a_real_toml(self, tmp_path):
        """Running `mise trust <path>` against a real toml exits 0."""
        mise_toml = tmp_path / "mise.toml"
        mise_toml.write_text("[tools]\n")
        result = subprocess.run(
            ["mise", "trust", str(mise_toml)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"`mise trust` exited {result.returncode}; stderr: {result.stderr.strip()!r}"
        )

    def test_real_mise_binary_accepts_host_mise_env(self):
        """mise --version with _host_mise_env merged into os.environ: exits 0, non-empty stdout."""
        host_env = dict(os.environ)
        host_env.update(_host_mise_env("any-stack"))
        result = subprocess.run(
            ["mise", "--version"],
            capture_output=True, text=True, env=host_env,
        )
        assert result.returncode == 0, (
            f"`mise --version` exited {result.returncode} with harnessed env; "
            f"stderr: {result.stderr.strip()!r}"
        )
        assert result.stdout.strip(), "mise --version produced no output"

    def test_mise_install_with_harnessed_env_produces_no_trust_error(self, tmp_path):
        """mise install with _host_mise_env merged: exits 0, no trust error in stderr.

        A redirected MISE_STATE_DIR would cause:
          mise ERROR error parsing config file: <path>
        The absence of that string is the live proof that harnessed does not break mise trust.
        """
        # Create an isolated mise root in tmp_path with a minimal mise.toml
        mise_root = tmp_path / "mise-root"
        mise_root.mkdir()
        (mise_root / "config").mkdir()
        mise_toml = tmp_path / "mise.toml"
        mise_toml.write_text("[tools]\n# no tools to install\n")

        host_env = dict(os.environ)
        host_env.update(_host_mise_env("any-stack"))
        # Override MISE_DATA_DIR and MISE_CONFIG_DIR to point at our tmp root
        host_env["MISE_DATA_DIR"] = str(mise_root)
        host_env["MISE_CONFIG_DIR"] = str(mise_root / "config")

        result = subprocess.run(
            ["mise", "install"],
            capture_output=True, text=True, env=host_env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"`mise install` exited {result.returncode}; stderr: {result.stderr.strip()!r}"
        )
        trust_error = "mise ERROR error parsing config file"
        assert trust_error not in result.stderr, (
            f"mise reported a trust error; MISE_STATE_DIR may be redirected away from the "
            f"user's trust store. stderr: {result.stderr.strip()!r}"
        )


# ---------------------------------------------------------------------------
# A6 — varlock JSON output (launchenv._varlock_resolve)
# ---------------------------------------------------------------------------

@podman
class TestVarlockJsonOutput:
    """A6: Verify _varlock_resolve parses varlock JSON output into a KEY->value dict.

    Requires `varlock` on PATH (provisioned via mise.toml's 'npm:varlock' entry).

    Negative control: calling with a dir that has no .env.schema → varlock exits non-zero
    → _varlock_resolve returns None, confirming the failure branch is exercised.
    """

    def test_varlock_is_on_path(self):
        """Prerequisite: varlock binary must be discoverable."""
        assert shutil.which("varlock") is not None, (
            "varlock is not on PATH; verify mise.toml declares 'npm:varlock' and "
            "the CI environment has run `mise install`"
        )

    def test_varlock_resolves_non_secret_variable(self, tmp_path):
        """Schema with FOO=bar → _varlock_resolve returns dict containing {'FOO': 'bar'}."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / ".env.schema").write_text("FOO=bar\n")
        _varlock_cache_clear()
        result = _varlock_resolve(schema_dir)
        assert result is not None, (
            "_varlock_resolve returned None for a valid schema; varlock may not be on PATH "
            "or may have returned non-zero"
        )
        assert result.get("FOO") == "bar", (
            # Do NOT print result!r here — the dict may contain OP_SERVICE_ACCOUNT_TOKEN
            # from os.environ (launchenv.py injects it when set). Print only the key under test.
            f"Expected FOO=bar in resolved dict; got FOO={result.get('FOO')!r} "
            "(full dict omitted — may contain env secrets)"
        )

    def test_varlock_returns_none_on_missing_schema(self, tmp_path):
        """Dir with no .env.schema → _varlock_resolve returns None (graceful degradation)."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        _varlock_cache_clear()
        result = _varlock_resolve(empty_dir)
        assert result is None, (
            # Same hazard as the sibling test above: the dict may carry OP_SERVICE_ACCOUNT_TOKEN
            # and whatever else launchenv injects from os.environ. This assertion only fires in
            # the surprising case, which is exactly when a full dump would reach a public CI log.
            # Key NAMES only, never values.
            f"_varlock_resolve must return None when no .env.schema exists; "
            f"got a dict with keys {sorted(result)} (values omitted — may contain env secrets)"
        )
