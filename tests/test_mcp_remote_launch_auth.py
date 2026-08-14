"""The launch-time consent prompt for OAuth MCP servers.

WHY IT EXISTS. mcp-remote is hatago's stdio child, so a GRANDCHILD of the harness. When it has no
token it prints `Please authorize this client by visiting: <url>` on a stderr the harness discards,
then blocks. What the operator sees is `MCP error -32001: Request timed out`, three retries later,
naming nothing. The token store, the published callback port and the mount were all already correct
— the only missing piece was a human being told to click something.

So the launch asks first, while someone is still watching, and only when there is nothing to reuse.
"""

import hashlib
import json
import re
from pathlib import Path



from harnessed import mounts

PIN = "0.1.38-test.3"
SPEC_ARG = f"@drmikecrowe/mcp-remote@{PIN}"
URL = "https://mcp.atlassian.com/v1/mcp/authv2"
PORT = "32081"
INST = "harnessed-claude-isolated-b3fb02f8"
# Verified against a real store, not derived from documentation: the file sitting beside the live
# Atlassian consent is named for this digest.
URL_SHA = "704a04845e8f89b90b87e2859a49ca9fd773b21816b45b2106417094b4c7fab3"


class _Server:
    def __init__(self, name="atlassian", args=None, is_stdio_child=True):
        self.name = name
        self.args = args if args is not None else ["dlx", SPEC_ARG, URL, PORT]
        self.is_stdio_child = is_stdio_child


def _store(tmp_path: Path) -> Path:
    return tmp_path / ".mcp-auth"


def _write_token(tmp_path: Path, digest: str = URL_SHA, version: str = PIN) -> Path:
    token = _store(tmp_path) / f"mcp-remote-{version}" / f"{digest}_tokens.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(json.dumps({"access_token": "x"}), encoding="utf-8")
    return token


class TestTheTokenPathIsComputedNotGuessed:
    """The basename is SHA-256 of the server URL. Computing it makes "is this authorized?" exact —
    a directory-contents heuristic would confuse two servers, and would call a half-finished consent
    (client_info + code_verifier written, tokens not) authorized."""

    def test_the_digest_is_sha256_of_the_server_url(self):
        assert hashlib.sha256(URL.encode()).hexdigest() == URL_SHA

    def test_the_path_carries_the_pinned_version(self, tmp_path):
        path = mounts._mcp_remote_token_file(_store(tmp_path), ["dlx", SPEC_ARG, URL, PORT])
        assert path == _store(tmp_path) / f"mcp-remote-{PIN}" / f"{URL_SHA}_tokens.json"

    def test_a_bumped_pin_moves_the_path(self, tmp_path):
        """The store is version-namespaced upstream, so a bump must not read the old version's
        token and report a server authorized that mcp-remote will treat as fresh."""
        other = mounts._mcp_remote_token_file(
            _store(tmp_path), ["dlx", "@drmikecrowe/mcp-remote@9.9.9", URL, PORT]
        )
        assert "mcp-remote-9.9.9" in str(other)

    def test_a_different_server_gets_a_different_file(self, tmp_path):
        a = mounts._mcp_remote_token_file(_store(tmp_path), ["dlx", SPEC_ARG, URL, PORT])
        b = mounts._mcp_remote_token_file(
            _store(tmp_path), ["dlx", SPEC_ARG, "https://mcp.example.com/mcp", PORT]
        )
        assert a != b

    def test_a_header_before_the_url_does_not_become_the_url(self, tmp_path):
        """Upstream splices `--header <value>` pairs out before indexing, so counting them would
        hash the header value and look for a token file that can never exist."""
        path = mounts._mcp_remote_token_file(
            _store(tmp_path), ["dlx", SPEC_ARG, "--header", "Authorization: Bearer x", URL, PORT]
        )
        assert f"{URL_SHA}_tokens.json" in str(path)

    def test_argv_naming_no_server_yields_no_path(self, tmp_path):
        assert mounts._mcp_remote_token_file(_store(tmp_path), ["dlx", SPEC_ARG]) is None


class TestOnlyAServerWithNoTokenIsAskedAbout:
    def test_a_server_with_no_token_is_pending(self, tmp_path):
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert [n for n, _ in pending] == ["atlassian"]

    def test_a_server_with_a_token_is_not(self, tmp_path):
        _write_token(tmp_path)
        assert mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path) == []

    def test_a_half_finished_consent_still_counts_as_pending(self, tmp_path):
        """The real mid-flow state: client_info and code_verifier present, tokens absent. That is
        unauthorized, and treating it as done would launch straight back into the timeout."""
        d = _store(tmp_path) / f"mcp-remote-{PIN}"
        d.mkdir(parents=True)
        (d / f"{URL_SHA}_client_info.json").write_text("{}", encoding="utf-8")
        (d / f"{URL_SHA}_code_verifier.txt").write_text("v", encoding="utf-8")
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert [n for n, _ in pending] == ["atlassian"]

    def test_a_token_for_a_different_version_does_not_count(self, tmp_path):
        _write_token(tmp_path, version="0.0.1")
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert [n for n, _ in pending] == ["atlassian"]

    def test_servers_that_are_not_mcp_remote_are_ignored(self, tmp_path):
        other = _Server(name="context-mode", args=["context-mode"])
        assert mounts._mcp_remote_pending_auth([other], INST, False, home=tmp_path) == []

    def test_a_network_server_is_ignored(self, tmp_path):
        """A `url:` server is proxied by hatago directly and never spawns this CLI, so it has no
        token of its own to wait for."""
        net = _Server(name="remote", is_stdio_child=False)
        assert mounts._mcp_remote_pending_auth([net], INST, False, home=tmp_path) == []

    def test_two_servers_are_reported_independently(self, tmp_path):
        second = _Server(name="other", args=["dlx", SPEC_ARG, "https://mcp.example.com/mcp", "4000"])
        _write_token(tmp_path)  # only the first is authorized
        pending = mounts._mcp_remote_pending_auth([_Server(), second], INST, False, home=tmp_path)
        assert [n for n, _ in pending] == ["other"]

    def test_declaration_order_is_preserved(self, tmp_path):
        second = _Server(name="other", args=["dlx", SPEC_ARG, "https://mcp.example.com/mcp", "4000"])
        pending = mounts._mcp_remote_pending_auth([_Server(), second], INST, False, home=tmp_path)
        assert [n for n, _ in pending] == ["atlassian", "other"]


class TestTheStoreLookedAtIsTheStoreMounted:
    """The mount and the check must resolve to ONE directory. If they diverged, a launch would mount
    a good token and then prompt for it anyway, forever."""

    def test_a_shared_identity_stack_reads_the_hosts_store(self, tmp_path):
        assert mounts._mcp_auth_store_dir(INST, False, home=tmp_path) == tmp_path / ".mcp-auth"

    def test_an_isolated_stack_reads_its_own(self, tmp_path):
        got = mounts._mcp_auth_store_dir(INST, True, home=tmp_path)
        assert INST in str(got) and got != tmp_path / ".mcp-auth"

    def test_the_mount_source_is_the_directory_the_check_uses(self, tmp_path):
        """Asserted against the mount ARGUMENT, so the two cannot drift apart silently."""
        args = mounts._mcp_auth_store_mount([_Server()], INST, False, home=tmp_path)
        source = args[1].split(":")[0]
        assert Path(source) == mounts._mcp_auth_store_dir(INST, False, home=tmp_path)


class TestTheLaunchSequenceAsksAtTheOnlyMomentItCan:
    def _launcher(self) -> str:
        from harnessed import paths
        return (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )

    def test_the_prompt_runs_before_the_harness_attaches(self):
        """After the pod (which supplies the published callback port and the store mount) and before
        attach (after which nothing can surface a URL)."""
        src = self._launcher()
        ask = src.index("_authorize_mcp_remote_servers(\n")
        attach = src.index("_attach(rt, harness, inst")
        assert ask < attach

    def test_headless_refuses_rather_than_blocking(self):
        """A browser prompt in CI would hang to the job timeout and report nothing useful."""
        src = self._launcher()
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        assert "if headless:" in block and "typer.Exit(1)" in block

    def test_the_hub_is_stopped_only_where_one_is_running(self):
        """Under http the entrypoint already started hatago, which already holds the callback port
        through its own mcp-remote; under stdio there is no hub until attach."""
        src = self._launcher()
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        assert "restart_hub = stk.hub_transport != HUB_TRANSPORT_STDIO" in block
        assert "pkill -f hatago-mcp-hub" in block

    def test_the_hub_comes_back_even_if_the_consent_fails(self):
        """`finally`. A cancelled consent must not leave the operator with an instance that has no
        MCP at all — strictly worse than one server short."""
        src = self._launcher()
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        assert re.search(r"finally:\s*\n\s*#", block)

    def test_the_hub_restart_matches_the_entrypoint(self):
        """The restart re-issues the hub command rather than re-running `harnessed-start`, whose
        `exec sleep infinity` would fork a second PID-1 stand-in. That makes it a SECOND copy of the
        command, so the two are pinned together here."""
        from harnessed import paths
        src = self._launcher()
        entry = (paths.harnessed_home() / "catalog" / "base" / "harnessed-start").read_text(
            encoding="utf-8"
        )
        assert "hatago serve --http" in entry
        assert "hatago serve --http" in src
        assert "harnessed-start >" not in src, (
            "the restart re-runs the entrypoint, which would spawn a second `sleep infinity`"
        )

    def test_reauth_is_offered_as_a_flag(self):
        src = self._launcher()
        assert '"--reauth"' in src

    def test_reauth_asks_about_already_authorized_servers_too(self):
        """The whole reason to pass it is that an existing token is wrong — revoked, wrong account,
        too few scopes — and those are exactly the ones the pending check reports as fine."""
        src = self._launcher()
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        assert "if reauth:" in block


class TestTheConsentKnowsWhenItIsDone:
    def _consent(self) -> str:
        from harnessed import paths
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("def _run_mcp_remote_consent"):]
        return block[:block.index("\ndef ")]

    def test_the_token_file_is_the_completion_signal(self):
        """mcp-remote does not exit on success — it becomes the proxy — so waiting for exit would
        hang forever on the happy path."""
        assert "token.is_file()" in self._consent()

    def test_an_early_exit_is_not_mistaken_for_success(self):
        """Declined, crashed, or bad URL: the process ends with no token, and that is a failure."""
        block = self._consent()
        assert "proc.poll() is not None" in block

    def test_it_is_bounded_and_cleans_up(self):
        block = self._consent()
        assert "deadline" in block
        assert "proc.terminate()" in block and "proc.kill()" in block

    def test_cancelling_one_consent_does_not_abort_the_launch(self):
        """Ctrl-C is a choice about this server, not about the stack."""
        assert "KeyboardInterrupt" in self._consent()

    def test_it_runs_interactively_in_the_instance(self):
        """`-it`, because the whole point is that a human reads the URL it prints; and in the
        container, where the published port and the mounted store already are."""
        assert '"exec", "-it", instance' in self._consent()
