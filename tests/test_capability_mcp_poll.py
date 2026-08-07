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

from harnessed import capability
from harnessed.capability import HATAGO_SERVERS_URI


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """The poll's cadence is not under test; its termination conditions are."""
    monkeypatch.setattr(capability.time, "sleep", lambda _s: None)


def _hatago_returning(monkeypatch, *rounds: dict[str, str]) -> list[int]:
    """Stub `_mcp_from_hatago` to yield `rounds` in order, then repeat the last one forever.

    Returns a one-element list holding the call count, so a test can assert single-shot behaviour
    where "exactly one read" is itself the contract (an MCP-free stack must pay no latency).
    """
    calls = [0]
    seq = list(rounds)

    def _fake(_instance):
        i = min(calls[0], len(seq) - 1)
        calls[0] += 1
        return dict(seq[i])

    monkeypatch.setattr(capability, "_mcp_from_hatago", _fake)
    return calls


def _llm_returning(monkeypatch, servers: dict[str, str]) -> None:
    monkeypatch.setattr(capability, "_mcp_from_llm", lambda _i, _h: dict(servers))


class TestThePollWaits:
    def test_a_late_connecting_child_is_still_found(self, monkeypatch):
        """The bug: hatago's port is up, its child is not yet connected, and the single-shot read
        concluded 'absent'."""
        _hatago_returning(monkeypatch, {}, {}, {"time": "connected"})
        _llm_returning(monkeypatch, {})

        servers, source = capability.introspect_mcp("inst", expect={"time"}, timeout=30)

        assert servers == {"time": "connected"}
        assert source == HATAGO_SERVERS_URI, (
            "the server was found by the authoritative hatago resource, so the report must say so "
            "rather than crediting the LLM backstop"
        )

    def test_a_partial_result_does_not_end_the_poll(self, monkeypatch):
        """One of two children connecting first must not be mistaken for 'this is all there is'."""
        _hatago_returning(
            monkeypatch, {"a": "connected"}, {"a": "connected", "b": "connected"},
        )
        _llm_returning(monkeypatch, {})

        servers, _ = capability.introspect_mcp("inst", expect={"a", "b"}, timeout=30)

        assert servers == {"a": "connected", "b": "connected"}

    def test_it_gives_up_at_the_deadline(self, monkeypatch):
        """A genuinely dead child must still go red — slower, but red."""
        _hatago_returning(monkeypatch, {})
        _llm_returning(monkeypatch, {})

        servers, source = capability.introspect_mcp("inst", expect={"time"}, timeout=0)

        assert servers == {}
        assert source == HATAGO_SERVERS_URI

    def test_the_llm_backstop_still_runs_when_hatago_yields_nothing(self, monkeypatch):
        """The pre-existing fallback is regression armor, not new behaviour — it must survive."""
        _hatago_returning(monkeypatch, {})
        _llm_returning(monkeypatch, {"time": "x"})

        servers, source = capability.introspect_mcp("inst", "claude", expect={"time"}, timeout=0)

        assert servers == {"time": "x"}
        assert "claude" in source

    def test_a_stack_with_no_mcp_servers_pays_no_latency(self, monkeypatch):
        """Most stacks declare no MCP at all. Polling for nothing would tax every one of them."""
        calls = _hatago_returning(monkeypatch, {})
        _llm_returning(monkeypatch, {})

        capability.introspect_mcp("inst", expect=set(), timeout=30)

        assert calls[0] == 1, f"expected a single-shot read for an MCP-free stack, got {calls[0]}"

    def test_the_old_call_shape_still_works(self, monkeypatch):
        """`introspect_mcp(inst, harness)` is called positionally elsewhere; the new parameters are
        keyword-only with defaults so that call site is untouched."""
        _hatago_returning(monkeypatch, {"time": "connected"})
        _llm_returning(monkeypatch, {})

        assert capability.introspect_mcp("inst", "claude")[0] == {"time": "connected"}


class TestTheHatagoLogIsSurfaced:
    """`live.yml` captures no hatago log, so rv2.2's runner-side cause was inferred from code shape
    rather than observed. Whatever the cause turns out to be, the next run must show it."""

    def test_a_missing_expected_server_captures_the_log(self, monkeypatch):
        captured: list[str] = []

        def _fake_exec(_instance, script, **_kw):
            captured.append(script)
            return "hatago: child 'time' exited 1: ModuleNotFoundError\n"

        monkeypatch.setattr(capability, "_exec", _fake_exec)

        log = capability.read_hatago_log("inst")

        assert "ModuleNotFoundError" in log
        assert any(capability.HATAGO_LOG in s for s in captured), (
            f"the probe did not read {capability.HATAGO_LOG}: {captured}"
        )

    def test_an_unreadable_log_is_empty_not_an_exception(self, monkeypatch):
        """Best-effort: a teardown race must not turn a capability failure into a crash."""
        monkeypatch.setattr(capability, "_exec", lambda *_a, **_k: "")
        assert capability.read_hatago_log("inst") == ""

    def test_the_report_carries_the_log_when_present(self):
        report = capability.CapabilityReport(stack="s", hatago_log="boom")
        assert report.to_dict()["hatago_log"] == "boom"

    def test_a_green_report_does_not_carry_an_empty_log_key(self):
        """Adding a permanently-empty key to every JSON report would be noise in every green run."""
        assert "hatago_log" not in capability.CapabilityReport(stack="s").to_dict()
