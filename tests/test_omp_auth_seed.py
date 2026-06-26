"""Tests for omp agent-dir sharing.

omp (Oh My Pi) keeps its credentials, setup config, usage and sessions under ~/.omp/agent. The
launcher bind-mounts the host dir rw so the pod shares one omp state with the host (always-current
auth + unified usage tracking), rather than copying a per-instance snapshot.
"""

from pathlib import Path

from harnessed import launcher

CONTAINER_HOME = launcher._CONTAINER_HOME_STR


def _home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


class TestOmpAgentMount:
    def test_bind_mounts_host_agent_dir_rw(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        (home / ".omp" / "agent").mkdir(parents=True)

        mount = launcher._omp_agent_mount("omp")

        assert mount[0] == "-v"
        src, dst, mode = mount[1].rsplit(":", 2)
        assert Path(src) == home / ".omp" / "agent"
        assert dst == f"{CONTAINER_HOME}/.omp/agent"
        assert mode == "rw"

    def test_no_host_agent_dir_returns_empty(self, monkeypatch, tmp_path):
        _home(monkeypatch, tmp_path)  # no ~/.omp/agent
        assert launcher._omp_agent_mount("omp") == []

    def test_non_omp_harness_noop(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        (home / ".omp" / "agent").mkdir(parents=True)
        assert launcher._omp_agent_mount("claude") == []
