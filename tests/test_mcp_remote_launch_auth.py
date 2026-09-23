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
    """Shaped like the real `McpServer`, which keeps `command` and `args` APART. Earlier versions of
    this fake carried only `args`, and that omission is exactly why the suite could not see the
    `dlx` bug: every test was written from the same half of the invocation the code used."""

    def __init__(
        self,
        name: str = "atlassian",
        args: list[str] | None = None,
        is_stdio_child: bool = True,
        command: str | None = "pnpm",
    ):
        self.name = name
        self.command = command
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


class TestWhatIsHandedToPodmanIsRunnable:
    """The consent runs `podman exec -it <inst> <argv>`, so argv must be the FULL command line.

    `McpServer` keeps `command` and `args` apart — `command: "pnpm"`, `args: ["dlx", …]` — which is
    the shape hatago's config wants and a trap for anything that runs the server itself. Passing
    `args` alone produced, on a real launch:

        crun: executable file `dlx` not found in $PATH

    No test over `args` could have caught it, because `args` was what the code and the tests were
    both built from. These assert the executable specifically.
    """

    def test_the_command_leads_the_argv(self, tmp_path):
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert pending[0][1][0] == "pnpm"

    def test_the_argv_is_command_plus_args(self, tmp_path):
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert pending[0][1] == ["pnpm", "dlx", SPEC_ARG, URL, PORT]

    def test_the_leading_token_is_never_a_bare_subcommand(self, tmp_path):
        """The specific shape of the bug: `dlx` is pnpm's subcommand, not an executable."""
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert pending[0][1][0] != "dlx"

    def test_a_server_with_no_command_falls_back_to_its_args(self):
        """`command` is Optional on the model. A server that carries the executable as args[0] must
        still yield something runnable rather than a list with a leading None."""
        srv = _Server(command=None, args=["mcp-remote-bin", SPEC_ARG, URL, PORT])
        assert mounts._mcp_remote_argv(srv) == ["mcp-remote-bin", SPEC_ARG, URL, PORT]

    def test_no_element_is_none(self, tmp_path):
        """`podman exec` takes strings; a None anywhere is a TypeError at the call, far from here."""
        pending = mounts._mcp_remote_pending_auth([_Server()], INST, False, home=tmp_path)
        assert all(isinstance(a, str) for a in pending[0][1])

    def test_reauth_builds_the_same_runnable_argv(self):
        """The --reauth branch assembles its own list, so it can drift from the pending path — and
        the original bug lived in both."""
        from harnessed import paths
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        assert "_mcp_remote_argv(s)" in block
        assert "list(s.args)" not in block, "the reauth branch still passes bare args"


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

    # The CALL, not the definition. `_authorize_mcp_remote_servers(\n` matches `def
    # _authorize_mcp_remote_servers(` first, which sits near the top of the file — so the original
    # form of this test compared the definition's offset against `_attach`'s and passed no matter
    # where the call went, including after it. It asserted nothing. Raised by CodeRabbit on PR #375.
    # Matches the ARGUMENTS, which only the call sites carry, and tolerates their differing
    # indentation (the re-attach one sits a level deeper).
    _CALL = re.compile(r"_authorize_mcp_remote_servers\(\s*\n\s*rt, inst, launch_servers, stk")

    def test_the_ordering_probe_matches_calls_and_not_the_definition(self):
        """Guards the guard. If this pattern ever matches the `def` line, every ordering assertion
        below silently goes vacuous — which is exactly how the first version of this test passed
        while asserting nothing."""
        src = self._launcher()
        found = list(self._CALL.finditer(src))
        assert len(found) >= 2, f"expected both call sites, matched {len(found)}"
        for occurrence in found:
            line_start = src.rfind("\n", 0, occurrence.start()) + 1
            assert not src[line_start:occurrence.start()].strip().startswith("def "), (
                "the ordering probe matches the function definition"
            )

    def test_every_attach_is_preceded_by_the_prompt(self):
        """After the pod (which supplies the published callback port and the store mount) and before
        attach (after which nothing can surface a URL). Asserted against EVERY `_attach` call site,
        not the first — the re-attach branch reaches its own, and skipping the prompt there is the
        defect this replaced."""
        src = self._launcher()
        calls = [m.start() for m in self._CALL.finditer(src)]
        attaches = [m.start() for m in re.finditer(r"_attach\(rt, harness, inst", src)]
        assert calls, "the launch never calls the consent prompt"
        assert attaches, "no attach call sites found — this test is looking at the wrong thing"
        for attach in attaches:
            assert any(call < attach for call in calls), (
                "an _attach is reachable with no preceding consent prompt"
            )

    def test_the_re_attach_branch_asks_too(self):
        """A running instance is the LIKELIEST state to need this — one that came up, failed to
        authorize, and is still running is exactly what an operator re-attaches to. Both branches
        there return straight into `_attach`, so without this `--reauth` silently did nothing
        whenever the pod happened to be up."""
        src = self._launcher()
        branch = src[src.index("if not headless and _container_running(rt, inst):"):]
        branch = branch[:branch.index("_attach(rt, harness, inst")]
        assert "_authorize_mcp_remote_servers(" in branch

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
        assert "pkill -f" in block

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


class TestAPartiallyWrittenTokenIsNotSuccess:
    """mcp-remote persists with a plain `writeFile` — the pinned dist contains no `rename(` at all —
    so the file appears at its final path EMPTY and fills in after. Existence alone would end the
    wait early, and the teardown would then terminate mcp-remote mid-write, leaving a corrupt token
    on disk permanently. Raised by CodeRabbit on PR #375."""

    def test_a_complete_token_is_accepted(self, tmp_path):
        from harnessed.launcher import _token_is_complete
        t = tmp_path / "t.json"
        t.write_text(json.dumps({"access_token": "abc"}), encoding="utf-8")
        assert _token_is_complete(t) is True

    def test_a_missing_file_is_not(self, tmp_path):
        from harnessed.launcher import _token_is_complete
        assert _token_is_complete(tmp_path / "absent.json") is False

    def test_the_moment_of_creation_is_not(self, tmp_path):
        """The exact state `writeFile` passes through: opened, still empty."""
        from harnessed.launcher import _token_is_complete
        t = tmp_path / "t.json"
        t.write_text("", encoding="utf-8")
        assert _token_is_complete(t) is False

    def test_a_half_written_object_is_not(self, tmp_path):
        from harnessed.launcher import _token_is_complete
        t = tmp_path / "t.json"
        t.write_text('{"access_token": "ab', encoding="utf-8")
        assert _token_is_complete(t) is False

    def test_an_empty_object_is_not(self, tmp_path):
        """`{}` parses. It carries no token, so it is not a finished consent."""
        from harnessed.launcher import _token_is_complete
        t = tmp_path / "t.json"
        t.write_text("{}", encoding="utf-8")
        assert _token_is_complete(t) is False

    def test_a_json_scalar_is_not(self, tmp_path):
        from harnessed.launcher import _token_is_complete
        t = tmp_path / "t.json"
        t.write_text("null", encoding="utf-8")
        assert _token_is_complete(t) is False

    def test_the_consent_waits_on_the_parsed_form(self):
        """Pinned structurally too: a future edit back to `token.is_file()` reopens the race."""
        from harnessed import paths
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("def _run_mcp_remote_consent"):]
        block = block[:block.index("\ndef ")]
        assert "_token_is_complete(token)" in block
        assert "token.is_file()" not in block


class TestTheHubStopCannotKillItsOwnShell:
    """`pkill -f` matches full command lines, including the `bash -lc "pkill -f …"` it runs as. The
    plain spelling makes the shell match itself and die before signalling the hub — observed while
    developing this, where the only symptom was an exec exiting 143 with the hub still up."""

    def _block(self) -> str:
        from harnessed import paths
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        return block[:block.index("\ndef ")]

    def test_the_pattern_cannot_match_itself(self):
        block = self._block()
        pattern = re.search(r"pkill -f '(\[.\][^']*)'", block)
        assert pattern, "the hub-stop pattern is not self-match-proof (no bracketed first char)"
        # The regex the shell runs, applied to the literal text of the command line that runs it.
        assert not re.search(pattern.group(1), pattern.group(0)), (
            "the pkill pattern still matches its own command line"
        )

    def test_it_still_matches_a_real_hub_command_line(self):
        """Self-match-proof is worthless if it also stops matching the process it must kill."""
        block = self._block()
        found = re.search(r"pkill -f '(\[.\][^']*)'", block)
        assert found, "no bracketed pkill pattern found"
        pattern = found.group(1)
        real = ("/home/harnessed/.local/share/mise/installs/node/22/bin/node "
                "/home/harnessed/.local/share/pnpm/global/v11/2-x/node_modules/"
                "@drmikecrowe/hatago-mcp-hub/dist/node/cli.js serve --http --port 3535")
        assert re.search(pattern, real)


class TestTheHeadlessErrorDoesNotSendTheReaderInACircle:
    def test_it_does_not_offer_reauth_as_the_way_out(self):
        """--reauth fails headless in exactly the same way, so naming it there is a loop. The only
        remedy is an interactive launch. Raised by CodeRabbit on PR #375."""
        from harnessed import paths
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("def _authorize_mcp_remote_servers"):]
        block = block[:block.index("\ndef ")]
        # The headless branch only (`--reauth` is legitimately named elsewhere in this function),
        # and CODE only — the comment above the message explains why the flag is withheld, and
        # matching that would assert the opposite of what it says.
        branch = block[block.index("    if headless:"):]
        branch = branch[:branch.index("typer.Exit(1)")]
        emitted = "\n".join(
            ln for ln in branch.splitlines() if not ln.lstrip().startswith("#")
        )
        assert "--reauth" not in emitted, "the headless error offers a flag that fails the same way"
        assert "interactively" in emitted, "the headless error does not name the actual remedy"


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
        hang forever on the happy path. The token file is what ends the wait; that it must be
        PARSED rather than merely present is pinned in TestAPartiallyWrittenTokenIsNotSuccess."""
        assert "_token_is_complete(token)" in self._consent()

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
