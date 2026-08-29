"""Host secrets-broker lifecycle — issue #437, Group B.

Topology B (epic #388) runs one `varlock proxy` per instance on the host's loopback. This module
owns starting it, recording just enough to find it again, stopping it, and reaping the ones whose
pod is gone.

**Nothing here spawns a real broker.** A real one resolves real secrets from a real 1Password, and
the suite runs no podman either. Every test drives the seams `broker.py` exposes for exactly this
reason — `spawn`, `status`, `run` — with recorders. So these prove the right commands are issued in
the right order with the right teardown; that varlock obeys them was measured in the #388 Phase 0
spike and re-measured against 1.16.1 while writing this (SPEC revision 3), not here.

Three facts from that measurement shape the whole design, and each has a test below:

  * `proxy start` does NOT daemonize — it streams a live request log until killed. Hence a spawn
    seam rather than a run-and-read one.
  * The session id comes from `proxy status --format json`, matched on the port WE chose, never
    from `start`'s ANSI-wrapped stdout.
  * status JSON carries an `endpointToken`. It is a credential and must never be persisted.
"""

import json

import pytest

from harnessed import broker, paths

INST = "harnessed-claude-default-abcd1234"
POD = INST + "-pod"
PORT = 39443
CERTS = "/run/harnessed/certs/" + INST

# A resolved secret must never reach disk or a message. The recorders below hand the code a value
# shaped like one so an assertion can search for it by content rather than by hope.
SENTINEL = "sk-ant-oat01-THIS-IS-A-RESOLVED-SECRET-VALUE"
TOKEN_SENTINEL = "4f2a9e45-f135-4d47-8284-4f39dcf94551"  # noqa: S105 - a fixture, not a credential


@pytest.fixture(autouse=True)
def _state_home(monkeypatch, tmp_path):
    """Broker state lives under XDG_STATE_HOME; point it somewhere disposable."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def _status_entry(port=PORT, session="i0oku", pid=4242):
    """One `varlock proxy status --format json` row, shaped like the real thing.

    Carries `endpointToken` and `placeholderOverrides` because the real one does — a fixture that
    omitted them would make the "nothing leaks" tests vacuous.
    """
    return {
        "id": session,
        "uuid": "8d91df1e-d139-45e4-b751-965f038d0da2",
        "ownerPid": pid,
        "startedAt": "2026-08-29T10:57:21.059Z",
        "endpointToken": TOKEN_SENTINEL,
        "schemaFingerprint": "ba1a7bdb",
        "placeholderOverrides": {"PROBE_TOKEN": "vlk_placeholder_PROBE_TOKEN_7db6e07f"},
        "env": {
            "HTTPS_PROXY": f"http://127.0.0.1:{port}",
            "HTTP_PROXY": f"http://127.0.0.1:{port}",
            "SSL_CERT_FILE": f"{CERTS}/combined-ca.pem",
            "RESOLVED": SENTINEL,
        },
        "entryPaths": ["/proj"],
    }


class _Runner:
    """Records every varlock invocation and answers `status` from a scripted queue."""

    def __init__(self, statuses=None, spawn_pid=4242):
        self.spawned: list[list[str]] = []
        self.ran: list[list[str]] = []
        self.killed: list[int] = []
        self._statuses = list(statuses if statuses is not None else [[_status_entry()]])
        self._spawn_pid = spawn_pid

    def spawn(self, argv):
        self.spawned.append(list(argv))
        return self._spawn_pid

    def status(self):
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]

    def run(self, argv):
        self.ran.append(list(argv))
        return 0

    def kill(self, pid):
        self.killed.append(pid)


def _start(runner, inst=INST, pod=POD, schema_dir="/proj", port=PORT):
    return broker.start(
        inst, pod, schema_dir,
        spawn=runner.spawn, status=runner.status, kill=runner.kill,
        port_free=lambda _p: True, candidates=iter([port]), sleep=lambda _s: None,
    )


class TestStartRecordsJustEnoughToFindItAgain:
    """B1, B2, M4."""

    def test_start_writes_a_state_file_for_the_instance(self):
        runner = _Runner()
        session = _start(runner)
        assert broker.read(INST) is not None
        assert session.port == PORT
        assert session.session == "i0oku"
        assert session.pod == POD

    def test_the_state_file_holds_no_secret_and_no_token(self):
        # B2/M4. The status row the code reads carries a resolved value, a placeholder, AND a
        # control-plane token. None of the three may reach disk. Asserted on the raw bytes, so a
        # future field that happens to carry one fails here rather than shipping.
        runner = _Runner()
        _start(runner)
        raw = broker.state_path(INST).read_text()
        assert SENTINEL not in raw
        assert TOKEN_SENTINEL not in raw
        assert "vlk_placeholder" not in raw
        # And positively: it holds exactly the five fields needed to find and stop the session.
        assert set(json.loads(raw)) == {"instance", "pod", "session", "port", "cert_dir"}

    def test_start_invokes_varlock_proxy_start(self):
        # The command words themselves. Asserting only the flags leaves the verb unpinned, and
        # `varlock proxy status --port …` would satisfy every other assertion in this class.
        runner = _Runner()
        _start(runner)
        assert runner.spawned[0][:3] == ["varlock", "proxy", "start"]

    def test_start_passes_the_schema_dir_as_an_explicit_path(self):
        # M3. A cwd-based invocation does not survive the mise shim outside this repo.
        runner = _Runner()
        _start(runner, schema_dir="/proj")
        argv = runner.spawned[0]
        assert "--path" in argv
        assert argv[argv.index("--path") + 1] == "/proj"

    def test_start_passes_every_composed_schema_dir(self):
        # A launch composes the user-global schema and the project's. The broker must resolve the
        # same set the --env-file path does; one --path would silently drop half the secrets.
        runner = _Runner()
        broker.start(
            INST, POD, ["/global", "/proj"],
            spawn=runner.spawn, status=runner.status, kill=runner.kill,
            port_free=lambda _p: True, candidates=iter([PORT]), sleep=lambda _s: None,
        )
        argv = runner.spawned[0]
        paths_passed = [argv[i + 1] for i, a in enumerate(argv) if a == "--path"]
        assert paths_passed == ["/global", "/proj"]

    def test_start_pins_the_port_and_the_cert_dir(self):
        runner = _Runner()
        _start(runner)
        argv = runner.spawned[0]
        assert argv[argv.index("--port") + 1] == str(PORT)
        assert "--cert-dir" in argv

    def test_start_never_exposes_the_broker(self):
        # N3. Topology B deleted --expose and the data-plane token. Reintroducing either would
        # publish a secret-injecting proxy to the LAN and the tailnet.
        runner = _Runner()
        _start(runner)
        argv = runner.spawned[0]
        assert "--expose" not in argv
        assert not any(a.startswith("--expose") for a in argv)
        assert "--persist-ca" not in argv


class TestTheSessionIdComesFromStatusNotStdout:
    """M2 — `start` prints the id wrapped in ANSI styling; status JSON is the contract."""

    def test_the_session_is_matched_on_the_port_we_chose(self):
        # Two sessions are running; ours is the one on our port, not the first in the list.
        runner = _Runner(statuses=[[
            _status_entry(port=39001, session="other"),
            _status_entry(port=PORT, session="ours"),
        ]])
        assert _start(runner).session == "ours"

    def test_start_polls_until_the_session_appears(self):
        # The broker takes real time to bind. An implementation that read status once would find
        # nothing and fail every launch on a slow machine.
        runner = _Runner(statuses=[[], [], [_status_entry()]])
        assert _start(runner).session == "i0oku"


class TestAFailedStartLeavesNothingBehind:
    """B8, B9 — the orphan this whole module exists to prevent (F-b)."""

    def test_a_session_that_never_appears_raises(self):
        runner = _Runner(statuses=[[]])
        with pytest.raises(broker.BrokerError):
            _start(runner)

    def test_and_writes_no_state_file(self):
        runner = _Runner(statuses=[[]])
        with pytest.raises(broker.BrokerError):
            _start(runner)
        assert broker.read(INST) is None

    def test_and_kills_the_process_it_spawned(self):
        # Without this the failed launch leaves a live broker holding real secrets, with no state
        # file naming it — the worst orphan of the set, because reconciliation cannot see it.
        runner = _Runner(statuses=[[]])
        with pytest.raises(broker.BrokerError):
            _start(runner)
        assert runner.killed == [4242]


class TestCtrlCDuringStartupLeavesNoOrphan:
    """The worst orphan available here, and the one the timeout path already guards against.

    `spawn` uses `start_new_session=True`, so the broker does NOT get the terminal's SIGINT. If
    Ctrl-C lands while `start` is polling for the session — a window of up to `_START_TIMEOUT` —
    the process keeps running with live credentials AND no state file names it, so `reconcile` is
    structurally blind to it. It survives until the machine reboots.
    """

    def test_an_interrupt_while_polling_kills_the_spawned_broker(self):
        runner = _Runner(statuses=[[]])

        def interrupt(_seconds):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            broker.start(
                INST, POD, "/proj",
                spawn=runner.spawn, status=runner.status, kill=runner.kill,
                port_free=lambda _p: True, candidates=iter([PORT]), sleep=interrupt,
            )
        assert runner.killed == [4242]

    def test_and_writes_no_state_file(self):
        runner = _Runner(statuses=[[]])

        def interrupt(_seconds):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            broker.start(
                INST, POD, "/proj",
                spawn=runner.spawn, status=runner.status, kill=runner.kill,
                port_free=lambda _p: True, candidates=iter([PORT]), sleep=interrupt,
            )
        assert broker.read(INST) is None

    def test_a_failure_inside_status_also_kills_the_broker(self):
        """Not only Ctrl-C: any escape from the polling loop must take the process with it."""
        runner = _Runner()

        def boom():
            raise OSError("varlock vanished")

        with pytest.raises(OSError):
            broker.start(
                INST, POD, "/proj",
                spawn=runner.spawn, status=boom, kill=runner.kill,
                port_free=lambda _p: True, candidates=iter([PORT]), sleep=lambda _s: None,
            )
        assert runner.killed == [4242]


class TestStop:
    """B3, B4."""

    def test_stop_stops_the_session_and_deletes_the_state(self):
        runner = _Runner()
        _start(runner)
        broker.stop(INST, run=runner.run)
        assert runner.ran[-1] == ["varlock", "proxy", "stop", "--session", "i0oku"]
        assert broker.read(INST) is None

    def test_stop_never_stops_every_session(self):
        # `--all` would kill brokers belonging to other instances AND to the user's own terminals.
        runner = _Runner()
        _start(runner)
        broker.stop(INST, run=runner.run)
        assert not any("--all" in argv for argv in runner.ran)

    def test_stopping_an_unknown_instance_is_a_no_op(self):
        # B4. `_pod_teardown` runs on paths that may already have torn down.
        runner = _Runner()
        broker.stop("never-started", run=runner.run)
        assert runner.ran == []

    def test_stop_is_idempotent(self):
        runner = _Runner()
        _start(runner)
        broker.stop(INST, run=runner.run)
        broker.stop(INST, run=runner.run)
        assert len(runner.ran) == 1


class TestReconciliationReapsOrphans:
    """B5, B6 — the F-a backstop, for every crash the teardown path never saw."""

    def test_a_broker_whose_pod_is_gone_is_stopped_and_forgotten(self):
        runner = _Runner()
        _start(runner)
        reaped = broker.reconcile(lambda _pod: False, run=runner.run)
        assert reaped == [INST]
        assert broker.read(INST) is None
        # The WHOLE argv. A malformed flag would leave the broker running while this reported it
        # reaped — the failure mode reconciliation exists to prevent.
        assert runner.ran[-1] == ["varlock", "proxy", "stop", "--session", "i0oku"]

    def test_a_broker_whose_pod_is_alive_is_left_alone(self):
        runner = _Runner()
        _start(runner)
        assert broker.reconcile(lambda _pod: True, run=runner.run) == []
        assert broker.read(INST) is not None
        assert runner.ran == []

    def test_reconcile_asks_about_the_pod_not_the_instance(self):
        # The pod is what podman owns; the instance is our name for it. Asking the wrong one
        # reaps every broker on a runtime that names pods differently.
        runner = _Runner()
        _start(runner)
        asked: list[str] = []
        broker.reconcile(lambda pod: asked.append(pod) or True, run=runner.run)
        assert asked == [POD]

    def test_a_live_broker_does_not_stop_the_sweep_reaching_a_later_orphan(self):
        """Every other test here has ONE record, which makes `break` and `continue` identical.

        With two, an early return leaves a real orphan running: a host process holding live
        secrets, for a pod that is gone, that nothing will name again.
        """
        runner = _Runner()
        _start(runner)
        broker._write(broker.Broker(
            instance="zzz-later", pod="zzz-pod", session="other", port=39999, cert_dir="/c",
        ))
        reaped = broker.reconcile(lambda pod: pod == POD, run=runner.run)
        assert reaped == ["zzz-later"]
        assert broker.read(INST) is not None

    def test_two_corrupt_records_are_both_reaped(self):
        # The corrupt branch has its own `continue`, and with a single record `break` is
        # indistinguishable from it — the same hole as the live-broker sweep above, one branch over.
        runner = _Runner()
        for name in ("aaa-one", "zzz-two"):
            broker.state_path(name).parent.mkdir(parents=True, exist_ok=True)
            broker.state_path(name).write_text("{not json")
        assert broker.reconcile(lambda _pod: True, run=runner.run) == ["aaa-one", "zzz-two"]

    def test_a_corrupt_record_is_reported_as_reaped_by_name(self):
        runner = _Runner()
        _start(runner)
        broker.state_path(INST).write_text("{not json")
        assert broker.reconcile(lambda _pod: True, run=runner.run) == [INST]

    def test_a_corrupt_state_file_is_reaped_rather_than_crashing_the_command(self):
        # Hostile-input pass: this file is read by `harnessed list`, which must not die on it.
        runner = _Runner()
        _start(runner)
        broker.state_path(INST).write_text("{not json")
        broker.reconcile(lambda _pod: True, run=runner.run)
        # The FILE, not `read()`: a corrupt record already reads as None, so asserting that would
        # hold whether or not reconcile deleted anything. mutmut found this exact hole.
        assert not broker.state_path(INST).exists()


class TestTheGapsMutationFound:
    """Each of these closes a survivor from the mutmut run, and each is a real hole.

    They share a shape worth naming: an assertion whose expected value was already true before the
    code under test ran, or a parameter whose effect the tests never varied. Neither can fail, so
    neither was testing anything.
    """

    def test_stop_deletes_a_corrupt_record(self):
        # `read()` returns None for a corrupt file, so `stop` takes its early-return branch — and
        # must still delete the file. Otherwise a record nothing can parse becomes permanent.
        runner = _Runner()
        _start(runner)
        broker.state_path(INST).write_text("{not json")
        broker.stop(INST, run=runner.run)
        assert not broker.state_path(INST).exists()

    def test_the_recorded_cert_dir_is_the_one_passed_to_varlock(self, tmp_path):
        # #438 binds this directory into the pod. A record naming a different one — or None — sends
        # that issue at the wrong path, and nothing here would have noticed.
        certs = str(tmp_path / "certs")
        runner = _Runner()
        record = broker.start(
            INST, POD, "/proj", cert_dir=certs,
            spawn=runner.spawn, status=runner.status, kill=runner.kill,
            port_free=lambda _p: True, candidates=iter([PORT]), sleep=lambda _s: None,
        )
        argv = runner.spawned[0]
        assert record.cert_dir == certs
        assert argv[argv.index("--cert-dir") + 1] == certs

    def test_start_honours_the_port_free_predicate(self, tmp_path):
        # Previously every test passed a predicate that said yes, so `start` ignoring it entirely
        # was indistinguishable from `start` obeying it.
        runner = _Runner(statuses=[[_status_entry(port=39444)]])
        record = broker.start(
            INST, POD, "/proj", cert_dir=str(tmp_path / "c"),
            spawn=runner.spawn, status=runner.status, kill=runner.kill,
            port_free=lambda p: p != 39443, candidates=iter([39443, 39444]),
            sleep=lambda _s: None,
        )
        assert record.port == 39444

    def test_starting_again_over_an_existing_cert_dir_is_fine(self, tmp_path):
        # A relaunch of the same instance reuses the directory. `mkdir` without exist_ok raises
        # FileExistsError, which would break every launch after the first.
        certs = tmp_path / "certs"
        certs.mkdir()
        runner = _Runner()
        broker.start(
            INST, POD, "/proj", cert_dir=str(certs),
            spawn=runner.spawn, status=runner.status, kill=runner.kill,
            port_free=lambda _p: True, candidates=iter([PORT]), sleep=lambda _s: None,
        )
        assert broker.read(INST) is not None

    def test_a_row_with_no_env_is_skipped_rather_than_crashing(self):
        # Hostile input: varlock is free to add or drop fields. A row without `env` must not take
        # down a launch.
        runner = _Runner(statuses=[[{"id": "nope"}, _status_entry()]])
        assert _start(runner).session == "i0oku"


class TestPortSelection:
    """B7, F-c — `proxy start` fails outright if the port is in use, so two concurrent
    instances must never be handed the same one."""

    def test_a_taken_port_is_skipped(self):
        taken = {39443}
        chosen = broker.pick_port(
            port_free=lambda p: p not in taken, candidates=iter([39443, 39444]),
        )
        assert chosen == 39444

    def test_no_free_port_raises_rather_than_returning_a_taken_one(self):
        with pytest.raises(broker.BrokerError):
            broker.pick_port(port_free=lambda _p: False, candidates=iter([1, 2, 3]))


class TestStateLocation:
    """The convention `_attach_marker` established, so the state dir is discoverable."""

    def test_state_lives_under_the_harnessed_state_home(self):
        path = broker.state_path(INST)
        assert path.parent == paths.xdg_state_home() / "harnessed" / "brokers"
        assert path.name == INST + ".json"
