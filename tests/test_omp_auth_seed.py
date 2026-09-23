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


class TestPruneUnlaunchableOmpBlocks:
    """The liveness rule for the shared agent dir: drop blocks no launch could ever reach.

    `write_omp_identity` refreshes only the launching stack's block, so a stack that stopped
    existing kept injecting its rules into every omp session forever. A block is dropped only when
    its stack fails the same existence check `container_run` already treats as fatal.
    """

    def _agent_dir(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        agent = home / ".omp" / "agent"
        agent.mkdir(parents=True)
        return agent

    def _block(self, name: str) -> str:
        return f"<!-- BEGIN harnessed:{name} -->\n## Rule: r\nbody\n<!-- END harnessed:{name} -->\n"

    def test_drops_only_the_unresolvable_stack(self, monkeypatch, tmp_path):
        agent = self._agent_dir(monkeypatch, tmp_path)
        (agent / "RULES.md").write_text(self._block("gone") + self._block("alive"), encoding="utf-8")
        monkeypatch.setattr(
            launcher.staleness, "stack_resolves", lambda _root, name: name == "alive"
        )

        launcher._prune_unlaunchable_omp_blocks("omp")

        text = (agent / "RULES.md").read_text()
        assert "harnessed:gone" not in text
        assert "harnessed:alive" in text

    def test_a_stale_but_resolvable_stack_keeps_its_block(self, monkeypatch, tmp_path):
        """Staleness is not death — a stale stack rebuilds fine, so its rules must survive."""
        agent = self._agent_dir(monkeypatch, tmp_path)
        (agent / "RULES.md").write_text(self._block("stale-but-real"), encoding="utf-8")
        monkeypatch.setattr(launcher.staleness, "stack_resolves", lambda _root, _name: True)

        launcher._prune_unlaunchable_omp_blocks("omp")

        assert "harnessed:stale-but-real" in (agent / "RULES.md").read_text()

    def test_non_omp_harness_never_touches_the_file(self, monkeypatch, tmp_path):
        agent = self._agent_dir(monkeypatch, tmp_path)
        (agent / "RULES.md").write_text(self._block("gone"), encoding="utf-8")
        monkeypatch.setattr(launcher.staleness, "stack_resolves", lambda _root, _name: False)

        launcher._prune_unlaunchable_omp_blocks("claude")

        assert "harnessed:gone" in (agent / "RULES.md").read_text()

    def test_missing_agent_dir_is_a_noop(self, monkeypatch, tmp_path):
        _home(monkeypatch, tmp_path)  # no ~/.omp/agent at all
        launcher._prune_unlaunchable_omp_blocks("omp")

    def test_both_launch_verbs_prune(self):
        """A container launch never re-assembles, so wiring only the host path would miss it."""
        import inspect

        for fn in (launcher.container_run, launcher._launch_host):
            assert "_prune_unlaunchable_omp_blocks" in inspect.getsource(fn), fn.__name__
