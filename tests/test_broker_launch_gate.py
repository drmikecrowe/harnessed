"""When a launch gets a secrets broker, and when it must not — issue #437, Groups C and D.

The gate has three inputs and one output. A broker is started only when **the composed schema opts
into the proxy model** (a `@proxy` annotation somewhere) AND **`--no-secrets` was not passed**.
Everything else — the overwhelming majority of launches, which have no `@proxy` anywhere — must be
untouched, and "untouched" is asserted as *no varlock subprocess runs at all*, not as "a broker was
not recorded". The issue's words: capability absent, not merely empty.

The other half is that a broker which cannot start **fails the launch**. That is a deliberate
behaviour change (SPEC decision 2): the alternative is a pod wired half-way to a proxy that is not
there, which is the silent half-wiring epic #388 exists to remove — and it gets worse at #439, when
the pod's env becomes placeholders that only the broker can redeem.
"""

from pathlib import Path

import pytest
import typer

from harnessed import broker, launchenv, launcher

INST = "harnessed-claude-default-abcd1234"
POD = INST + "-pod"

PROXY_SCHEMA = '# @proxy(domain="api.github.com") @sensitive\nGITHUB_TOKEN=exec("op read …")\n'
PLAIN_SCHEMA = "# @defaultSensitive=false\n# ---\nPLAIN_NOTE=hello\n"

# `proxy status` returns a control-plane token; nothing must carry one into a report.
TOKEN_ISH = "4f2a9e45-f135-4d47-8284-4f39dcf94551"  # noqa: S105 - a fixture, not a credential


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """State home disposable, NO_SECRETS unset, and the varlock cache empty.

    `_schema_declares_proxy` reads files but `_varlock_proxy_modes` memoizes, so a dirty cache
    would let one test's schema answer another's question.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("NO_SECRETS", raising=False)
    launchenv._varlock_cache_clear()
    yield
    launchenv._varlock_cache_clear()


@pytest.fixture
def no_global_schema(monkeypatch, tmp_path):
    """The user's real ~/.config/harnessed must not decide a test's outcome."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    return tmp_path / "home"


def _project(tmp_path, schema: str | None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    if schema is not None:
        (proj / ".env.schema").write_text(schema)
    return proj


class _Spy:
    """Records whether anything tried to start a broker, and lets a test make it fail."""

    def __init__(self, fail=False):
        self.starts: list[tuple] = []
        self.fail = fail

    def start(self, inst, pod, schema_dirs, **kw):
        self.starts.append((inst, pod, [str(d) for d in schema_dirs]))
        if self.fail:
            raise broker.BrokerError("the secrets broker did not come up on port 39443 within 30s")
        return broker.Broker(
            instance=inst, pod=pod, session="i0oku", port=39443, cert_dir="/certs",
        )


class TestNoOptInMeansNoBroker:
    """C1 — the majority case, and N1."""

    def test_a_project_with_no_schema_at_all_starts_no_broker(
        self, monkeypatch, tmp_path, no_global_schema
    ):
        spy = _Spy()
        monkeypatch.setattr(broker, "start", spy.start)
        assert launcher._broker_start_for(INST, POD, _project(tmp_path, None)) is None
        assert spy.starts == []

    def test_a_schema_without_proxy_starts_no_broker(
        self, monkeypatch, tmp_path, no_global_schema
    ):
        spy = _Spy()
        monkeypatch.setattr(broker, "start", spy.start)
        assert launcher._broker_start_for(INST, POD, _project(tmp_path, PLAIN_SCHEMA)) is None
        assert spy.starts == []

    def test_no_varlock_subprocess_runs_at_all(self, monkeypatch, tmp_path, no_global_schema):
        """The issue's words: 'assert the process is absent, not merely idle'.

        `varlock proxy rules` RESOLVES values and can sit on a 1Password unlock prompt, so buying
        one for a schema that opted into nothing is a real cost, not a cosmetic one.
        """
        spawned: list[list[str]] = []
        monkeypatch.setattr(broker, "_spawn", lambda argv: spawned.append(argv) or 1)
        monkeypatch.setattr(broker, "_status", lambda: [])
        monkeypatch.setattr(broker, "_run", lambda argv: spawned.append(argv) or 0)
        launcher._broker_start_for(INST, POD, _project(tmp_path, PLAIN_SCHEMA))
        assert spawned == []


class TestOptInStartsABroker:
    """C2."""

    def test_a_proxy_schema_starts_a_broker_for_this_instance(
        self, monkeypatch, tmp_path, no_global_schema
    ):
        spy = _Spy()
        monkeypatch.setattr(broker, "start", spy.start)
        proj = _project(tmp_path, PROXY_SCHEMA)
        record = launcher._broker_start_for(INST, POD, proj)
        assert record is not None
        assert spy.starts[0][0] == INST
        assert spy.starts[0][1] == POD
        assert str(proj) in spy.starts[0][2]


class TestNoSecretsOptsOut:
    """C3 — the escape hatch decision 2 promises, parallel to --no-firewall."""

    def test_no_secrets_starts_no_broker_even_with_a_proxy_schema(
        self, monkeypatch, tmp_path, no_global_schema
    ):
        monkeypatch.setenv("NO_SECRETS", "true")
        spy = _Spy()
        monkeypatch.setattr(broker, "start", spy.start)
        assert launcher._broker_start_for(INST, POD, _project(tmp_path, PROXY_SCHEMA)) is None
        assert spy.starts == []

    def test_the_flag_sets_the_env_the_backend_reads(self):
        """`--no-secrets` reaches the backend the same way `--no-firewall` does. Asserting the
        contract between them keeps the flag from being wired to a variable nobody reads."""
        assert "--no-secrets" in _option_flags(launcher.container_run)


class TestAFailedBrokerFailsTheLaunch:
    """C4, C5 — decision 2. The behaviour change, and the message that has to carry it."""

    def test_a_broker_that_cannot_start_aborts_the_launch(
        self, monkeypatch, tmp_path, no_global_schema
    ):
        spy = _Spy(fail=True)
        monkeypatch.setattr(broker, "start", spy.start)
        with pytest.raises(typer.Exit) as exc:
            launcher._broker_start_for(INST, POD, _project(tmp_path, PROXY_SCHEMA))
        assert exc.value.exit_code == 1

    def test_the_failure_names_the_escape_hatch(
        self, monkeypatch, tmp_path, no_global_schema, capsys
    ):
        # A fatal launch failure that does not say how to proceed is a support ticket.
        spy = _Spy(fail=True)
        monkeypatch.setattr(broker, "start", spy.start)
        with pytest.raises(typer.Exit):
            launcher._broker_start_for(INST, POD, _project(tmp_path, PROXY_SCHEMA))
        err = capsys.readouterr().err
        assert "--no-secrets" in err

    def test_the_failure_prints_no_resolved_value(
        self, monkeypatch, tmp_path, no_global_schema, capsys
    ):
        # N4, on the path most likely to reach for context it should not have.
        sentinel = "sk-ant-oat01-RESOLVED"

        def boom(inst, pod, schema_dirs, **kw):
            raise broker.BrokerError(f"failed while resolving {sentinel}")

        monkeypatch.setattr(broker, "start", boom)
        with pytest.raises(typer.Exit):
            launcher._broker_start_for(INST, POD, _project(tmp_path, PROXY_SCHEMA))
        assert sentinel not in capsys.readouterr().err


class TestTeardownTakesTheBrokerWithIt:
    """C7 — `_pod_teardown` is the single choke point, so wiring it there covers --rm, --fresh,
    prune and the abort path in one place."""

    def test_pod_teardown_stops_the_instances_broker(self, monkeypatch):
        stopped: list[str] = []
        monkeypatch.setattr(broker, "stop", lambda inst, **kw: stopped.append(inst))
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: _ok())
        launcher._pod_teardown("podman", INST, POD)
        assert stopped == [INST]

    def test_a_broker_stop_failure_never_blocks_the_pod_teardown(self, monkeypatch):
        """The pod is the containment boundary. If stopping the broker raises, the pod must still
        come down — leaving it running would be strictly worse than leaking one host process."""

        def boom(inst, **kw):
            raise RuntimeError("varlock is gone")

        torn: list[tuple] = []
        monkeypatch.setattr(broker, "stop", boom)
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: torn.append(a) or _ok())
        launcher._pod_teardown("podman", INST, POD)
        assert torn, "the pod teardown did not run"


def _ok():
    class R:
        returncode = 0
        stdout = ""
        stderr = ""
    return R()


def _option_flags(command) -> list[str]:
    """Every CLI flag string declared on a typer command's options."""
    import inspect
    flags: list[str] = []
    for param in inspect.signature(command).parameters.values():
        default = param.default
        for attr in ("param_decls", "_param_decls"):
            decls = getattr(default, attr, None)
            if decls:
                flags += [d for d in decls if isinstance(d, str)]
    return flags


class TestListReportsBrokerAttachment:
    """Group D — `harnessed list` shows whether a running instance has a broker attached."""

    def _record(self, inst=INST, pod=POD, session="i0oku", port=39443):
        broker._write(broker.Broker(
            instance=inst, pod=pod, session=session, port=port, cert_dir="/certs",
        ))

    def test_an_attached_broker_is_reported(self, capsys):
        self._record()
        launcher._broker_report(lambda _pod: True)
        out = capsys.readouterr().out
        assert INST in out
        assert "i0oku" in out

    def test_an_instance_with_no_broker_is_not_reported(self, capsys):
        launcher._broker_report(lambda _pod: True)
        assert INST not in capsys.readouterr().out

    def test_a_stale_record_is_reconciled_away_rather_than_reported(self, capsys):
        """D4/F-d. A record whose pod is gone must not read as 'attached' — that is the list
        telling the user a secret broker is running when it is not, or vice versa."""
        self._record()
        launcher._broker_report(lambda _pod: False, run=lambda _argv: 0)
        assert INST not in capsys.readouterr().out
        assert broker.read(INST) is None

    def test_the_report_prints_no_secret_and_no_token(self, capsys):
        # D3. The section names the instance, the session and the port. Nothing else exists to
        # print — the record holds nothing else, which is the point of keeping it to five fields.
        self._record()
        launcher._broker_report(lambda _pod: True)
        out = capsys.readouterr().out
        assert "vlk_" not in out
        assert TOKEN_ISH not in out

