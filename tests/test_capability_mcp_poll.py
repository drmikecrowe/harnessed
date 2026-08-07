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

    def test_the_old_call_shape_still_works(self, monkeypatch):
        """`introspect_mcp(inst, harness)` is called positionally elsewhere; the new parameters are
        keyword-only with defaults so that call site is untouched."""
        _hatago_returning(monkeypatch, {"time": "connected"})
        _llm_returning(monkeypatch, {})

        assert capability.introspect_mcp(INSTANCE, "claude")[0] == {"time": "connected"}


class TestTheHatagoLogIsSurfaced:
    """`live.yml` captures no hatago log, so rv2.2's runner-side cause was inferred from code shape
    rather than observed. Whatever the cause turns out to be, the next run must show it."""

    def test_a_missing_expected_server_captures_the_log(self, monkeypatch):
        captured: list[tuple[str, str]] = []

        def _fake_exec(instance, script, **_kw):
            captured.append((instance, script))
            return "hatago: child 'time' exited 1: ModuleNotFoundError\n"

        monkeypatch.setattr(capability, "_exec", _fake_exec)

        log = capability.read_hatago_log(INSTANCE)

        assert "ModuleNotFoundError" in log
        assert [i for i, _s in captured] == [INSTANCE], f"read the wrong container: {captured}"
        assert any(capability.HATAGO_LOG in s for _i, s in captured), (
            f"the probe did not read {capability.HATAGO_LOG}: {captured}"
        )

    def test_an_unreadable_log_is_empty_not_an_exception(self, monkeypatch):
        """Best-effort: a teardown race must not turn a capability failure into a crash."""
        monkeypatch.setattr(capability, "_exec", lambda *_a, **_k: "")
        assert capability.read_hatago_log(INSTANCE) == ""

    def test_the_report_carries_the_log_when_present(self):
        report = capability.CapabilityReport(stack="s", hatago_log="boom")
        assert report.to_dict()["hatago_log"] == "boom"

    def test_a_green_report_does_not_carry_an_empty_log_key(self):
        """Adding a permanently-empty key to every JSON report would be noise in every green run."""
        assert "hatago_log" not in capability.CapabilityReport(stack="s").to_dict()

    def test_the_human_readable_report_shows_it_too(self):
        """`harnessed test` without --json is what a person runs; the log has to reach them there,
        not only in the CI-facing JSON."""
        rendered = report_mod.render_markdown(
            capability.CapabilityReport(stack="s", hatago_log="child 'time' exited 1")
        )
        assert "child 'time' exited 1" in rendered

    def test_a_green_run_renders_no_log_section(self):
        assert "hatago log" not in report_mod.render_markdown(capability.CapabilityReport(stack="s"))


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


class TestTheWiringFromTheTestVerbToTheLog:
    """S13 as specified is about `run_capability_test`, not about `read_hatago_log` in isolation.

    The seam that actually matters is ORDERING: the log must be read while the instance is alive.
    Teardown runs in a `finally` before the report is built, so capturing it a few lines later —
    the obvious place — silently yields "" on every real run, and the CI log stays as useless as it
    was. Every podman-facing call is stubbed; what is under test is the sequence, not podman.
    """

    def _run(self, monkeypatch, *, declared: set[str], connected: set[str]) -> tuple:
        events: list[str] = []
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

        def _read_log(_instance, **_kw):
            events.append("read_log")
            return "hatago: child died"

        monkeypatch.setattr(capability, "read_hatago_log", _read_log)
        monkeypatch.setattr(capability, "teardown", lambda *a, **k: events.append("teardown"))
        report = capability.run_capability_test(".", "s", "claude", run_tests=False)
        return report, events

    def test_a_missing_server_captures_the_log_before_teardown(self, monkeypatch):
        report, events = self._run(monkeypatch, declared={"time"}, connected=set())
        assert report.hatago_log == "hatago: child died"
        assert events == ["read_log", "teardown"], (
            f"the log must be read while the instance is alive, got {events}"
        )
        assert report.to_dict()["hatago_log"] == "hatago: child died"

    def test_a_green_run_reads_no_log(self, monkeypatch):
        report, events = self._run(monkeypatch, declared={"time"}, connected={"time"})
        assert report.hatago_log == ""
        assert "read_log" not in events

    def test_a_stack_declaring_no_mcp_reads_no_log(self, monkeypatch):
        _report, events = self._run(monkeypatch, declared=set(), connected=set())
        assert "read_log" not in events
