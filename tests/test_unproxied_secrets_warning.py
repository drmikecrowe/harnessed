"""The launch-time warning for secrets the credential proxy will not carry (#388 finding F1).

varlock treats every schema item as sensitive by default, so once the launch takes its env from
the broker, an item with no `@proxy` rule resolves to a placeholder that reaches neither the
container nor any upstream. Nothing fails at launch; the agent just gets a real-looking value no
API accepts, and the error surfaces far away as a 401. These tests defend the contract that
harnessed names those items out loud, BEFORE that cutover makes them break.

Today is still the old behaviour: `_varlock_resolve` runs `varlock load`, which returns the real
value for every item whatever its proxy mode (pinned by
`test_it_does_not_claim_an_unrouted_secret_is_already_broken`). The warning is a readiness report,
and its wording has to stay in that tense until the broker path is the one delivering values.

`varlock proxy rules` prints for humans and has no `--format json`, so the classifier parses
display text. The parse is therefore the fragile part, and most of what follows pins its failure
behaviour rather than its happy path.
"""
from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

from harnessed import launchenv


RULES_OUTPUT = """Proxy configuration
  egress mode: permissive

Rules (1)
  • api.github.com  → inject RULED_TOKEN

Secrets (4)
  RULED_TOKEN         proxied: placeholder; real value injected on matching hosts
  PASSTHRU_TOKEN      passthrough: real value sent to the child
  UNCLASSIFIED_TOKEN  placeholder: sensitive, no rule (not injected anywhere)
  DEAD_TOKEN          omit: withheld from the child entirely
"""


def _schema(tmp_path: Path, body: str = "# @proxy(domain=\"x\")\nA=1\n") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env.schema").write_text(body)
    return tmp_path


def _flat(text: str) -> str:
    """Rendered output with every run of whitespace collapsed.

    `_err` is a rich Console that hard-wraps at 80 columns, and the messages embed `schema_dir` —
    a pytest `tmp_path`, whose length differs per machine (`/tmp/pytest-of-mcrowe/pytest-1829/...`
    locally, `/tmp/pytest-of-runner/pytest-0/...` in CI). So the wrap point moves, and a substring
    assertion on a multi-word phrase passes or fails depending on WHO RAN IT. That is how
    `test_a_resolver_failure_...` went green locally and red on CI.

    Assert through this, never on the raw text.
    """
    return " ".join(text.split())


def _fake_rules(stdout: str, returncode: int = 0):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


@pytest.fixture(autouse=True)
def _clean():
    launchenv._varlock_cache_clear()
    yield
    launchenv._varlock_cache_clear()


class TestClassification:
    def test_every_mode_is_read_off_the_rules_output(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) == {
            "RULED_TOKEN": "proxied",
            "PASSTHRU_TOKEN": "passthrough",
            "UNCLASSIFIED_TOKEN": "placeholder",
            "DEAD_TOKEN": "omit",
        }

    def test_a_count_mismatch_is_refused_rather_than_half_reported(self, tmp_path, monkeypatch):
        """The header states its own count. If the parse disagrees, the format has moved and every
        conclusion drawn from it is suspect — including a reassuring one."""
        broken = RULES_OUTPUT.replace("Secrets (4)", "Secrets (9)")
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(broken))
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) is None

    def test_a_missing_secrets_header_is_refused(self, tmp_path, monkeypatch):
        head = RULES_OUTPUT.split("Secrets (4)")[0]
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(head))
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) is None

    def test_a_missing_rules_header_is_refused(self, tmp_path, monkeypatch):
        """Both headers are the structural check; one of them alone does not prove the shape."""
        no_rules = "\n".join(
            ln for ln in RULES_OUTPUT.splitlines() if not ln.startswith("Rules (")
        )
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(no_rules))
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) is None

    def test_a_nonzero_exit_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT, returncode=1))
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) is None

    def test_a_hanging_varlock_degrades_instead_of_blocking_the_launch(self, tmp_path, monkeypatch):
        seen: dict = {}

        def run(cmd, **kw):
            seen.update(kw)
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0.0)

        monkeypatch.setattr(launchenv.subprocess, "run", run)
        assert launchenv._varlock_proxy_modes(_schema(tmp_path)) is None
        assert seen.get("timeout"), "proxy rules resolves values, so it must carry a deadline"

    def test_the_result_is_memoized(self, tmp_path, monkeypatch):
        calls: list[int] = []

        def run(cmd, **kw):
            calls.append(1)
            return subprocess.CompletedProcess(cmd, 0, stdout=RULES_OUTPUT, stderr="")

        monkeypatch.setattr(launchenv.subprocess, "run", run)
        d = _schema(tmp_path)
        launchenv._varlock_proxy_modes(d)
        launchenv._varlock_proxy_modes(d)
        assert len(calls) == 1


class TestTheGate:
    """A schema with no `@proxy` is every schema shipped today. It must cost nothing and say
    nothing — `proxy rules` resolves values, so it can prompt for a 1Password unlock."""

    def test_a_schema_without_proxy_never_shells_out(self, tmp_path, capsys, monkeypatch):
        def explode(*a, **kw):
            raise AssertionError("varlock must not run for a schema that never mentions @proxy")

        monkeypatch.setattr(launchenv.subprocess, "run", explode)
        launchenv._warn_unproxied_secrets(_schema(tmp_path, "# @sensitive\nSNYK_TOKEN=op(op://v/i/f)\n"))
        assert _flat(capsys.readouterr().err) == ""

    @pytest.mark.parametrize("prose", [
        "# TODO: add @proxy after the migration\nA=1\n",
        "# see the @proxy docs before editing this\nA=1\n",
        # Bare `@proxy` is not an annotation either. Measured on varlock 1.17.0: the item is
        # reported as `omit` and `varlock load` fails validation, so `_varlock_resolve` already
        # returns None and the launch says so. Nothing is silenced by skipping it here.
        "# @sensitive @proxy\nA=1\n",
    ])
    def test_a_prose_mention_of_proxy_does_not_buy_a_subprocess(self, tmp_path, capsys,
                                                                monkeypatch, prose):
        """The gate guards a `varlock proxy rules` call that RESOLVES values and can sit on a
        1Password prompt. A schema that merely says the word has opted into nothing."""
        def explode(*a, **kw):
            raise AssertionError("varlock must not run for a schema with no @proxy annotation")

        monkeypatch.setattr(launchenv.subprocess, "run", explode)
        launchenv._warn_unproxied_secrets(_schema(tmp_path, prose))
        assert _flat(capsys.readouterr().err) == ""

    @pytest.mark.parametrize("annotation", [
        '# @sensitive @proxy(domain="api.github.com")\nA=1\n',
        "# @sensitive @proxy=passthrough\nA=1\n",
        '# @proxyConfig={egress="strict"}\n# ---\n# @sensitive\nA=1\n',
    ])
    def test_every_real_annotation_form_still_opens_the_gate(self, tmp_path, monkeypatch,
                                                             annotation):
        """The inverse risk of tightening the gate: a pattern narrow enough to miss a real
        annotation makes the whole warning fail silent, which is the failure mode this file exists
        to prevent. All three forms are ones varlock 1.17.0 acts on."""
        ran: list = []
        monkeypatch.setattr(launchenv.subprocess, "run",
                            lambda *a, **kw: ran.append(1) or _fake_rules(RULES_OUTPUT)(*a, **kw))
        launchenv._warn_unproxied_secrets(_schema(tmp_path, annotation))
        assert ran, f"gate closed on a real annotation: {annotation!r}"

    def test_an_absent_schema_is_silent(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no")))
        launchenv._warn_unproxied_secrets(tmp_path)
        assert _flat(capsys.readouterr().err) == ""


class TestWhatGetsReported:
    def test_an_unroutable_secret_is_named(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = _flat(capsys.readouterr().err)
        assert "UNCLASSIFIED_TOKEN" in err

    def test_a_resolver_failure_is_reported_separately_from_a_missing_route(self, tmp_path, capsys,
                                                                            monkeypatch):
        """`omit` and `placeholder` fail differently and are fixed differently: one is a broken
        resolver, the other a missing rule. Collapsing them sends the reader to the wrong file."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = _flat(capsys.readouterr().err)
        assert "DEAD_TOKEN" in err
        assert "could not be resolved" in err
        # The two groups must not be merged into one list.
        assert err.index("DEAD_TOKEN") > err.index("UNCLASSIFIED_TOKEN")

    def test_it_does_not_claim_an_unrouted_secret_is_already_broken(self, tmp_path, capsys,
                                                                    monkeypatch):
        """Today `_varlock_resolve` runs `varlock load`, which returns the REAL value whatever the
        proxy mode — so an unrouted item still works. The warning is a readiness report, and
        stating it in the present tense would be false until #388 Phase 1 switches the launch to
        the broker's placeholder env."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = _flat(capsys.readouterr().err)
        assert "still arrive as real values today" in err

    def test_a_proxied_secret_is_not_reported(self, tmp_path, capsys, monkeypatch):
        """The whole point is that it works; naming it would train the reader to skip the block."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "RULED_TOKEN" not in _flat(capsys.readouterr().err)

    def test_an_all_passthrough_schema_raises_no_warning(self, tmp_path, capsys, monkeypatch):
        """Passthrough is a declared decision, not a defect. Warning on it would make the warning
        unreadable for the schemas that opt every item out deliberately."""
        out = ("Proxy configuration\n  egress mode: permissive\n\nRules (0)\n"
               "  (none; add @proxy(domain=...) to route a secret)\n\n"
               "Secrets (2)\n  A  passthrough: real value sent to the child\n"
               "  B  passthrough: real value sent to the child\n")
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(out))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "warning" not in _flat(capsys.readouterr().err)

    def test_passthrough_items_are_still_listed_as_a_note(self, tmp_path, capsys, monkeypatch):
        """'Which real secrets are still in the container' is the question the proxy exists to
        answer, and passthrough keeps the full pre-proxy exposure."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "PASSTHRU_TOKEN" in _flat(capsys.readouterr().err)

    def test_an_unknown_mode_is_treated_as_unsafe(self, tmp_path, capsys, monkeypatch):
        """varlock's proxy surface is an explicit preview and its modes may grow. A mode this
        version has never heard of must not be assumed benign."""
        out = ("Proxy configuration\n  egress mode: permissive\n\nRules (1)\n"
               "  • h  → inject X\n\nSecrets (1)\n  X  quarantined: something new\n")
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(out))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = _flat(capsys.readouterr().err)
        assert "X" in err and "quarantined" in err

    def test_an_unparseable_rules_output_says_so_instead_of_going_quiet(self, tmp_path, capsys,
                                                                       monkeypatch):
        """The failure this whole file exists to prevent is a guard that stops guarding without
        telling anyone (cf. the egress firewall, #429)."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules("something else entirely\n"))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "could not be classified" in _flat(capsys.readouterr().err)

    def test_the_report_survives_a_schema_path_long_enough_to_move_every_wrap(
        self, tmp_path, capsys, monkeypatch
    ):
        """`_err` hard-wraps at 80 columns and the messages embed the schema path, so the wrap
        points are a function of how long that path happens to be. This passed locally and failed
        on CI purely because `/tmp/pytest-of-runner/pytest-0/…` is a different length from
        `/tmp/pytest-of-mcrowe/pytest-1829/…`, which split "could not be resolved" across a line.

        A path long enough to shift every wrap keeps that class of bug from coming back."""
        deep = tmp_path / ("d" * 60) / ("e" * 60)
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(deep))
        err = _flat(capsys.readouterr().err)
        for phrase in ("declare no @proxy route", "could not be resolved",
                       "still arrive as real values today"):
            assert phrase in err, f"{phrase!r} did not survive wrapping"

    def test_no_secret_value_is_ever_printed(self, tmp_path, capsys, monkeypatch):
        """The report is names and modes only — that is what makes it safe on every launch."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = _flat(capsys.readouterr().err)
        # The descriptions carry no values, and nothing here reads the resolved map at all.
        assert "op://" not in err
        assert "real value injected on matching hosts" not in err

    def test_it_warns_once_per_dir_even_though_four_call_sites_ask(self, tmp_path, capsys,
                                                                   monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        d = _schema(tmp_path)
        launchenv._warn_unproxied_secrets(d)
        launchenv._warn_unproxied_secrets(d)
        assert _flat(capsys.readouterr().err).count("UNCLASSIFIED_TOKEN") == 1


class TestBothLaunchPathsAreWired:
    """Container and host mode read the same schemas; a warning on only one of them is a warning
    the host-native user never sees."""

    @pytest.mark.parametrize("entry", ["_resolve_launch_secrets", "_resolve_launch_env"])
    def test_the_project_schema_is_classified(self, tmp_path, monkeypatch, entry):
        asked: list[Path] = []
        monkeypatch.setattr(launchenv, "_warn_unproxied_secrets", lambda d: asked.append(d))
        monkeypatch.setattr(launchenv.shutil, "which", lambda _: "/usr/bin/varlock")
        monkeypatch.setattr(launchenv, "_varlock_resolve", lambda d: {})
        monkeypatch.setattr(launchenv, "_varlock_resolve_env_file", lambda d: None)
        # Point the global lookup somewhere empty so only the project dir can register.
        monkeypatch.setattr(launchenv.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
        proj = _schema(tmp_path / "proj")
        getattr(launchenv, entry)(proj)
        assert proj in asked
