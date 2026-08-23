"""The launch-time warning for secrets the credential proxy will not carry (#388 finding F1).

varlock treats every schema item as sensitive by default, and an item with no `@proxy` rule
resolves to a placeholder that reaches neither the container nor any upstream. Nothing fails at
launch; the agent just gets a real-looking value no API accepts, and the error surfaces far away
as a 401. These tests defend the contract that harnessed names those items out loud.

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
        assert capsys.readouterr().err == ""

    def test_an_absent_schema_is_silent(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no")))
        launchenv._warn_unproxied_secrets(tmp_path)
        assert capsys.readouterr().err == ""


class TestWhatGetsReported:
    def test_an_unroutable_secret_is_named(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = capsys.readouterr().err
        assert "UNCLASSIFIED_TOKEN" in err

    def test_a_resolver_failure_is_reported_as_unset_not_as_a_bad_value(self, tmp_path, capsys,
                                                                       monkeypatch):
        """`omit` and `placeholder` fail differently and are fixed differently: one is a broken
        resolver, the other a missing rule. Collapsing them sends the reader to the wrong file."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = capsys.readouterr().err
        assert "DEAD_TOKEN" in err
        assert "UNSET" in err

    def test_a_proxied_secret_is_not_reported(self, tmp_path, capsys, monkeypatch):
        """The whole point is that it works; naming it would train the reader to skip the block."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "RULED_TOKEN" not in capsys.readouterr().err

    def test_an_all_passthrough_schema_raises_no_warning(self, tmp_path, capsys, monkeypatch):
        """Passthrough is a declared decision, not a defect. Warning on it would make the warning
        unreadable for the schemas that opt every item out deliberately."""
        out = ("Proxy configuration\n  egress mode: permissive\n\nRules (0)\n"
               "  (none; add @proxy(domain=...) to route a secret)\n\n"
               "Secrets (2)\n  A  passthrough: real value sent to the child\n"
               "  B  passthrough: real value sent to the child\n")
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(out))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "warning" not in capsys.readouterr().err

    def test_passthrough_items_are_still_listed_as_a_note(self, tmp_path, capsys, monkeypatch):
        """'Which real secrets are still in the container' is the question the proxy exists to
        answer, and passthrough keeps the full pre-proxy exposure."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "PASSTHRU_TOKEN" in capsys.readouterr().err

    def test_an_unknown_mode_is_treated_as_unsafe(self, tmp_path, capsys, monkeypatch):
        """varlock's proxy surface is an explicit preview and its modes may grow. A mode this
        version has never heard of must not be assumed benign."""
        out = ("Proxy configuration\n  egress mode: permissive\n\nRules (1)\n"
               "  • h  → inject X\n\nSecrets (1)\n  X  quarantined: something new\n")
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(out))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = capsys.readouterr().err
        assert "X" in err and "quarantined" in err

    def test_an_unparseable_rules_output_says_so_instead_of_going_quiet(self, tmp_path, capsys,
                                                                       monkeypatch):
        """The failure this whole file exists to prevent is a guard that stops guarding without
        telling anyone (cf. the egress firewall, #429)."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules("something else entirely\n"))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        assert "could not be classified" in capsys.readouterr().err

    def test_no_secret_value_is_ever_printed(self, tmp_path, capsys, monkeypatch):
        """The report is names and modes only — that is what makes it safe on every launch."""
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        launchenv._warn_unproxied_secrets(_schema(tmp_path))
        err = capsys.readouterr().err
        # The descriptions carry no values, and nothing here reads the resolved map at all.
        assert "op://" not in err
        assert "real value injected on matching hosts" not in err

    def test_it_warns_once_per_dir_even_though_four_call_sites_ask(self, tmp_path, capsys,
                                                                   monkeypatch):
        monkeypatch.setattr(launchenv.subprocess, "run", _fake_rules(RULES_OUTPUT))
        d = _schema(tmp_path)
        launchenv._warn_unproxied_secrets(d)
        launchenv._warn_unproxied_secrets(d)
        assert capsys.readouterr().err.count("UNCLASSIFIED_TOKEN") == 1


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
