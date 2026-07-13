"""Credentialed re-scan: `harnessed rescan [image]` (bd main-9ol).

`harnessed build` is deliberately credential-free — `_build_derived_image` never passes a build
secret — so the build's own scan layer only ever runs osv-scanner + pip-audit, and the token-gated
scanners (snyk, socket) sit it out. THAT is what these tests pin down: the credentialed pass is a
separate container run, fed by an --env-file the host resolved from ~/.config/harnessed/.env{,.schema},
and it is the only path on which snyk/socket see a token.
"""

import re
import subprocess

import pytest
from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    return " ".join(_ANSI.sub("", output).split())


@pytest.fixture
def podman(monkeypatch):
    """Record every podman argv, answering `image exists` from a known set. No real containers."""
    calls: list[list[str]] = []
    existing = {"harnessed-claude-demo:latest"}

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        rc = 0
        stdout = ""
        if cmd[1:3] == ["image", "exists"]:
            rc = 0 if cmd[3] in existing else 1
        elif cmd[1:2] == ["images"]:
            stdout = "harnessed-claude-demo:latest\nharnessed-codex-demo:latest\n"
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    return calls


@pytest.fixture
def no_archive_scan(monkeypatch):
    """Stub the online archive pass (podman save + network osv-scanner) — not under test here."""
    monkeypatch.setattr(launcher, "_scan_image", lambda rt, run_env, image: True)


class TestRescanImageArgument:
    def test_named_image_scans_only_that_image(self, monkeypatch, no_archive_scan, podman):
        scanned: list[str] = []
        monkeypatch.setattr(launcher, "_scan_image", lambda rt, run_env, image: scanned.append(image) or True)
        result = runner.invoke(launcher.app, ["rescan", "harnessed-claude-demo:latest"])
        assert result.exit_code == 0
        assert scanned == ["harnessed-claude-demo:latest"]

    def test_unknown_image_errors_and_scans_nothing(self, monkeypatch, podman):
        scanned: list[str] = []
        monkeypatch.setattr(launcher, "_scan_image", lambda rt, run_env, image: scanned.append(image) or True)
        result = runner.invoke(launcher.app, ["rescan", "harnessed-nope:latest"])
        assert result.exit_code == 1
        assert "no such image 'harnessed-nope:latest'" in plain(result.output)
        assert scanned == []

    def test_omitted_image_still_scans_every_labelled_image(self, monkeypatch, podman):
        """Regression guard: adding the optional arg must not break the bare, scan-everything form."""
        scanned: list[str] = []
        monkeypatch.setattr(launcher, "_scan_image", lambda rt, run_env, image: scanned.append(image) or True)
        result = runner.invoke(launcher.app, ["rescan"])
        assert result.exit_code == 0
        assert scanned == ["harnessed-claude-demo:latest", "harnessed-codex-demo:latest"]


class TestCredentialedContainerScan:
    """`_scan_image_in_container` — the only path that hands snyk/socket a token."""

    def test_resolved_env_files_are_passed_and_harnessed_scan_is_the_command(self, monkeypatch, tmp_path):
        envf = tmp_path / "resolved.env"
        envf.write_text("SNYK_TOKEN=t\nSOCKET_CLI_API_TOKEN=s\n")
        monkeypatch.setattr(launcher, "_resolve_launch_secrets", lambda project_path=None: ([envf], []))

        seen: list[list[str]] = []

        def fake_run(cmd, *a, **kw):
            seen.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)
        assert launcher._scan_image_in_container("podman", "img:latest") is True

        cmd = seen[0]
        assert cmd[:3] == ["podman", "run", "--rm"]
        assert "--env-file" in cmd and str(envf) in cmd
        assert cmd[-2:] == ["img:latest", "harnessed-scan"]

    def test_temp_env_files_are_unlinked_even_when_the_scan_fails(self, monkeypatch, tmp_path):
        """Resolved secrets must never outlive the scan — including on a non-zero exit."""
        secret = tmp_path / "secret.env"
        secret.write_text("SNYK_TOKEN=t\n")
        monkeypatch.setattr(launcher, "_resolve_launch_secrets", lambda project_path=None: ([secret], [secret]))
        monkeypatch.setattr(
            launcher.subprocess, "run", lambda cmd, *a, **kw: subprocess.CompletedProcess(cmd, 1)
        )
        assert launcher._scan_image_in_container("podman", "img:latest") is False
        assert not secret.exists()

    def test_no_schema_still_scans_and_says_snyk_socket_are_skipped(self, monkeypatch, capsys):
        """The original complaint: a tokenless run must SAY the token-gated scanners sat out."""
        monkeypatch.setattr(launcher, "_resolve_launch_secrets", lambda project_path=None: ([], []))
        seen: list[list[str]] = []
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda cmd, *a, **kw: seen.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0),
        )
        launcher._scan_image_in_container("podman", "img:latest")

        out = plain(capsys.readouterr().out)
        assert "snyk and socket have no tokens" in out
        assert "--env-file" not in seen[0]          # nothing to inject
        assert seen[0][-1] == "harnessed-scan"      # ...but the credential-free scanners still run


class TestGlobalScannerTokenSources:
    """Scanner tokens come from the user-global config dir — `.env.schema` (varlock) or a bare `.env`."""

    def test_bare_global_env_is_normalized_into_an_env_file(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        (home / ".config" / "harnessed").mkdir(parents=True)
        (home / ".config" / "harnessed" / ".env").write_text('SNYK_TOKEN="tok"\n')
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)   # no varlock on PATH

        env_files, temp_files = launcher._resolve_launch_secrets(project_path=None)
        assert len(env_files) == 1
        assert "SNYK_TOKEN=tok" in env_files[0].read_text()   # surrounding quotes stripped
        assert env_files[0] in temp_files

    def test_schema_wins_over_a_bare_env(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        cfg = home / ".config" / "harnessed"
        cfg.mkdir(parents=True)
        (cfg / ".env").write_text("SNYK_TOKEN=from-env\n")
        (cfg / ".env.schema").write_text("SNYK_TOKEN=op(op://v/i/f)\n")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/varlock")

        resolved = tmp_path / "resolved.env"
        resolved.write_text("SNYK_TOKEN=from-varlock\n")
        monkeypatch.setattr(launcher, "_varlock_resolve_env_file", lambda d: resolved)

        env_files, _ = launcher._resolve_launch_secrets(project_path=None)
        assert env_files == [resolved]

    def test_no_global_config_resolves_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "empty"))
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
        assert launcher._resolve_launch_secrets(project_path=None) == ([], [])
