"""Deadlines on the launcher's subprocess calls, and the seam that carries them (bd harnessed-1ao).

Three properties, and they are not the same property:

1. `_bounded` turns a hang into a *failure* — it kills the child and returns a non-zero
   CompletedProcess rather than raising, so every call site's existing "non-zero means it did not
   work" branch handles a wedged podman exactly as it handles a broken one.
2. `_run_tagged` accepts `timeout=`. It builds a `Popen`, which has no such parameter, so before
   this bead `_run(cmd, timeout=…)` worked or raised TypeError depending on whether a parallel
   build tag happened to be set — the seam defect the bead names.
3. A function that advertises a deadline in its own output honours it. Bounding the probe inside
   `for _ in range(timeout)` without making the loop deadline-driven would push worst-case elapsed
   to `timeout * (probe + 1)` while the message still claims `timeout` — a fix that reads correct
   and lies at runtime.

The suite runs no real podman (CLAUDE.md), so these use sleeping stand-in processes: they prove the
mechanism fires, degrades and stays honest, never that 30s/120s are the right numbers for podman
under load.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest
import typer

from hypothesis import given, settings
from hypothesis.strategies import floats

from harnessed import launcher, proc
from harnessed.schema import Recipe, ServiceDef, SetupSpec
from support import patch_all


def _sleeper(seconds: float) -> list[str]:
    """A child that outlives any deadline we give it."""
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _sleep_then_write(seconds: float, path) -> list[str]:
    """A child that proves whether it was really killed: the file appears only if it ran to term."""
    return [
        sys.executable,
        "-c",
        f"import time; time.sleep({seconds}); open({str(path)!r}, 'w').write('survived')",
    ]


class _Recorder:
    """Stands in for the shared console so a test can read what was printed."""

    def __init__(self):
        self.lines: list[str] = []

    def print(self, *args, **kwargs):
        self.lines.append(" ".join(str(a) for a in args))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def err(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(proc, "_err", rec)
    monkeypatch.setattr(launcher, "_err", rec)
    return rec


class TestBoundedDegradesInsteadOfHanging:
    """`_bounded` is the shape ~30 podman call sites move to."""

    def test_a_hung_command_returns_the_timeout_code_instead_of_blocking(self, err):
        res = proc._bounded(_sleeper(30), timeout=0.3, capture_output=True, text=True)
        assert res.returncode == proc._TIMEOUT_RC

    def test_it_returns_within_the_deadline_not_when_the_child_would_finish(self, err):
        start = time.monotonic()
        proc._bounded(_sleeper(30), timeout=0.3, capture_output=True, text=True)
        assert time.monotonic() - start < 5, "the deadline did not actually cut the call short"

    @pytest.mark.parametrize(
        "kwarg", [{"text": True}, {"encoding": "utf-8"}, {"universal_newlines": True}]
    )
    def test_every_way_of_asking_for_str_gets_str_back(self, err, kwarg):
        """Callers do `res.stdout.strip()` and compare against str. `text=` is the common spelling
        but `encoding=` and `universal_newlines=` mean the same thing to `subprocess`, and handing
        one of those callers bytes turns the degradation path into a silently wrong comparison."""
        res = proc._bounded(_sleeper(30), timeout=0.3, capture_output=True, **kwarg)
        assert res.stdout == "" and res.stderr == ""

    def test_the_result_names_the_command_that_was_run(self, err):
        """`CompletedProcess.args` is part of the contract callers and tracebacks read."""
        cmd = _sleeper(30)
        assert proc._bounded(cmd, timeout=0.3, capture_output=True).args == cmd

    def test_byte_mode_gets_empty_bytes_output(self, err):
        """`_wait_service_healthy` does `result.stdout.decode(...)` on the last probe — a str there
        raises AttributeError and turns a service timeout into a traceback."""
        res = proc._bounded(_sleeper(30), timeout=0.3, capture_output=True)
        assert res.stdout == b"" and res.stderr == b""
        res.stdout.decode(errors="replace")  # must not raise

    def test_the_child_is_killed_not_merely_abandoned(self, tmp_path, err):
        """An abandoned child keeps holding whatever it holds. Prove death behaviourally: the file
        it writes on completion must never appear, even well after it would have."""
        marker = tmp_path / "survived.txt"
        proc._bounded(_sleep_then_write(1.0, marker), timeout=0.2, capture_output=True)
        time.sleep(1.6)
        assert not marker.exists(), "the timed-out child ran to completion — it was never killed"

    def test_a_command_that_finishes_in_time_passes_through_untouched(self, err):
        res = proc._bounded(
            [sys.executable, "-c", "print('hello')"], timeout=30, capture_output=True, text=True
        )
        assert res.returncode == 0
        assert res.stdout.strip() == "hello"
        assert err.text == "", "a successful command must print no timeout warning"

    def test_a_genuine_nonzero_exit_keeps_its_own_output(self, err):
        """Only a real timeout produces the blanked result. A command that merely fails keeps its
        code and its diagnostics — blanking those would destroy the error the user needs."""
        res = proc._bounded(
            [sys.executable, "-c", "import sys; print('detail'); sys.exit(3)"],
            timeout=30, capture_output=True, text=True,
        )
        assert res.returncode == 3
        assert res.stdout.strip() == "detail"

    def test_a_hang_is_never_silent(self, err):
        proc._bounded(_sleeper(30), timeout=0.3, capture_output=True)
        assert "warning:" in err.text.lower(), (
            "a wedged podman must announce itself — `warning:` is also what the console's warning "
            "counter matches, so _acknowledge_warnings surfaces it before the TTY handoff"
        )

    def test_the_warning_says_which_command_hung_and_for_how_long(self, err):
        """'something timed out' sends the user hunting. Naming the command and the deadline is
        the difference between an actionable warning and a note that something went wrong."""
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        proc._bounded(cmd, timeout=0.3, capture_output=True)
        # Rendered the way the user would type it, so the warning can be copied into a shell to
        # reproduce — not as a Python list repr.
        assert " ".join(cmd) in err.text, "the warning does not say WHAT hung"
        assert "0.3" in err.text, "the warning does not say what deadline was exceeded"

    def test_warn_false_stays_quiet_for_poll_loops(self, err):
        """A loop that probes every second would otherwise print one warning per iteration, burying
        the single actionable error the loop prints at the end."""
        proc._bounded(_sleeper(30), timeout=0.3, capture_output=True, warn=False)
        assert err.text == ""


class TestRunTaggedAcceptsATimeout:
    """The seam defect bd harnessed-1ao names."""

    def test_it_raises_timeoutexpired_when_the_deadline_passes(self):
        """Matching `subprocess.run`, so the two shapes stay interchangeable for callers."""
        cmd = _sleeper(30)
        with pytest.raises(subprocess.TimeoutExpired) as exc:
            proc._run_tagged(cmd, timeout=0.3)
        # A caller that catches this and logs `exc.cmd` must learn which build hung — during a
        # parallel build that is the only thing distinguishing one wedged stack from another. The
        # deadline rides along because TimeoutExpired's own message quotes it.
        assert exc.value.cmd == cmd
        assert exc.value.timeout == 0.3

    def test_it_returns_within_the_deadline(self):
        start = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            proc._run_tagged(_sleeper(30), timeout=0.3)
        assert time.monotonic() - start < 5

    def test_the_child_is_killed(self, tmp_path):
        marker = tmp_path / "survived.txt"
        with pytest.raises(subprocess.TimeoutExpired):
            proc._run_tagged(_sleep_then_write(1.0, marker), timeout=0.2)
        time.sleep(1.6)
        assert not marker.exists()

    def test_a_command_inside_the_deadline_is_unaffected(self):
        cmd = [sys.executable, "-c", "print('ok')"]
        res = proc._run_tagged(cmd, timeout=30)
        assert res.returncode == 0
        assert res.args == cmd

    def test_a_failing_command_still_raises_by_default(self):
        """Adding `timeout` to this signature must not disturb `check`: callers rely on a non-zero
        build exit aborting rather than being returned quietly."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(2)"]
        with pytest.raises(subprocess.CalledProcessError) as exc:
            proc._run_tagged(cmd, timeout=30)
        assert exc.value.cmd == cmd and exc.value.returncode == 2

    def test_check_false_returns_the_failure_instead_of_raising(self):
        res = proc._run_tagged(
            [sys.executable, "-c", "import sys; sys.exit(2)"], check=False, timeout=30
        )
        assert res.returncode == 2

    def test_the_watchdog_does_not_fire_after_a_fast_success(self):
        """A watchdog left armed kills whatever reuses the pid, and a stray raise would turn a
        successful build into a spurious timeout."""
        for _ in range(3):
            assert proc._run_tagged([sys.executable, "-c", "pass"], timeout=5).returncode == 0
        time.sleep(0.3)

    def test_popen_never_receives_a_timeout_kwarg(self, monkeypatch):
        """`Popen` has no `timeout` parameter — forwarding it is the TypeError this bead fixes."""
        seen: dict = {}

        class _FakePopen:
            def __init__(self, cmd, **kwargs):
                seen.update(kwargs)
                self.stdout = iter(["line\n"])

            def wait(self, *a, **k):
                return 0

            def kill(self):
                pass

        monkeypatch.setattr(proc.subprocess, "Popen", _FakePopen)
        proc._run_tagged(["anything"], timeout=5)
        assert "timeout" not in seen

    def test_without_a_timeout_behaviour_is_unchanged(self, monkeypatch):
        seen: dict = {}

        class _FakePopen:
            def __init__(self, cmd, **kwargs):
                seen.update(kwargs)
                self.stdout = iter(["line\n"])

            def wait(self, *a, **k):
                return 0

            def kill(self):
                pass

        monkeypatch.setattr(proc.subprocess, "Popen", _FakePopen)
        assert proc._run_tagged(["anything"]).returncode == 0
        assert "timeout" not in seen


class TestRunPropagatesTheTimeout:
    """`_run` dispatches to two different shapes; the kwarg has to survive both."""

    def test_untagged_path_reaches_subprocess_run(self, monkeypatch):
        seen: dict = {}

        def fake_run(cmd, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(proc.subprocess, "run", fake_run)
        proc._run(["x"], timeout=7)
        assert seen.get("timeout") == 7

    def test_tagged_path_reaches_run_tagged(self, monkeypatch):
        seen: dict = {}

        def fake_tagged(cmd, check=True, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(proc, "_run_tagged", fake_tagged)
        token = proc._BUILD_TAG.set(("stack(x)", "cyan"))
        try:
            proc._run(["x"], timeout=7)
        finally:
            proc._BUILD_TAG.reset(token)
        assert seen.get("timeout") == 7


class TestAdvertisedDeadlinesAreHonest:
    """A loop that prints 'never came up after {timeout}s' must return in about that long — whether
    its probes answer, fail, or hang."""

    @staticmethod
    def _hanging_probe(monkeypatch, calls):
        """Stand in for a wedged podman: the probe burns exactly the deadline it was handed, then
        reports the timeout code, which is what `_bounded` does to a hung child."""

        def probe(cmd, *, timeout, warn=True, **kwargs):
            calls.append(timeout)
            time.sleep(timeout)
            return subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, b"", b"")

        monkeypatch.setattr(launcher, "_bounded", probe)

    def test_wait_hatago_respects_its_own_timeout(self, monkeypatch, err):
        calls: list[float] = []
        self._hanging_probe(monkeypatch, calls)
        start = time.monotonic()
        assert launcher._wait_hatago("podman", "inst", port=1234, timeout=2) is False
        elapsed = time.monotonic() - start
        assert elapsed < 5, (
            f"advertised 2s, took {elapsed:.1f}s — a per-probe deadline without a loop deadline "
            "multiplies the wait by the probe length"
        )

    def test_wait_hatago_never_probes_past_its_deadline(self, monkeypatch, err):
        """The clamp that makes the above true: a probe must not be handed more time than the loop
        has left, or one probe alone overruns the promise."""
        calls: list[float] = []
        self._hanging_probe(monkeypatch, calls)
        launcher._wait_hatago("podman", "inst", port=1234, timeout=2)
        assert calls, "no probe ran at all"
        assert sum(calls) <= 2 + 1.5, f"probes were granted {sum(calls):.1f}s inside a 2s budget"

    def test_wait_hatago_still_succeeds_immediately_on_a_live_port(self, monkeypatch, err):
        """The fast path is the one that runs on every healthy launch; it must not have grown a
        deadline's worth of latency."""
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b""),
        )
        start = time.monotonic()
        assert launcher._wait_hatago("podman", "inst", port=1234, timeout=30) is True
        assert time.monotonic() - start < 2

    def test_wait_service_healthy_respects_its_own_timeout(self, monkeypatch, err):
        calls: list[float] = []
        self._hanging_probe(monkeypatch, calls)
        monkeypatch.setattr(launcher, "_service_container_status", lambda *a, **k: "running")

        # A real ServiceDef, not a stand-in object: `socket` makes it socket-only, which skips the
        # TCP pre-probe and lands directly in the healthcheck loop under test.
        svc = ServiceDef(
            name="db", image="i", scope="project", socket="/run/db.sock", healthcheck="true"
        )

        start = time.monotonic()
        with pytest.raises(typer.Exit):
            launcher._wait_service_healthy("podman", "cname", svc, timeout=2)
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"advertised 2s, took {elapsed:.1f}s"


class TestDeadlineHonestyHoldsForAnyTimeout:
    """The scenarios above pin one timeout value. The arithmetic — a clamp, a subtraction and a
    loop guard — is where an off-by-one hides, so sample it instead of trusting one example."""

    @settings(max_examples=6, deadline=None)
    @given(budget=floats(min_value=0.1, max_value=1.0))
    def test_wait_hatago_returns_within_its_budget_for_any_budget(self, budget):
        # A per-example MonkeyPatch context, not the fixture: a function-scoped fixture is set up
        # once and reused across every generated input, which hypothesis rightly flags.
        def probe(cmd, *, timeout, warn=True, **kwargs):
            time.sleep(timeout)  # a wedged podman: burns exactly the deadline it was handed
            return subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, b"", b"")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(launcher._out, "print", lambda *a, **k: None)
            mp.setattr(launcher, "_bounded", probe)
            start = time.monotonic()
            assert launcher._wait_hatago("podman", "i", port=1, timeout=budget) is False
            elapsed = time.monotonic() - start
        # One probe may be in flight when the deadline passes, so the bound is budget + one probe,
        # never budget * probes. The slack absorbs scheduling, not a second full poll cycle.
        assert elapsed <= budget + 1.5, f"budget {budget:.2f}s overran to {elapsed:.2f}s"


class TestATimeoutNeverMasksTheRealFailure:
    def test_teardown_timeout_does_not_swallow_the_bodys_exception(self, monkeypatch, err):
        """`_with_image_container` removes its throwaway container in a `finally`. If that removal
        could raise on timeout it would replace whatever went wrong inside — the caller would see a
        TimeoutExpired about `rm` instead of the real fault."""
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, "cid123", ""),
        )

        def boom(_cid):
            raise ValueError("the real failure")

        with pytest.raises(ValueError, match="the real failure"):
            launcher._with_image_container("podman", "img", boom)


class TestWedgedPodmanDoesNotCrashTeardown:
    """Teardown runs when something has ALREADY gone wrong. Turning a hung `podman rm` into a
    traceback there replaces the fault the user needs to see with one about the cleanup — so these
    paths must absorb a timeout and carry on. They also check the call shape: the podman-driving
    branches are never executed by this suite (no real podman, per CLAUDE.md), so a mis-typed
    kwarg would otherwise reach a user before it reached a test."""

    @pytest.fixture
    def wedged(self, monkeypatch):
        """Every `_bounded` reports a killed-on-deadline child, and records what it was asked."""
        seen: list[dict] = []

        def stub(cmd, **kw):
            seen.append({"cmd": cmd, **kw})
            return subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, b"", b"")

        monkeypatch.setattr(launcher, "_bounded", stub)
        return seen

    @pytest.mark.parametrize("uses_pods", [True, False])
    def test_pod_teardown_survives_a_hung_runtime(self, monkeypatch, wedged, uses_pods):
        monkeypatch.setattr(launcher, "_rt_uses_pods", lambda _rt: uses_pods)
        launcher._pod_teardown("podman", "inst", "pod")  # must not raise
        assert wedged and wedged[0]["timeout"], "teardown ran without a deadline"

    def test_best_effort_ca_install_survives_a_hung_exec(self, monkeypatch, wedged, tmp_path):
        ca = tmp_path / "corp.crt"
        ca.write_text("x")
        monkeypatch.setattr(launcher.paths, "corp_proxy_ca_path", lambda: ca)
        launcher._install_corp_proxy_ca_in_container("podman", "c", best_effort=True)
        assert wedged and wedged[0]["timeout"]


class TestAnUnansweredQueryIsNeverReportedAsEmpty:
    """"podman says there are none" and "podman never replied" are the same empty stdout. Every
    listing command here turned that into a cheerful "No instances found" and exit 0 — so a wrapping
    script reads success and a human reads a cleanup that never happened. Adversarial review found
    this on `stop`/`rm`/`prune`/`volume-gc`; `rescan` is the same shape and the worst case, since a
    systemd timer fires it and a false "nothing to scan" silently skips the nightly CVE scan."""

    @pytest.fixture(autouse=True)
    def _wedged_listing(self, monkeypatch):
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, "", ""),
        )

    def test_stop_aborts_rather_than_claiming_no_instances(self, err):
        with pytest.raises(typer.Exit) as exc:
            launcher.stop("somestack")
        assert exc.value.exit_code == 1
        assert "No running instances" not in err.text

    def test_rm_aborts_rather_than_claiming_no_instances(self, err):
        with pytest.raises(typer.Exit) as exc:
            launcher.remove("somestack")
        assert exc.value.exit_code == 1
        assert "No instances found" not in err.text

    def test_rescan_aborts_rather_than_silently_scanning_nothing(self, err):
        """The nightly security scan must not report success having scanned zero images."""
        with pytest.raises(typer.Exit) as exc:
            launcher.rescan(None)
        assert exc.value.exit_code == 1
        assert "No harnessed-labelled images" not in err.text


class TestTheEgressFirewallFailsClosed:
    """The script installs a default-DROP policy, so "did not run" means NO firewall, not a weaker
    one. This return value was discarded, which only survived because an unbounded hang stopped the
    launch by never finishing — adding a deadline would otherwise have converted a wedged runtime
    into a silently unconfined agent."""

    def test_a_timed_out_firewall_aborts_the_launch(self, monkeypatch, err):
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, proc._TIMEOUT_RC, b"", b""),
        )
        with pytest.raises(typer.Exit) as exc:
            launcher._apply_firewall("podman", "inst", ["example.com"])
        assert exc.value.exit_code == 1
        assert "unrestricted" in err.text.lower()

    def test_a_failing_firewall_also_aborts(self, monkeypatch, err):
        """Same invariant, other cause. Guarding only the deadline would leave the identical
        silently-unconfined agent one exit code away."""
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"nft: permission denied"),
        )
        with pytest.raises(typer.Exit):
            launcher._apply_firewall("podman", "inst", [])

    def test_a_successful_firewall_is_silent(self, monkeypatch, err):
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b""),
        )
        launcher._apply_firewall("podman", "inst", [])
        assert err.text == ""

    def test_the_documented_opt_out_still_skips_it(self, monkeypatch, err):
        """The error tells the user to set NO_FIREWALL=true, so that escape hatch must work — or
        failing closed becomes a wall rather than a gate."""
        monkeypatch.setenv("NO_FIREWALL", "true")
        called = []
        monkeypatch.setattr(launcher, "_bounded", lambda cmd, **kw: called.append(cmd))
        launcher._apply_firewall("podman", "inst", [])
        assert called == [] and err.text == ""


class TestSetupConditionsCannotHangALaunch:
    """Catalog-authored shell, run host-side on the launch critical path, every launch."""

    @pytest.fixture(autouse=True)
    def _state(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        # A conditional notice builds the folder-env contract, which resolves the stack's sockets,
        # and these use a synthetic stack name with no manifest — same stub as
        # tests/test_setup_notice.py. The subject here is the deadline, not socket wiring.
        patch_all(monkeypatch, "svc_socket_env", lambda *a, **k: {})
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {})
        self.project = tmp_path

    @staticmethod
    def _recipe(name, condition):
        return Recipe(
            name=name,
            setup=SetupSpec(summary=f"do {name}", reference="https://example/x", condition=condition),
        )

    def test_a_hanging_condition_shows_the_notice_rather_than_swallowing_it(self, monkeypatch, err):
        """Polarity here is 'non-zero == already satisfied == suppress'. Letting a timeout fall into
        that branch would silently drop a setup step the user still has to perform, and the whole
        point of the notice is that nothing else tells them. A redundant notice is recoverable; a
        missing one is not.

        Runs the REAL `_bounded` against a real hanging shell rather than stubbing it, so this
        covers the whole path — deadline, kill, warning, and the polarity decision on top.
        """
        monkeypatch.setattr(launcher, "_SETUP_CONDITION_TIMEOUT", 0.3)
        start = time.monotonic()
        shown = launcher._collect_setup_notices(
            [self._recipe("needs-setup", "sleep 999")], self.project, "s", "claude"
        )
        assert time.monotonic() - start < 5, "a hanging condition blocked the launch"
        assert [r.name for r in shown] == ["needs-setup"]
        assert "warning:" in err.text.lower(), "a condition that never answered must say so"
        # Named by RECIPE, never by command text: the condition is catalog-authored shell the schema
        # does not restrict, so it may resolve a secret to do its job. Printing the argv — which is
        # `_bounded`'s default — would put that secret on stderr and into any CI log. Found by the
        # security lens of adversarial review.
        assert "needs-setup" in err.text
        assert "sleep 999" not in err.text, "the warning echoed the condition's shell back out"

    def test_a_prompt_nonzero_condition_is_still_suppressed(self, monkeypatch, err):
        """The existing polarity is unchanged for every condition that actually answers."""
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b""),
        )
        shown = launcher._collect_setup_notices(
            [self._recipe("already-done", "false")], self.project, "s", "claude"
        )
        assert shown == []

    def test_a_satisfied_condition_still_shows(self, monkeypatch, err):
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b""),
        )
        shown = launcher._collect_setup_notices(
            [self._recipe("needed", "true")], self.project, "s", "claude"
        )
        assert [r.name for r in shown] == ["needed"]

    def test_the_condition_is_given_a_deadline(self, monkeypatch, err):
        seen: dict = {}

        def spy(cmd, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(launcher, "_bounded", spy)
        launcher._collect_setup_notices(
            [self._recipe("x", "true")], self.project, "s", "claude"
        )
        assert seen.get("timeout"), "a catalog condition must not be able to block a launch forever"
