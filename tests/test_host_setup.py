"""Tests for host-native first-run setup: the git-common-dir → database-name algorithm, repo-identity
primitives, the {…} substitution engine, `setup.config`/`run` resolution, and the codified
`beads/team` recipe. Also covers native-MCP emission (moved here when the daemon supervisor was
removed)."""

from pathlib import Path

from harnessed import launcher
from harnessed.schema import load_recipe

CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class TestGcdDbName:
    def test_relative_to_home_lowercase_underscored(self, monkeypatch):
        gcd = Path.home() / "Programming" / "Personal" / "harnessed" / ".bare"
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: gcd)
        assert launcher._gcd_db_name(Path("/anywhere")) == "programming_personal_harnessed"

    def test_drops_leading_components_over_64(self, monkeypatch):
        gcd = Path.home().joinpath(
            "a", "BigOrg", "PlatformTeam", "DataPipeline", "IngestionSubsystem",
            "the-actual-repo", ".bare",
        )
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: gcd)
        name = launcher._gcd_db_name(Path("/x"))
        assert len(name) <= 64
        assert not name.startswith("a_") and "bigorg" not in name  # shallowest dropped first
        assert name.endswith("the_actual_repo")                    # specific tail kept

    def test_outside_home_uses_full_path(self, monkeypatch):
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: Path("/opt/work/myrepo/.bare"))
        assert launcher._gcd_db_name(Path("/x")) == "opt_work_myrepo"


class TestRepoPrimitives:
    def test_basename_and_db_and_hashes(self, monkeypatch):
        gcd = Path.home() / "Programming" / "Personal" / "harnessed" / ".bare"
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: gcd)
        p = launcher._repo_primitives(Path("/x"))
        assert p["repo"] == "harnessed"                       # basename, for the prefix
        assert p["gcd_db"] == "programming_personal_harnessed"  # unique db name
        assert len(p["gcd_hash"]) == 8


class TestSubst:
    def test_substitutes_known_leaves_unknown(self):
        out = launcher._subst("db={config.database} repo={repo} keep={unknown}",
                              {"config.database": "x", "repo": "harnessed"})
        assert out == "db=x repo=harnessed keep={unknown}"


class TestBeadsTeamCodified:
    def test_resolves_to_shared_server_init(self, monkeypatch):
        gcd = Path.home() / "Programming" / "Personal" / "harnessed" / ".bare"
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: gcd)
        r = load_recipe(CATALOG / "recipes" / "beads" / "team", strict=True)
        assert r.setup.run and "--shared-server" in r.setup.run

        prims = launcher._repo_primitives(Path("/x"))
        vals = launcher._resolve_setup_config(r.setup, prims, interactive=False)  # default prefix
        cmd = launcher._subst(r.setup.run, vals)
        assert cmd == (
            "bd init --shared-server --database programming_personal_harnessed "
            "--prefix harnessed --init-if-missing"
        )

    def test_prompt_used_when_interactive(self, monkeypatch):
        gcd = Path.home() / "Programming" / "Personal" / "harnessed" / ".bare"
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: gcd)
        monkeypatch.setattr(launcher.typer, "prompt", lambda *a, **k: "hns")  # user overrides prefix
        r = load_recipe(CATALOG / "recipes" / "beads" / "team", strict=True)
        vals = launcher._resolve_setup_config(r.setup, launcher._repo_primitives(Path("/x")),
                                              interactive=True)
        assert vals["config.prefix"] == "hns"
        assert vals["config.database"] == "programming_personal_harnessed"  # derive is silent


class TestNativeMcp:
    """Default host MCP path (hatago deferred): servers emitted directly into native .mcp.json."""

    def test_no_mcp_stack_returns_none(self):
        assert launcher._host_native_mcp("hostspike") is None  # greet: no MCP

    def test_stdio_server_emitted_natively(self):
        servers = launcher._host_native_mcp("hostmcp")  # [time] → uvx mcp-server-time
        assert servers is not None
        assert servers["time"]["command"] == "uvx"
        assert "mcp-server-time" in servers["time"]["args"]
        assert "url" not in servers["time"]
