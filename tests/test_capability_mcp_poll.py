"""The MCP capability probe waits for hatago's children — bd harnessed-rv2.2.

`wait_ready` waits for hatago's OWN tcp port to accept a connection. It does NOT wait for the stdio
child servers hatago spawns to finish connecting, and `introspect_mcp` then read `hatago://servers`
exactly once. Measured on the dev box this was written on:

    hatago port ready:              0.2s
    servers ['time'] first seen:    0.4s
    lag after port-ready:           0.3s

A real 0.3s window that a warm fast box wins by luck. `live.yml` reported
`"present": false, "detail": "not connected (checked hatago://servers)"` for exactly the two
MCP-bearing stacks (hostmcp, gsd-core_repowise) while every skill in those same stacks was present
— the container and the profile mount were fine; only the children were missing.

These tests assert the PROPERTY — *a late-connecting child is still found* — not a call count.
A hatago read that returns nothing and then returns the server is the situation; the number of
attempts in between is an implementation detail that must be free to change.

They also pin the second half of the bead: when an expected server is absent, the report must carry
`/tmp/hatago.log`, or a runner-only MCP failure stays permanently undiagnosable from the CI log.
"""

from __future__ import annotations

import pytest

from harnessed import capability, schema
from harnessed import report as report_mod
from harnessed.capability import HATAGO_SERVERS_URI


@pytest.fixture(autouse=True)
def naps(monkeypatch) -> list[float]:
    """Record the poll's sleeps instead of taking them.

    Recorded rather than discarded because mutation testing showed a `lambda _s: None` stub makes
    the interval unobservable — `time.sleep(None)` scored identically to `time.sleep(1.0)`, so
    nothing pinned that the poll paces itself rather than spinning on `_mcp_from_hatago`.
    """
    naps: list[float] = []
    monkeypatch.setattr(capability.time, "sleep", naps.append)
    return naps


INSTANCE = "harnessed-claude-hostmcp-abc123"


def _hatago_returning(monkeypatch, *rounds: dict[str, str]) -> list:
    """Stub `_mcp_from_hatago` to yield `rounds` in order, then repeat the last one forever.

    Returns the list of instances it was asked about — its length is the call count (so a test can
    assert the single-shot contract for MCP-free stacks) and its contents pin that the RIGHT
    instance was probed. Mutation testing caught the second part: with the argument ignored,
    `_mcp_from_hatago(None)` scored identically to the real call, so nothing detected a probe
    pointed at the wrong container.
    """
    probed: list = []
    seq = list(rounds)

    def _fake(instance):
        i = min(len(probed), len(seq) - 1)
        probed.append(instance)
        return dict(seq[i])

    monkeypatch.setattr(capability, "_mcp_from_hatago", _fake)
    return probed


def _llm_returning(monkeypatch, servers: dict[str, str]) -> list:
    """Stub the LLM backstop; returns the (instance, harness) pairs it was called with."""
    called: list = []

    def _fake(instance, harness):
        called.append((instance, harness))
        return dict(servers)

    monkeypatch.setattr(capability, "_mcp_from_llm", _fake)
    return called


class TestThePollWaits:
    def test_a_late_connecting_child_is_still_found(self, monkeypatch, naps):
        """The bug: hatago's port is up, its child is not yet connected, and the single-shot read
        concluded 'absent'."""
        probed = _hatago_returning(monkeypatch, {}, {}, {"time": "connected"})
        _llm_returning(monkeypatch, {})

        servers, source = capability.introspect_mcp(INSTANCE, expect={"time"}, timeout=30)

        assert servers == {"time": "connected"}
        assert source == HATAGO_SERVERS_URI, (
            "the server was found by the authoritative hatago resource, so the report must say so "
            "rather than crediting the LLM backstop"
        )
        assert set(probed) == {INSTANCE}, f"probed the wrong container: {probed}"
        assert naps and all(n == capability.MCP_POLL_INTERVAL for n in naps), (
            f"the poll must pace itself at MCP_POLL_INTERVAL rather than spin; slept {naps}"
        )

    def test_a_partial_result_does_not_end_the_poll(self, monkeypatch):
        """One of two children connecting first must not be mistaken for 'this is all there is'."""
        _hatago_returning(
            monkeypatch, {"a": "connected"}, {"a": "connected", "b": "connected"},
        )
        _llm_returning(monkeypatch, {})

        servers, _ = capability.introspect_mcp(INSTANCE, expect={"a", "b"}, timeout=30)

        assert servers == {"a": "connected", "b": "connected"}

    def test_it_gives_up_at_the_deadline(self, monkeypatch):
        """A genuinely dead child must still go red — slower, but red."""
        _hatago_returning(monkeypatch, {})
        _llm_returning(monkeypatch, {})

        servers, source = capability.introspect_mcp(INSTANCE, expect={"time"}, timeout=0)

        assert servers == {}
        assert source == HATAGO_SERVERS_URI

    def test_the_llm_backstop_still_runs_when_hatago_yields_nothing(self, monkeypatch):
        """The pre-existing fallback is regression armor, not new behaviour — it must survive, and
        it must be handed the same instance and harness it was asked about."""
        _hatago_returning(monkeypatch, {})
        called = _llm_returning(monkeypatch, {"time": "x"})

        servers, source = capability.introspect_mcp(INSTANCE, "omp", expect={"time"}, timeout=0)

        assert servers == {"time": "x"}
        assert called == [(INSTANCE, "omp")], f"backstop called wrong: {called}"
        assert "omp" in source

    def test_the_harness_defaults_to_claude(self, monkeypatch):
        """`harness` routes the backstop and labels the source. The default is the historical call
        path, so it is behaviour, not a decoration."""
        _hatago_returning(monkeypatch, {})
        called = _llm_returning(monkeypatch, {"time": "x"})

        _servers, source = capability.introspect_mcp(INSTANCE, expect={"time"}, timeout=0)

        assert called == [(INSTANCE, "claude")]
        assert source.startswith("claude ")

    def test_a_stack_with_no_mcp_servers_pays_no_latency(self, monkeypatch, naps):
        """Most stacks declare no MCP at all. Polling for nothing would tax every one of them."""
        probed = _hatago_returning(monkeypatch, {})
        _llm_returning(monkeypatch, {})

        capability.introspect_mcp(INSTANCE, expect=set(), timeout=30)

        assert probed == [INSTANCE], f"expected a single-shot read, got {len(probed)} reads"
        assert naps == [], "an MCP-free stack must not sleep at all"

    def test_a_slow_first_probe_does_not_eat_the_retry_window(self, monkeypatch):
        """An adversarial reviewer's finding, and a real defect in the first implementation.

        `_exec` carries its own 60s subprocess timeout — the same number as `MCP_CONNECT_TIMEOUT`.
        The deadline used to start BEFORE the first `_mcp_from_hatago` call, so a `podman exec` that
        hung to its own timeout left the poll deadline already expired on first entry to the loop:
        zero retries, silently. A cold runner spawning uvx for the first time is exactly where a
        slow exec and a slow child connect happen together — so the fix for rv2.2 degraded precisely
        in the situation rv2.2 is about.

        The clock is faked rather than slept: the deadline arithmetic is what is under test.
        """
        clock = [0.0]
        monkeypatch.setattr(capability.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(capability.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))

        rounds = [{}, {}, {"time": "connected"}]
        calls = [0]

        def _slow_then_ready(_instance):
            i = min(calls[0], len(rounds) - 1)
            # The FIRST probe burns the entire timeout, as a hung `podman exec` would.
            clock[0] += capability.MCP_CONNECT_TIMEOUT if calls[0] == 0 else 0.0
            calls[0] += 1
            return dict(rounds[i])

        monkeypatch.setattr(capability, "_mcp_from_hatago", _slow_then_ready)
        _llm_returning(monkeypatch, {})

        servers, source = capability.introspect_mcp(
            INSTANCE, expect={"time"}, timeout=capability.MCP_CONNECT_TIMEOUT
        )

        assert servers == {"time": "connected"}, (
            f"the poll gave up after {calls[0]} probe(s); a slow first probe must not consume the "
            "retry window"
        )
        assert source == HATAGO_SERVERS_URI

    def test_the_old_call_shape_still_works(self, monkeypatch):
        """`introspect_mcp(inst, harness)` is called positionally elsewhere; the new parameters are
        keyword-only with defaults so that call site is untouched."""
        _hatago_returning(monkeypatch, {"time": "connected"})
        _llm_returning(monkeypatch, {})

        assert capability.introspect_mcp(INSTANCE, "claude")[0] == {"time": "connected"}


class TestTheReportCarriesNoChildProcessOutput:
    """T-02-07, restated: the report carries capability NAMES + STATUS only, never config values or
    secrets. `capability.py` says so three times — the module docstring, the `detail` field comment,
    and `_TEST_DETAIL_MAX`, which caps recipe-test output at 120 chars because "a stray secret could
    ride along".

    An earlier version of this change put a 200-line, unbounded, unredacted tail of
    `/tmp/hatago.log` into the same report. hatago's children are MCP servers that take credentials
    from the environment, and a crashing one prints exactly that — into a report that `--json` feeds
    to a PUBLIC CI log. CodeRabbit caught it. The log is now POINTED AT rather than copied.

    These tests are the guard that it does not come back.
    """

    def test_the_report_has_no_field_for_child_output(self):
        """Structural: there must be nowhere to put it."""
        fields = set(capability.CapabilityReport(stack="s").to_dict())
        assert fields == {"stack", "ok", "results"}, (
            f"the report grew a field beyond names+status: {fields}"
        )

    def test_nothing_reads_the_hub_log_into_the_process(self):
        """`read_hatago_log` existed to copy the log out of the container. It must not come back:
        a helper that returns the bytes is one refactor away from a field that publishes them."""
        assert not hasattr(capability, "read_hatago_log")

    def test_a_missing_server_points_at_the_log_instead_of_quoting_it(self):
        """The diagnosability rv2.2 asked for, without the egress. The detail names WHERE to look
        and how to keep the instance alive long enough to look."""
        expected = schema.Capabilities(mcp_servers=["time"], skills=[], commands=[], plugins=[])
        report = capability.build_report("s", expected, capability.LiveCapabilities(mcp={}))

        detail = report.results[0].detail
        assert "hatago.log" in detail, f"the miss does not say where to look: {detail!r}"
        assert "--keep" in detail, (
            f"teardown removes the instance, so a pointer that omits --keep is not actionable: "
            f"{detail!r}"
        )

    def test_a_present_server_gets_no_remediation_noise(self):
        expected = schema.Capabilities(mcp_servers=["time"], skills=[], commands=[], plugins=[])
        live = capability.LiveCapabilities(mcp={"time": "connected"}, mcp_source="src")
        detail = capability.build_report("s", expected, live).results[0].detail
        assert "hatago.log" not in detail

    def test_the_markdown_report_quotes_no_log_either(self):
        """`--json` is not the only egress; `harnessed test` without it renders markdown."""
        expected = schema.Capabilities(mcp_servers=["time"], skills=[], commands=[], plugins=[])
        rendered = report_mod.render_markdown(
            capability.build_report("s", expected, capability.LiveCapabilities(mcp={}))
        )
        assert "hatago.log" in rendered          # the pointer survives
        assert "```" not in rendered, (          # ...and no fenced block quoting container output
            f"the markdown report grew a quoted block: {rendered}"
        )


class TestIntrospectForwardsTheExpectation:
    """`introspect` is the only caller of `introspect_mcp` in production.

    If it dropped `expect_mcp` the poll would never engage on a real launch — and every test above
    would still pass, because they all call `introspect_mcp` directly. That is exactly the shape of
    hole this bead was filed about, so it gets its own test rather than being assumed.
    """

    def test_the_declared_servers_reach_the_probe(self, monkeypatch):
        seen: dict = {}

        def _fake(instance, harness="claude", *, expect=(), timeout=0):
            seen["expect"] = set(expect)
            return {"time": "connected"}, "src"

        monkeypatch.setattr(capability, "introspect_mcp", _fake)
        monkeypatch.setattr(capability, "_fileext_from_filesystem", lambda _i, _s: {"x"})

        live = capability.introspect("inst", "claude", expect_mcp={"time", "repowise"})

        assert seen["expect"] == {"time", "repowise"}
        assert live.mcp == {"time": "connected"}


class TestTheTestVerbPublishesNothingFromTheContainer:
    """The end-to-end shape of T-02-07 for this change: drive `run_capability_test` with a stack
    whose MCP server never connects, and assert the report it returns carries the POINTER and no
    container bytes. Every podman-facing call is stubbed; the data flow is what is under test."""

    def _report(self, monkeypatch, *, declared: set[str], connected: set[str]):
        expected = schema.Capabilities(
            mcp_servers=sorted(declared), skills=[], commands=[], plugins=[],
        )
        monkeypatch.setattr(capability.schema, "load_stack_with_recipes", lambda _r, _s: (None, []))
        monkeypatch.setattr(capability.schema, "expected_capabilities", lambda _s, _r: expected)
        monkeypatch.setattr(capability, "launch_headless", lambda *a, **k: "inst")
        monkeypatch.setattr(capability, "wait_ready", lambda *a, **k: True)
        monkeypatch.setattr(
            capability, "introspect",
            lambda *a, **k: capability.LiveCapabilities(mcp={n: "connected" for n in connected}),
        )
        monkeypatch.setattr(capability, "teardown", lambda *a, **k: None)
        # If anything tried to shell into the container for output, this would fire.
        monkeypatch.setattr(capability, "_exec", lambda *a, **k: pytest.fail(
            "run_capability_test read from the container after introspection — T-02-07"
        ))
        return capability.run_capability_test(".", "s", "claude", run_tests=False)

    def test_a_missing_server_yields_a_pointer_and_no_container_bytes(self, monkeypatch):
        report = self._report(monkeypatch, declared={"time"}, connected=set())
        assert report.ok is False
        detail = report.results[0].detail
        assert "hatago.log" in detail and "--keep" in detail
        assert set(report.to_dict()) == {"stack", "ok", "results"}

    def test_a_green_run_says_nothing_about_the_log(self, monkeypatch):
        report = self._report(monkeypatch, declared={"time"}, connected={"time"})
        assert report.ok is True
        assert "hatago.log" not in report.results[0].detail
