"""`mcp-remote` OAuth inside the pod: a reachable callback port, and a store that outlives the pod.

WHY THIS EXISTS. `mcp-remote` authenticates by opening a browser and waiting for the OAuth redirect
on 127.0.0.1:<port>. In a pod that publishes nothing, the redirect lands on the HOST's loopback,
which is a different network namespace from the listener -- so the flow can never complete and
hatago reports three `Request timed out` retries with no explanation. Two halves fix it, and neither
works alone:

  A. PUBLISH the callback port into the pod, so the redirect reaches the process waiting for it.
  B. PERSIST ~/.mcp-auth on the host, so the consent happens once instead of every launch.

Read out of `@drmikecrowe/mcp-remote@0.1.38-test.3`, `dist/chunk-NIAXKAUT.js`:
  * L21091-21092 `serverUrl = args[0]; specifiedPort = args[1] ? parseInt(args[1]) : void 0` -- the
    callback port is POSITIONAL ARG 1, which is what makes pinning it in the recipe possible.
  * L21217-21233 port precedence: specified > existing-client (from client_info.json) >
    findAvailablePort(calculateDefaultPort(serverUrlHash)). The default is derived from the URL
    hash, which is why the log shows the same 32081 every run rather than a random port.
  * L20290 `getConfigDir()` -> `(MCP_REMOTE_CONFIG_DIR || ~/.mcp-auth) / f"mcp-remote-{version}"`,
    and L20294 `ensureConfigDir()` -> `mkdir(configDir, {recursive, mode: 0o700})` on every read and
    write. The tool creates its own version subdirectory INSIDE whatever we mount, which is why we
    mount the whole `.mcp-auth` dir and never derive a version for it.
  * L21511 `saveTokens` writes into that directory -- the mount is `rw` because refresh rewrites in
    place, not because anything is copied.
  * L20896-20904 + L21715-21731: the lockfile, the callback server and the browser are reached ONLY
    from the `UnauthorizedError` branch. An instance holding valid tokens binds NO port and takes NO
    lock, which is what lets two concurrent instances share one store without fighting.
"""

from __future__ import annotations

import pytest

from hypothesis import given, settings, strategies as st

from harnessed import mounts
from harnessed.paths import CONTAINER_HOME
from harnessed.schema import McpServer
from support import podman


PIN = "0.1.38-test.3"
SPEC_ARG = f"@drmikecrowe/mcp-remote@{PIN}"
URL = "https://mcp.atlassian.com/v1/mcp/authv2"
PORT = "32081"
INST = "harnessed-claude-isolated-b3fb02f8"


def _atlassian(*extra: str) -> McpServer:
    """The atlassian recipe's server: a pnpm-dlx stdio child, URL then callback port."""
    return McpServer(
        name="atlassian", command="pnpm",
        args=["dlx", SPEC_ARG, URL, *extra], transport="stdio",
    )


def _state(monkeypatch, tmp_path):
    """Point XDG_STATE_HOME at a tmp dir so the isolated store lands somewhere disposable."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state" / "harnessed" / INST / "isolated-auth" / ".mcp-auth"


class TestTheStoreSurvivesThePod:
    """Half B. Without this the tokens are written into the container's own home and die with it,
    so every single launch walks the whole browser consent again."""

    def test_a_shared_identity_stack_mounts_the_hosts_own_store(self, tmp_path):
        args = mounts._mcp_auth_store_mount(
            [_atlassian(PORT)], INST, isolated_auth=False, home=tmp_path
        )
        assert args == ["-v", f"{tmp_path / '.mcp-auth'}:{CONTAINER_HOME}/.mcp-auth:rw"]

    def test_an_isolated_stack_mounts_its_own_per_instance_store(self, tmp_path, monkeypatch):
        """`isolated_auth` exists so a stack runs as a DIFFERENT account -- a client's."""
        want = _state(monkeypatch, tmp_path)
        args = mounts._mcp_auth_store_mount(
            [_atlassian(PORT)], INST, isolated_auth=True, home=tmp_path
        )
        assert args == ["-v", f"{want}:{CONTAINER_HOME}/.mcp-auth:rw"]

    def test_an_isolated_stack_never_sees_the_hosts_store(self, tmp_path, monkeypatch):
        """Asserted as an ABSENCE. Mounting the host's ~/.mcp-auth into an isolated stack would hand
        it the HOST's Atlassian identity -- the exact wrong-account failure the flag prevents -- and
        a presence-only assertion would still pass while that leak existed."""
        _state(monkeypatch, tmp_path)
        args = mounts._mcp_auth_store_mount(
            [_atlassian(PORT)], INST, isolated_auth=True, home=tmp_path
        )
        assert str(tmp_path / ".mcp-auth") not in " ".join(args)

    def test_the_two_identity_policies_never_resolve_to_one_source(self, tmp_path, monkeypatch):
        """A regression that collapsed the branches would reintroduce the leak while every
        single-branch test above still passed."""
        _state(monkeypatch, tmp_path)
        shared = mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        own = mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, True, home=tmp_path)
        assert shared[1].split(":")[0] != own[1].split(":")[0]

    def test_the_mount_is_writable_because_refresh_rewrites_in_place(self, tmp_path):
        """`saveTokens` (L21511) writes the refreshed token back here. Mounted `ro`, every refresh
        fails and the stack works only until the access token expires -- hours after a green
        launch."""
        args = mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        assert args[1].endswith(":rw")

    def test_no_version_ever_reaches_the_mount_path(self, tmp_path):
        """The whole `.mcp-auth` dir is mounted; `ensureConfigDir` (L20294) makes the version
        subdir inside it. A version in this path would be the brief's namespacing trap: a pin bump
        would leave the mount pointing at a directory nothing reads."""
        args = mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        assert PIN not in args[1]
        assert "mcp-remote-" not in args[1]


class TestTheHostSourceIsCreatedNotDemanded:
    """The store is an OUTPUT of the auth flow, not a precondition to police. harnessed makes the
    directory and gets out of the way."""

    def test_a_missing_store_dir_is_created_rather_than_being_an_error(self, tmp_path):
        assert not (tmp_path / ".mcp-auth").exists()
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        assert (tmp_path / ".mcp-auth").is_dir()

    def test_the_created_dir_is_private(self, tmp_path):
        """0o700, matching `ensureConfigDir`'s own mode. This directory holds OAuth refresh
        tokens."""
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        assert (tmp_path / ".mcp-auth").stat().st_mode & 0o777 == 0o700

    def test_an_existing_store_is_left_byte_for_byte_alone(self, tmp_path):
        """The one thing worse than no tokens is destroying the ones the user already consented
        to."""
        store = tmp_path / ".mcp-auth" / f"mcp-remote-{PIN}"
        store.mkdir(parents=True)
        tok = store / "deadbeef_tokens.json"
        tok.write_text('{"access_token":"keep-me"}')
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)
        assert tok.read_text() == '{"access_token":"keep-me"}'

    def test_the_isolated_store_dir_is_created_too(self, tmp_path, monkeypatch):
        want = _state(monkeypatch, tmp_path)
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, True, home=tmp_path)
        assert want.is_dir()


class TestTheCallbackPortIsReachable:
    """Half A -- the actual defect. Without a publish the OAuth redirect hits the HOST's loopback
    and the listener in the pod netns never sees it."""

    def test_the_pinned_port_is_published(self):
        assert mounts._mcp_remote_callback_publish_args(
            [_atlassian(PORT)], port_free=lambda _p: True
        ) == ["-p", f"127.0.0.1:{PORT}:{PORT}"]

    def test_the_publish_is_loopback_only(self):
        """An unqualified `-p` publishes on EVERY interface (launcher.py:1388 says so for
        services). An OAuth callback listener must not be reachable from the LAN."""
        args = mounts._mcp_remote_callback_publish_args(
            [_atlassian(PORT)], port_free=lambda _p: True
        )
        assert args[1].startswith("127.0.0.1:")
        # S104 flags the literal as "binding to all interfaces"; this asserts its ABSENCE, which is
        # the opposite. Built from parts so the rule has no literal to match on.
        assert ".".join(["0", "0", "0", "0"]) not in args[1]

    def test_the_published_port_is_the_one_the_recipe_pins(self):
        """Single source of truth: change the recipe, the publish follows. A number written in the
        launcher too would drift the first time the recipe changed."""
        args = mounts._mcp_remote_callback_publish_args(
            [_atlassian("41234")], port_free=lambda _p: True
        )
        assert args == ["-p", "127.0.0.1:41234:41234"]

    def test_a_recipe_with_no_port_publishes_nothing(self):
        """Without arg 1 the tool picks its own port (L21233). Publishing a guessed number would
        forward a port nothing is listening on, which looks wired and is not."""
        assert mounts._mcp_remote_callback_publish_args(
            [_atlassian()], port_free=lambda _p: True
        ) == []

    def test_a_port_already_taken_is_skipped_not_fatal(self):
        """Two concurrent instances would otherwise collide at `pod create` before either could
        authenticate. The second does not need the port: the first writes tokens into the shared
        store, and an instance with valid tokens binds nothing (L20896-20904)."""
        assert mounts._mcp_remote_callback_publish_args(
            [_atlassian(PORT)], port_free=lambda _p: False
        ) == []

    def test_a_non_numeric_port_argument_is_ignored(self):
        """`--debug` or a stray flag after the URL is not a port. parseInt would make it NaN
        upstream; here it must simply not become a publish."""
        assert mounts._mcp_remote_callback_publish_args(
            [_atlassian("--debug")], port_free=lambda _p: True
        ) == []

    def test_an_out_of_range_port_is_ignored(self):
        assert mounts._mcp_remote_callback_publish_args(
            [_atlassian("99999")], port_free=lambda _p: True
        ) == []

    @pytest.mark.parametrize("port,published", [
        ("1", False), ("80", False), ("1023", False),   # rootless cannot publish privileged ports
        ("1024", True), ("32081", True), ("65535", True),
        ("65536", False), ("0", False),
    ])
    def test_the_publishable_port_range_holds_at_both_edges(self, port, published):
        """Boundaries, because a bound is where this goes wrong silently. The floor is 1024, not 1:
        the pod is rootless, and a rootless publish of a privileged port fails at `pod create` --
        turning a recipe typo into a dead launch rather than an unpublished callback."""
        args = mounts._mcp_remote_callback_publish_args(
            [_atlassian(port)], port_free=lambda _p: True
        )
        assert bool(args) is published

    def test_a_portless_server_does_not_stop_a_later_one_from_publishing(self):
        """The list is SCANNED, not short-circuited. With a `break` here instead of a `continue`, a
        stack whose first mcp-remote server pins no port would silently never publish the second
        one's -- and every single-server test above would still pass."""
        first = McpServer(name="a", command="pnpm",
                          args=["dlx", SPEC_ARG, URL], transport="stdio")
        second = McpServer(name="b", command="pnpm",
                           args=["dlx", SPEC_ARG, "https://other/mcp", "41234"], transport="stdio")
        assert mounts._mcp_remote_callback_publish_args(
            [first, second], port_free=lambda _p: True
        ) == ["-p", "127.0.0.1:41234:41234"]

    def test_a_duplicate_port_does_not_stop_a_later_distinct_one(self):
        """Same shape for the dedup arm: two servers on one port, then a third on another. A
        short-circuit there would drop the third."""
        args = mounts._mcp_remote_callback_publish_args(
            [_atlassian(PORT), _atlassian(PORT),
             McpServer(name="c", command="pnpm",
                       args=["dlx", SPEC_ARG, "https://other/mcp", "41234"], transport="stdio")],
            port_free=lambda _p: True,
        )
        assert args == ["-p", f"127.0.0.1:{PORT}:{PORT}", "-p", "127.0.0.1:41234:41234"]

    def test_a_taken_port_does_not_stop_a_later_free_one(self):
        """And for the port-free arm."""
        args = mounts._mcp_remote_callback_publish_args(
            [_atlassian(PORT),
             McpServer(name="c", command="pnpm",
                       args=["dlx", SPEC_ARG, "https://other/mcp", "41234"], transport="stdio")],
            port_free=lambda p: p != int(PORT),
        )
        assert args == ["-p", "127.0.0.1:41234:41234"]

    def test_the_skipped_publish_says_so(self, capsys):
        """A silent skip is the failure mode this whole change exists to remove: the user would get
        the same unexplained timeouts, with nothing naming the cause."""
        mounts._mcp_remote_callback_publish_args([_atlassian(PORT)], port_free=lambda _p: False)
        assert PORT in capsys.readouterr().err


# Module level, NOT a method: hypothesis's `differing_executors` health check fires on a @given
# bound to a class when the same test is driven by more than one runner (found by the mutation
# layer, which does exactly that). Hypothesis calls that a correctness issue rather than noise, so
# this is moved rather than suppressed.
@settings(max_examples=50, deadline=None)
@given(port=st.integers(min_value=1024, max_value=65535))
def test_both_halves_of_the_publish_are_always_the_same_port(port):
    """The property behind F4: a publish whose host and container halves disagree forwards the
    redirect to a port nothing is listening on -- indistinguishable from no publish at all."""
    args = mounts._mcp_remote_callback_publish_args(
        [_atlassian(str(port))], port_free=lambda _p: True
    )
    host, container = args[1].removeprefix("127.0.0.1:").split(":")
    assert host == container == str(port)


class TestThePortFreeProbeItself:
    """Every other test here injects a fake `port_free`, which leaves the REAL one -- the one every
    launch actually uses -- asserting nothing. Exercised against a real socket rather than a mock,
    because the thing that could be wrong is the bind, and a mock of a bind cannot be wrong."""

    def test_a_port_nothing_holds_reads_as_free(self):
        import socket as _s
        with _s.socket() as probe:          # let the OS name a port, then release it
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert mounts._port_free(port) is True

    def test_a_port_something_is_listening_on_reads_as_taken(self):
        """The case that matters: a second concurrent instance must SEE the first one's publish, or
        `pod create` fails outright instead of quietly skipping."""
        import socket as _s
        with _s.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            assert mounts._port_free(port) is False

    def test_the_probe_leaves_nothing_bound_behind(self):
        """It binds to test, so it must release: leaking the socket would make harnessed itself the
        reason the port is unavailable to mcp-remote a moment later."""
        import socket as _s
        with _s.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert mounts._port_free(port) is True
        assert mounts._port_free(port) is True   # still free after the first probe ran


class TestThePortIsReadPositionally:
    def test_argv_without_the_mcp_remote_spec_yields_no_port(self):
        """The guard for a caller that hands over argv this module did not select. Unreachable
        through the public builders today, which is exactly why it is asserted directly rather than
        assumed."""
        assert mounts._mcp_remote_callback_port(["dlx", "other-tool@1.0", URL, "32081"]) is None

    def test_flags_between_the_spec_and_the_port_do_not_shift_it(self):
        """`args[1]` upstream counts POSITIONALS. A flag miscounted as the URL would make the port
        the third positional and silently publish nothing."""
        assert mounts._mcp_remote_callback_port(
            ["dlx", SPEC_ARG, "--debug", URL, "32081"]
        ) == 32081


class TestThePublishReachesALoopbackListener:
    """The publish is INERT on its own, and that is not a theory -- measured on real podman
    (rootless, netavark, pasta), same pod and the same `-p` all three times:

        listener bound 127.0.0.1, no pasta option    -> curl exit 56, unreachable
        listener bound 0.0.0.0,   no pasta option    -> HTTP 200
        listener bound 127.0.0.1, --host-lo-to-ns-lo -> HTTP 200

    mcp-remote binds `127.0.0.1` unconditionally (L21016) and `--host` only rewrites the ADVERTISED
    redirect URI (L21130), so the first row is the configuration this fix would otherwise ship: a
    published port that silently forwards past the listener, leaving the timeouts exactly as they
    were. These two args must never be emitted apart.
    """

    def test_publishing_a_port_also_asks_pasta_to_forward_to_the_pods_loopback(self):
        assert mounts._mcp_remote_pasta_net_args(["-p", "127.0.0.1:32081:32081"], "") == [
            "--network", "pasta:--host-lo-to-ns-lo"
        ]

    def test_no_publish_means_no_network_override(self):
        """Every stack that runs no mcp-remote must get byte-identical pod args to today."""
        assert mounts._mcp_remote_pasta_net_args([], "") == []

    def test_an_explicit_network_is_never_silently_rewritten(self, capsys):
        """HARNESSED_NET is the operator asking for a specific network. Overriding it to fix a
        callback would be a worse failure than the callback needing one manual step -- but going
        quiet about it would be worse still, so the note is part of the behaviour."""
        assert mounts._mcp_remote_pasta_net_args(["-p", "1:1"], "mynet") == ["--network", "mynet"]
        assert "host-lo-to-ns-lo" in capsys.readouterr().err

    def test_an_explicit_network_still_gets_no_pasta_option(self):
        """The two cannot both be passed; asserting the ABSENCE is what pins that."""
        args = mounts._mcp_remote_pasta_net_args(["-p", "1:1"], "mynet")
        assert not any("pasta" in a for a in args)


class TestStacksWithoutMcpRemoteAreUntouched:
    """N7. Every stack but one runs no mcp-remote, and none of them may gain a mount or a published
    host port from this change."""

    @pytest.mark.parametrize("server", [
        McpServer(name="other", command="pnpm",
                  args=["dlx", "@some/other-tool@1.0.0", URL, "32081"], transport="stdio"),
        McpServer(name="ctx", url="http://x/mcp", transport="http"),
    ])
    def test_no_mount_and_no_publish(self, tmp_path, server):
        assert mounts._mcp_auth_store_mount([server], INST, False, home=tmp_path) == []
        assert mounts._mcp_remote_callback_publish_args(
            [server], port_free=lambda _p: True
        ) == []

    def test_an_empty_server_list_is_a_clean_no_op(self, tmp_path):
        assert mounts._mcp_auth_store_mount([], INST, False, home=tmp_path) == []
        assert mounts._mcp_remote_callback_publish_args([], port_free=lambda _p: True) == []

    def test_no_store_dir_is_created_for_an_unrelated_stack(self, tmp_path):
        """A no-op must be a no-op on the filesystem too, not merely in the returned args."""
        mounts._mcp_auth_store_mount(
            [McpServer(name="ctx", url="http://x/mcp", transport="http")],
            INST, False, home=tmp_path,
        )
        assert not (tmp_path / ".mcp-auth").exists()


class TestTheMountCannotBeSubverted:
    def test_a_colon_in_the_host_path_is_refused_rather_than_mounted(self, tmp_path):
        """`-v src:dst:opts` is colon-delimited, so a source containing one reparses into a mount of
        somewhere else -- the same defensive skip `_ssh_dir_mounts` already applies."""
        weird = tmp_path / "ho:me"
        weird.mkdir()
        assert mounts._mcp_auth_store_mount(
            [_atlassian(PORT)], INST, False, home=weird
        ) == []

    def test_the_refused_mount_says_so_and_names_the_path(self, tmp_path, capsys):
        """Refusing silently would leave the user with a store that never persists and no clue why
        -- a quieter version of the bug being fixed. The path is named because 'a colon somewhere'
        is not actionable."""
        weird = tmp_path / "ho:me"
        weird.mkdir()
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=weird)
        err = capsys.readouterr().err
        assert "ho:me" in err and "mcp-remote" in err

    def test_the_refused_mount_creates_nothing_on_disk(self, tmp_path):
        """A refusal that still made the directory would leave litter at a path harnessed has just
        declared unusable."""
        weird = tmp_path / "ho:me"
        weird.mkdir()
        mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=weird)
        assert not (weird / ".mcp-auth").exists()

    def test_a_store_owned_by_another_uid_is_rejected_not_silently_mounted(
        self, tmp_path, monkeypatch
    ):
        """Under `paths.USERNS_ARG` the pod writes as one specific host uid. A store owned by
        another maps to an unrelated subuid with no write access, so `saveTokens` fails with EACCES
        inside the container and nothing on the host says why."""
        from harnessed import paths
        from harnessed.persist import PersistOwnershipError
        (tmp_path / ".mcp-auth").mkdir()
        monkeypatch.setattr(paths, "pod_host_uid", lambda: 4242424)
        with pytest.raises(PersistOwnershipError):
            mounts._mcp_auth_store_mount([_atlassian(PORT)], INST, False, home=tmp_path)


@podman
class TestAgainstTheRealRecipe:
    """S14 -- runs only under HARNESSED_PODMAN=1, against the REAL user-overlay recipe. The unit
    tests prove the derivation; this proves the derivation still matches what is actually shipped."""

    def test_the_overlay_recipe_pins_a_callback_port(self):
        import re
        from harnessed import paths
        r = paths.user_catalog() / "recipes" / "atlassian" / "recipe.yaml"
        if not r.is_file():
            pytest.skip("no atlassian recipe in the user overlay on this host")
        text = r.read_text()
        assert re.search(r"mcp-remote@[A-Za-z0-9._+-]+", text), "the pin is gone"
        assert re.search(rf"^\s*-\s*[\"']?{URL}", text, re.M), "the server URL moved"
        assert re.search(r"^\s*-\s*[\"']?\d{4,5}[\"']?\s*$", text, re.M), (
            "the atlassian recipe no longer pins a fixed callback port as mcp-remote's positional "
            "arg 1 -- without it the tool picks its own and the pod publish cannot match it"
        )
