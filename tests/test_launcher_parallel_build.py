"""Parallel stack builds: `harnessed build --jobs N`.

A bare `harnessed build` rebuilds every stale (stack, harness) pair. Serially that is the sum of
every stack's build; the pairs are independent (own profile dir, own image tag), so they fan out.

What must hold under concurrency:
  * the SHARED images (base, per-harness agent) are built once, BEFORE any worker starts — they are
    the FROM parent / last layers of every derived build;
  * one stack failing does not cancel its siblings;
  * each build's log is prefixed with its own tag, so N interleaved podman logs stay readable.
"""

import threading
import time

import pytest
import typer

from harnessed import launcher
from support import patch_all
from harnessed import proc


@pytest.fixture
def quiet(monkeypatch):
    """No real podman, no real shared-image builds; reset the once-per-process guard."""
    monkeypatch.setattr(launcher, "_SHARED_IMAGES_BUILT", set())
    patch_all(monkeypatch, "_runtime", lambda: "podman")


class TestBuildSharedOnce:
    def test_builds_once_and_serializes_concurrent_callers(self, quiet):
        """The lock is held ACROSS the build, not just the set check.

        A claim-then-release guard would let a second worker sail past while the first is still
        building, and go on to build its derived image FROM a base that does not exist yet.
        """
        concurrent = 0
        peak = 0
        calls = 0
        lock = threading.Lock()

        def slow_build():
            nonlocal concurrent, peak, calls
            with lock:
                calls += 1
                concurrent += 1
                peak = max(peak, concurrent)
            time.sleep(0.05)
            with lock:
                concurrent -= 1

        threads = [
            threading.Thread(target=lambda: launcher._build_shared_once("harnessed-base:latest", slow_build))
            for _ in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert calls == 1, "shared image built more than once"
        assert peak == 1, "two builders were inside the shared-image build at once"


class TestReconcileParallel:
    @pytest.fixture
    def harness_stubs(self, monkeypatch, quiet):
        """Record shared-image builds and per-pair builds, with real threading."""
        events: list[str] = []
        lock = threading.Lock()

        def record(name):
            with lock:
                events.append(name)

        monkeypatch.setattr(launcher, "_build_base_image", lambda rt: record("base"))
        monkeypatch.setattr(launcher, "_build_agent_image", lambda rt, h: record(f"agent:{h}"))
        return events

    def _stale(self, monkeypatch, pairs):
        monkeypatch.setattr(
            launcher, "_stale_pairs",
            lambda rt, root, *, strict: [(s, h, "no built image") for s, h in pairs],
        )

    def test_shared_images_built_before_any_stack(self, monkeypatch, harness_stubs):
        events = harness_stubs
        self._stale(monkeypatch, [("a", "claude"), ("b", "omp"), ("c", "claude")])

        def fake_build_stack(rt, stack, harness, root=None, **kw):
            events.append(f"stack:{stack}")

        monkeypatch.setattr(launcher, "_build_stack", fake_build_stack)
        launcher._reconcile_stacks("podman", None, strict=True, jobs=3)

        # Base first, then one agent image per DISTINCT harness, then the stacks — never a stack
        # before its prerequisites.
        first_stack = next(i for i, e in enumerate(events) if e.startswith("stack:"))
        prereqs = events[:first_stack]
        assert prereqs[0] == "base"
        assert sorted(prereqs[1:]) == ["agent:claude", "agent:omp"]
        assert sorted(e for e in events if e.startswith("stack:")) == ["stack:a", "stack:b", "stack:c"]

    def test_stacks_actually_run_concurrently(self, monkeypatch, harness_stubs):
        concurrent = 0
        peak = 0
        lock = threading.Lock()
        self._stale(monkeypatch, [("a", "claude"), ("b", "claude"), ("c", "claude")])

        def slow_stack(rt, stack, harness, root=None, **kw):
            nonlocal concurrent, peak
            with lock:
                concurrent += 1
                peak = max(peak, concurrent)
            time.sleep(0.05)
            with lock:
                concurrent -= 1

        monkeypatch.setattr(launcher, "_build_stack", slow_stack)
        launcher._reconcile_stacks("podman", None, strict=True, jobs=3)
        assert peak > 1, "stacks built serially despite --jobs 3"

    def test_one_failing_stack_does_not_cancel_the_others(self, monkeypatch, harness_stubs):
        built: list[str] = []
        lock = threading.Lock()
        self._stale(monkeypatch, [("good1", "claude"), ("bad", "claude"), ("good2", "claude")])

        def flaky(rt, stack, harness, root=None, **kw):
            if stack == "bad":
                raise RuntimeError("recipe blew up")
            with lock:
                built.append(stack)

        monkeypatch.setattr(launcher, "_build_stack", flaky)
        with pytest.raises(typer.Exit):  # the run still reports a non-zero exit
            launcher._reconcile_stacks("podman", None, strict=True, jobs=3)

        # The siblings still built: a broken stack costs you that stack, not the whole build.
        assert sorted(built) == ["good1", "good2"]

    def test_jobs_1_is_the_serial_path(self, monkeypatch, harness_stubs):
        concurrent = 0
        peak = 0
        lock = threading.Lock()
        self._stale(monkeypatch, [("a", "claude"), ("b", "claude")])

        def slow_stack(rt, stack, harness, root=None, **kw):
            nonlocal concurrent, peak
            with lock:
                concurrent += 1
                peak = max(peak, concurrent)
            time.sleep(0.02)
            with lock:
                concurrent -= 1

        monkeypatch.setattr(launcher, "_build_stack", slow_stack)
        launcher._reconcile_stacks("podman", None, strict=True, jobs=1)
        assert peak == 1


class TestBuildTag:
    def test_untagged_output_is_unprefixed(self, capsys):
        launcher._say("hello")
        assert proc._BUILD_TAG.get() is None
        assert "│" not in capsys.readouterr().out

    def test_tagged_output_carries_label_and_colour(self, capsys):
        token = proc._BUILD_TAG.set(("mystack(omp)", "cyan"))
        try:
            launcher._say("hello")
        finally:
            proc._BUILD_TAG.reset(token)
        out = capsys.readouterr().out
        assert "mystack(omp)" in out
        assert "│" in out
        assert "hello" in out

    def test_tagged_run_streams_each_line_prefixed(self, capsys):
        """`podman build` output must land in its OWN lane, or N concurrent logs are unreadable."""
        token = proc._BUILD_TAG.set(("s(claude)", "green"))
        try:
            launcher._run(["printf", "one\\ntwo\\n"])
        finally:
            proc._BUILD_TAG.reset(token)
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 2
        assert all("s(claude)" in ln and "│" in ln for ln in lines)
        assert "one" in lines[0] and "two" in lines[1]

    def test_tagged_run_raises_on_failure(self):
        token = proc._BUILD_TAG.set(("s(claude)", "green"))
        try:
            with pytest.raises(Exception):
                launcher._run(["sh", "-c", "exit 3"])
        finally:
            proc._BUILD_TAG.reset(token)

    def test_capturing_callers_are_not_hijacked(self):
        """A caller that captures output wants the bytes back, not printed — tag or no tag."""
        token = proc._BUILD_TAG.set(("s(claude)", "green"))
        try:
            result = launcher._run(["printf", "payload"], capture_output=True, text=True)
        finally:
            proc._BUILD_TAG.reset(token)
        assert result.stdout == "payload"
