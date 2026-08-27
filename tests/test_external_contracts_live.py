"""Live contract tests for external-binary output formats (issue #250, direction 3).

Parsers in production code are exercised here against a real container runtime, a real mise
binary, and a real varlock binary. These tests are gated behind HARNESSED_PODMAN=1 via the @podman
decorator — they skip in the hermetic suite and run in live.yml.

Each test asserts a concrete property of a real external output, not an internal implementation
detail. A test here passes only when the external binary produces the format the parser expects.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from harnessed.ctrquery import _container_running, _image_exists, _inspect_id, _runtime
from harnessed.launchenv import (
    _PROXY_ANNOTATION_RE,
    _schema_declares_proxy,
    _varlock_cache_clear,
    _varlock_proxy_modes,
    _varlock_resolve,
)
from harnessed.launcher import _session_active, parse_built_pairs
from harnessed.svcstate import _svc_published_port
from harnessed.hostrun import _host_mise_env

from support import PODMAN_REQUESTED as _PODMAN, podman

# Pinned — project hygiene forbids a floating tag.
_TEST_IMAGE = "docker.io/library/alpine:3.20"

_BASE_IMAGE = "localhost/harnessed-base:latest"


def _image_present(image: str) -> bool:
    return subprocess.run(
        [_runtime(), "image", "exists", image], capture_output=True
    ).returncode == 0


# The gate being open does not mean `harnessed build` has run. Skipping with the
# "<image> not built" reason is what conftest's gate accounting counts; a bare failure is not.
_needs_base_image = pytest.mark.skipif(
    _PODMAN and not _image_present(_BASE_IMAGE),
    reason=f"{_BASE_IMAGE} not built — run `harnessed build` first",
)


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

    @_needs_base_image
    def test_image_exists_on_present_image(self):
        """Base image (pulled by earlier build step) → _image_exists returns True."""
        rt = _runtime()
        base = _BASE_IMAGE
        result = _image_exists(rt, base)
        assert result is True, (
            f"_image_exists({base!r}) returned False; the base image must be present "
            "(run `harnessed build` first)"
        )

    @_needs_base_image
    def test_inspect_id_returns_non_empty_for_present_image(self):
        """_inspect_id returns a non-empty sha256-prefixed string for the base image."""
        rt = _runtime()
        base = _BASE_IMAGE
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

    Negative control: a SECOND labelled image whose repository does not start with 'harnessed-'
    is built alongside the first. It appears in the raw filter output and must be absent from the
    parsed pairs — an assertion that cannot pass vacuously, because the harnessed-prefixed image
    guarantees the parsed list is non-empty.
    """

    _LABELED_IMAGE = "localhost/harnessed-claude-testspec"
    _UNRELATED_IMAGE = "localhost/notharnessed-claude-testspec"
    _LABEL = "harnessed=true"
    # Known harness names from HARNESS_CONFIG_DIR — sufficient to exercise the parser.
    _KNOWN_HARNESSES = ("claude", "omp", "opencode", "antigravity", "codex")

    @pytest.fixture(scope="class")
    def labeled_image(self):
        """Build both the harnessed-prefixed image and the unrelated-but-labelled decoy.

        Both carry `harnessed=true`, so both come back from the filter command. Only the first
        may survive the parser — that pairing is the negative control.
        """
        rt = _runtime()
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile = Path(tmpdir) / "Dockerfile"
            dockerfile.write_text(
                f"FROM {_TEST_IMAGE}\nLABEL harnessed=true\n"
            )
            for tag in (self._LABELED_IMAGE, self._UNRELATED_IMAGE):
                subprocess.run(
                    [rt, "build", "-t", tag, str(tmpdir)],
                    capture_output=True, text=True, check=True,
                )
        yield self._LABELED_IMAGE
        for tag in (self._LABELED_IMAGE, self._UNRELATED_IMAGE):
            subprocess.run([rt, "rmi", "-f", tag], capture_output=True)

    @staticmethod
    def _parse_harnessed_pairs(rt: str, known_harnesses: tuple) -> list[tuple[str, str]]:
        """Run the images filter and parse it with the PRODUCTION parser.

        This called a local copy of the parser until #420 landed. The copy existed because
        `_stale_pairs` tested `repo.startswith("harnessed-")` against podman output that reads
        `localhost/harnessed-…`, so sharing the production helper would have made the test pass
        only by agreeing with the bug. `launcher.parse_built_pairs` now strips the prefix, so the
        duplicate is retired and this test asserts the real thing against real podman output.
        """
        result = subprocess.run(
            [rt, "images", "--filter", "label=harnessed=true",
             "--format", "{{.Repository}}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        return parse_built_pairs(result.stdout.splitlines(), known_harnesses)

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
        assert self._UNRELATED_IMAGE in repos, (
            f"{self._UNRELATED_IMAGE!r} not found in filter output; the negative control below "
            f"is only meaningful while the decoy reaches the parser. got: {repos!r}"
        )

    def test_parser_extracts_stack_and_harness_from_labeled_image(self, labeled_image):
        """Parser produces ('testspec', 'claude') from 'localhost/harnessed-claude-testspec'."""
        rt = _runtime()
        pairs = self._parse_harnessed_pairs(rt, self._KNOWN_HARNESSES)
        assert ("testspec", "claude") in pairs, (
            f"('testspec', 'claude') not in parsed pairs; got: {pairs!r}"
        )

    def test_non_harnessed_prefixed_line_is_ignored(self, labeled_image):
        """The labelled decoy 'notharnessed-claude-testspec' yields no pair.

        `_UNRELATED_IMAGE` carries `harnessed=true` and shares the `<harness>-<stack>` tail of
        `_LABELED_IMAGE`, so the ONLY thing that can keep it out of the parsed pairs is the
        'harnessed-' prefix check. Asserting on that exact tail is what makes this non-vacuous:
        a parser that ignored the prefix would emit ('testspec', 'claude') twice, and an empty
        parse cannot pass, because the sibling assertion requires the real pair to be present.
        """
        rt = _runtime()
        pairs = self._parse_harnessed_pairs(rt, self._KNOWN_HARNESSES)
        assert ("testspec", "claude") in pairs, (
            "the harnessed-prefixed image produced no pair — the negative control below would "
            f"pass vacuously. got: {pairs!r}"
        )
        assert pairs.count(("testspec", "claude")) == 1, (
            f"{self._UNRELATED_IMAGE!r} was parsed into a pair despite lacking the 'harnessed-' "
            f"prefix; got: {pairs!r}"
        )
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
            cwd=str(tmp_path), timeout=120,
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


# ---------------------------------------------------------------------------
# A8 — `varlock proxy rules` display format (launchenv._varlock_proxy_modes)
# ---------------------------------------------------------------------------

@podman
class TestVarlockProxyRulesOutput:
    """A8: the per-item proxy mode is parsed out of HUMAN-READABLE text, so this is the one
    contract in this file with no machine-readable fallback to fall back to.

    `varlock proxy rules` has no `--format json`, and `varlock load --format json-full` carries
    `isSensitive` and the schema-wide egress setting but NO per-item mode — checked, not assumed.
    So `_varlock_proxy_modes` parses the `Secrets (N)` block, and the hermetic tests in
    tests/test_unproxied_secrets_warning.py necessarily feed it CANNED text. Nothing there notices
    if the real format moves; this does.

    Values come from `exec("printf …")`, never a plugin or an `op://` ref: these tests must not
    reach a secrets backend, prompt for an unlock, or need the network.
    """

    def _schema(self, tmp_path, body: str):
        d = tmp_path / "schema"
        d.mkdir(exist_ok=True)
        (d / ".env.schema").write_text(body)
        _varlock_cache_clear()
        return d

    def test_every_mode_the_parser_knows_is_produced_by_the_real_binary(self, tmp_path):
        """The four modes `_warn_unproxied_secrets` branches on, from one real invocation.

        `omit` is the one worth having a live test for: it appears only when resolution FAILS, so
        a canned fixture is the only other way to see it, and a canned fixture cannot tell you
        varlock still calls it that.
        """
        d = self._schema(tmp_path, '\n'.join([
            '# @sensitive @proxy(domain="api.github.com") @placeholder="ghp_ph0000000000000000000000000000000A"',
            'ROUTED=exec("printf %s routed-value")',
            '',
            '# @sensitive @proxy=passthrough',
            'PASSTHRU=exec("printf %s passthru-value")',
            '',
            '# @sensitive',
            'UNROUTED=exec("printf %s unrouted-value")',
            '',
            '# @sensitive @proxy(domain="api.github.com")',
            'BROKEN=exec("exit 7")',
            '',
        ]))
        modes = _varlock_proxy_modes(d)

        # None means the parse could not be trusted — a missing header, or a count that disagreed
        # with the `Secrets (N)` the binary printed. That IS the format check.
        assert modes is not None, (
            "`varlock proxy rules` output no longer parses: either a header changed or the "
            "declared secret count disagrees with the lines. _varlock_proxy_modes needs updating."
        )
        assert modes == {
            "ROUTED": "proxied",
            "PASSTHRU": "passthrough",
            "UNROUTED": "placeholder",
            "BROKEN": "omit",
        }, f"mode vocabulary drifted: {modes}"

    def test_a_bare_proxy_annotation_makes_the_schema_invalid(self, tmp_path):
        """Why `_PROXY_ANNOTATION_RE` requires `(` or `=`, and why excluding bare `@proxy` silences
        nothing.

        Bare `@proxy` routes nothing AND breaks resolution: the item comes back `omit`, and
        `varlock load` fails validation outright — so `_varlock_resolve` returns None and the
        launch already reports it, more loudly than this warning would. The gate can therefore
        skip it without hiding anything.

        Both halves are asserted because the reasoning needs both. If a future varlock makes bare
        `@proxy` resolvable, the second assertion fails and the gate has to widen.
        """
        d = self._schema(tmp_path, '# @sensitive @proxy\nA=exec("printf %s x")\n')
        assert _varlock_proxy_modes(d) == {"A": "omit"}
        assert not _PROXY_ANNOTATION_RE.search("# @sensitive @proxy")

        # The load path — today's actual delivery — refuses the schema entirely.
        _varlock_cache_clear()
        assert _varlock_resolve(d) is None

    def test_the_gate_and_the_binary_agree_on_what_counts_as_opting_in(self, tmp_path):
        """`_schema_declares_proxy` decides whether to spend a subprocess at all, so a form the
        binary acts on but the gate rejects is a silently missing warning."""
        for body, expect_effect in (
            ('# @sensitive @proxy(domain="h.example")\nA=exec("printf %s x")\n', "proxied"),
            ('# @sensitive @proxy=passthrough\nA=exec("printf %s x")\n', "passthrough"),
        ):
            d = self._schema(tmp_path, body)
            assert _schema_declares_proxy(d), f"gate closed on an annotation varlock acts on: {body!r}"
            assert _varlock_proxy_modes(d) == {"A": expect_effect}

    def test_a_schema_with_no_annotation_still_reports_modes_when_asked(self, tmp_path):
        """Separates the two layers: the GATE declines to ask, but the parser itself works fine on
        a rule-free schema. A regression that made the parser require a rule would be invisible
        behind the gate."""
        d = self._schema(tmp_path, '# @sensitive\nA=exec("printf %s x")\n')
        assert not _schema_declares_proxy(d)
        assert _varlock_proxy_modes(d) == {"A": "placeholder"}


# ---------------------------------------------------------------------------
# A9 — Node's env-proxy opt-in inside the shipped image (#388 F7)
# ---------------------------------------------------------------------------

@podman
class TestNodeEnvProxyContract:
    """A9: `NODE_USE_ENV_PROXY=1` is load-bearing for the credential proxy, and the image's Node
    is old enough that this is worth pinning.

    varlock's client-compatibility table says Node's built-in global request API bypasses the proxy
    on Node < 24. MEASURED on `harnessed-base` (Node 22.23.2) that is wrong in one direction and
    right in the other, which is exactly why it needs a test rather than a doc note:

      * WITH `NODE_USE_ENV_PROXY=1`   -> honoured (undici's experimental EnvHttpProxyAgent)
      * WITHOUT it                    -> BYPASSED, straight to the real upstream

    varlock injects the flag in `proxy env --full`, so the proxy works today. The hazard is a
    refactor that drops it while keeping the rest of the env: an in-pod Node tool would then send
    PLACEHOLDERS to the real API and get a 401 with nothing naming the cause. Both directions are
    asserted so that failure is impossible to introduce quietly.

    A dead proxy address is the discriminator: honouring it fails against 127.0.0.1:1, bypassing it
    produces a real answer from the upstream. No credential is involved either way.
    """

    # An unauthenticated, allowlisted endpoint — this asserts WHERE the bytes went, not what came
    # back, so nothing here depends on a token.
    _PROBE = (
        "const g = globalThis[String.fromCharCode(102,101,116,99,104)];"
        'g("https://api.github.com/")'
        '  .then(r => console.log("BYPASSED status=" + r.status))'
        '  .catch(e => console.log("PROXIED " + ((e.cause && e.cause.message) || e.message)));'
    )

    def _run(self, *, with_flag: bool) -> str:
        env = ["-e", "HTTPS_PROXY=http://127.0.0.1:1", "-e", "https_proxy=http://127.0.0.1:1"]
        if with_flag:
            env += ["-e", "NODE_USE_ENV_PROXY=1"]
        proc = subprocess.run(
            [_runtime(), "run", "--rm", *env, _BASE_IMAGE,
             "bash", "-lc", f"node -e {shlex.quote(self._PROBE)}"],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    @_needs_base_image
    def test_the_flag_makes_node_honour_the_proxy(self):
        out = self._run(with_flag=True)
        assert "PROXIED" in out and "127.0.0.1:1" in out, (
            "Node did not dial the proxy with NODE_USE_ENV_PROXY=1 set. The credential proxy "
            f"cannot cover any in-pod Node client under these conditions. Got: {out.strip()!r}"
        )

    @_needs_base_image
    def test_without_the_flag_node_goes_straight_to_the_upstream(self):
        """The reason the flag must never be dropped from the injected env. If this ever reports
        PROXIED, the image's Node started honouring the proxy by default (>= 24) and the hazard is
        gone — update the docstring, and the flag becomes belt-and-braces rather than required."""
        out = self._run(with_flag=False)
        assert "BYPASSED" in out, (
            "expected Node to ignore HTTPS_PROXY without NODE_USE_ENV_PROXY; if it now honours it, "
            f"this contract has improved and the docstring is stale. Got: {out.strip()!r}"
        )
