"""Tests for host-native first-run setup: the git-common-dir → database-name algorithm, repo-identity
primitives, the {…} substitution engine, `setup.config`/`script` resolution, and the codified
`beads/team` recipe. Also covers native-MCP emission (moved here when the daemon supervisor was
removed)."""

import subprocess
from pathlib import Path

import pytest
import typer

from support import patch_all

from harnessed import launcher
from harnessed.schema import (
    PinValidationError,
    RecipeLintError,
    SchemaError,
    load_recipe,
    validate_setup_script,
)

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


class TestHostRunSetupsExecutesTheScript:
    """`_host_run_setups` actually runs a recipe's `setup.script`.

    This coverage existed only through `setup.run` (tests/test_folder_env_contract.py's old
    `test_host_run_site`), so removing that field in bd harnessed-0tk.9 deleted the sole end-to-end
    exercise of this function — a mutation making it skip every recipe passed the whole suite.
    Asserted on the script's observable side effect, not on a call count, so it would still fail if
    the launcher invoked bash without the script or with the wrong cwd.
    """

    def _recipe(self, tmp_path, body_script: str):
        d = tmp_path / "cat" / "r"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n"
        )
        (d / "setup.sh").write_text(body_script)
        return load_recipe(d, strict=True)

    def _run(self, tmp_path, monkeypatch, recipe, proj):
        # patch_all, NOT setattr(launcher, …): `_host_run_setups` lives in hostrun.py and resolves
        # this name in hostrun's globals, so patching launcher's binding would silently do nothing
        # and the real catalog lookup would run (see tests/support.py).
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _c, _s: (None, [recipe]))
        monkeypatch.setattr(launcher.paths, "xdg_data_home", lambda: tmp_path / "xdg")
        monkeypatch.setattr(launcher.paths, "git_common_dir", lambda _p: None)
        launcher._host_run_setups("s", proj, harness="claude")

    def test_the_script_runs(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        stamp = tmp_path / "ran"
        r = self._recipe(tmp_path, f"#!/usr/bin/env bash\ntouch {stamp}\n")
        self._run(tmp_path, monkeypatch, r, proj)
        assert stamp.exists(), "_host_run_setups did not execute the recipe's setup.script"

    def test_it_runs_in_the_project_directory(self, tmp_path, monkeypatch):
        """cwd is the contract a setup script is written against — `bd init` must land in the
        project, not in harnessed's own tree."""
        proj = tmp_path / "proj"
        proj.mkdir()
        r = self._recipe(tmp_path, "#!/usr/bin/env bash\npwd > cwd.txt\n")
        self._run(tmp_path, monkeypatch, r, proj)
        assert (proj / "cwd.txt").read_text().strip() == str(proj)

    def test_a_failing_script_aborts_the_launch(self, tmp_path, monkeypatch):
        """Exit non-zero must stop the launch — continuing would hand the user an agent whose
        first-run setup silently failed."""
        proj = tmp_path / "proj"
        proj.mkdir()
        r = self._recipe(tmp_path, "#!/usr/bin/env bash\nexit 3\n")
        # typer.Exit specifically — a bare `Exception` here would also be satisfied by the launch
        # blowing up for an unrelated reason, which is how this test first passed while the script
        # was never reached at all.
        with pytest.raises(typer.Exit):
            self._run(tmp_path, monkeypatch, r, proj)


class TestBeadsTeamIsNotAutoInitialized:
    """beads/team must NEVER self-initialize. This replaces two tests that pinned the opposite, and
    the behaviour they pinned is the origin of the 2026-07-19 incident.

    What used to run automatically on a host launch:

        bd init --shared-server --database <gcd> --prefix <repo> --init-if-missing

    No `--external`, no `--server-socket`, so bd's auto-start stayed enabled — pointed at the global
    `~/.beads/shared-server`, one database dir for every project on the machine. Three days later a
    host `bd` auto-started into its own data dir, initialized that directory as a database, and the
    project database was unreachable for five days (BEADS.md §10). The feature landed 2026-07-16 —
    the same date as this checkout's `metadata.json.bak-before-shared-reinit`.

    It is also the placement where `bd init` COMMITS 18 files to a shared repo, which is the user's
    decision. beads/stealth auto-inits instead, because `--stealth` writes no commit at all.
    """

    def test_team_never_initializes_without_asking(self):
        """Team DOES automate `bd init` now — behind `setup.confirm`, which is what keeps the
        decision the user's (see tests/test_setup_confirm.py). What must never come back is
        executable setup that runs unattended.

        The `run:` field the 2026-07-19 shared-server command lived in no longer exists — it was
        removed outright in bd harnessed-0tk.9, so a recipe cannot declare it and `_parse_setup`
        rejects it by name. That half of this guard is now structural rather than asserted here;
        tests/test_setup_run_removed.py pins the rejection. What is still worth asserting is the
        property that outlives the field: team's executable setup must be confirm-gated.
        """
        r = load_recipe(CATALOG / "recipes" / "beads" / "team", strict=True)
        assert r.setup is not None, "the user-facing notice must survive"
        assert r.setup.script, "team's automation is a setup script"
        assert r.setup.confirm, "team's setup script must be gated by a confirm"

    def test_team_init_never_runs_bd(self):
        """`init:` runs on every launch, so anything that touches the DATABASE there is the same
        hazard by another door. Team's init exists only to put the `bd-shim` wrapper on PATH (see
        tests/test_beads_bd_shim.py) — a plain export, no `bd` invocation of any kind."""
        r = load_recipe(CATALOG / "recipes" / "beads" / "team", strict=True)
        if r.init is None:
            return
        assert r.init.run.startswith("export "), "team's init must be an export, not a command"
        assert "bd " not in r.init.run, "team must not self-initialize"

    def test_no_beads_recipe_reaches_bds_shared_server(self):
        """The hazard followed the field. With `setup.run` removed (bd harnessed-0tk.9) the only
        place an executable setup command can live is the SCRIPT FILE, so scan its contents —
        scanning the recipe yaml alone would now pass vacuously no matter what the script did."""
        for variety in ("team", "stealth"):
            r = load_recipe(CATALOG / "recipes" / "beads" / variety, strict=True)
            parts = [r.init.run if r.init else ""]
            if r.setup and r.setup.script:
                parts.append((r.root / r.setup.script).read_text())
            blob = " ".join(parts)
            assert "--shared-server" not in blob, f"beads/{variety} must not use bd's shared server"

    def test_both_placements_gate_on_beads_dir_not_raw_git(self):
        """`git rev-parse --git-common-dir` is wrong for an ordinary clone.

        There the common dir is `<repo>/.git`, so the old team condition tested
        `<repo>/.git/.beads/metadata.json` while bd's workspace lives at `<repo>/.beads` — a path
        that can never exist, so the notice fired on every launch of an already-initialized
        workspace and `bd init` then refused. It passed unnoticed because harnessed's OWN repo is
        bare+worktrees, where the common dir is `.bare/` and `.bare/.beads` is the real workspace.

        $BEADS_DIR resolves through the same persist entry the launcher and the service use, so it
        is correct in both layouts and both modes.
        """
        for placement in ("team", "stealth"):
            recipe = load_recipe(CATALOG / "recipes" / "beads" / placement, strict=True)
            assert recipe.setup is not None
            cond = recipe.setup.condition or ""
            assert "BEADS_DIR" in cond, f"beads/{placement} must gate on $BEADS_DIR"
            assert "git-common-dir" not in cond, f"beads/{placement} must not shell out to git"

    def test_stealth_initializes_itself_externally(self):
        r = load_recipe(CATALOG / "recipes" / "beads" / "stealth", strict=True)
        assert r.init is not None
        # --external is what keeps bd from ever auto-starting a dolt of its own. The port comes
        # from the service's client_env and is passed explicitly so its `:?` guard is the check
        # that beads-server is actually attached.
        assert "--external" in r.init.run and "--server-port" in r.init.run
        assert "--stealth" in r.init.run


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


class TestSetupScriptSchema:
    """`setup.script` — the both-mode replacement for `setup.run` + `provision:` (bd harnessed-zi6)."""

    def _recipe(self, tmp_path, body: str, script: str | None = "echo hi"):
        d = tmp_path / "r"
        d.mkdir(exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        if script is not None:
            (d / "setup.sh").write_text(f"#!/usr/bin/env bash\n{script}\n")
        return d

    def test_script_parsed(self, tmp_path):
        d = self._recipe(tmp_path, "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n")
        assert load_recipe(d, strict=True).setup.script == "setup.sh"

    def test_declaring_run_alongside_script_is_rejected(self, tmp_path):
        """`run` used to be merely mutually exclusive with `script`; it is now removed outright, so
        declaring it is an error whether or not a script is present (bd harnessed-0tk.9)."""
        d = self._recipe(
            tmp_path,
            "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n  run: echo hi\n",
        )
        with pytest.raises(SchemaError, match="has been removed"):
            load_recipe(d, strict=True)

    def test_script_escaping_recipe_dir_rejected(self, tmp_path):
        d = self._recipe(
            tmp_path, "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: ../../evil.sh\n"
        )
        with pytest.raises(SchemaError, match="relative path inside the recipe dir"):
            load_recipe(d, strict=True)


class TestValidateSetupScript:
    """The script is a FILE, so neither validate_no_raw_npm (strings only) nor validate_pin
    (Dockerfiles only) would ever read it. validate_setup_script closes that hole."""

    def _load(self, tmp_path, script_body):
        d = tmp_path / "r"
        d.mkdir(exist_ok=True)
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n"
        )
        (d / "setup.sh").write_text(script_body)
        return load_recipe(d, strict=True)

    def test_clean_script_passes(self, tmp_path):
        validate_setup_script(self._load(tmp_path, "#!/usr/bin/env bash\nuv tool install x==1.2.3\n"))

    def test_raw_npm_in_script_rejected(self, tmp_path):
        with pytest.raises(RecipeLintError, match="raw npm/npx"):
            validate_setup_script(self._load(tmp_path, "#!/usr/bin/env bash\nnpm install -g x\n"))

    def test_floating_ref_in_script_rejected(self, tmp_path):
        with pytest.raises(PinValidationError, match="floating ref"):
            validate_setup_script(self._load(tmp_path, "#!/usr/bin/env bash\nuv tool install x@latest\n"))

    def test_comments_do_not_self_trigger(self, tmp_path):
        validate_setup_script(self._load(tmp_path, "#!/usr/bin/env bash\n# never use npm install or @latest\ntrue\n"))

    def test_missing_script_file_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n"
        )
        with pytest.raises(RecipeLintError, match="not found"):
            validate_setup_script(load_recipe(d, strict=True))


class TestScriptEnv:
    """The env contract — the SAME keys must reach the script in host and container mode."""

    VALUES = {"repo": "harnessed", "gcd_db": "prog_harnessed", "config.name": "harnessed"}

    def test_primitives_and_config_become_env(self):
        env = launcher._script_env("st", Path("/p"), self.VALUES, mode="host", harness="claude")
        assert env["HARNESSED_MODE"] == "host"
        assert env["HARNESSED_STACK"] == "st"
        assert env["HARNESSED_PROJECT_DIR"] == "/p"
        assert env["HARNESSED_REPO"] == "harnessed"
        assert env["HARNESSED_GCD_DB"] == "prog_harnessed"
        assert env["HARNESSED_CFG_NAME"] == "harnessed"

    def test_key_set_identical_across_modes(self):
        host = launcher._script_env("st", Path("/p"), self.VALUES, mode="host", harness="claude")
        ctr = launcher._script_env("st", Path("/p"), self.VALUES, mode="container", harness="claude")
        assert set(host) - {"HARNESSED_MODE"} == set(ctr) - {"HARNESSED_MODE"}
        assert ctr["HARNESSED_MODE"] == "container"

    def test_bin_dir_leads_path_so_install_then_configure_works(self, tmp_path):
        env = launcher._script_env("st", Path("/p"), self.VALUES, mode="host", harness="claude", bin_dir=tmp_path)
        assert env["HARNESSED_BIN_DIR"] == str(tmp_path)
        assert env["PATH"].startswith(f"{tmp_path}:")

    def test_project_dir_is_mode_invariant(self):
        """_build_mount_args mounts the project at its own host path, so the string is identical."""
        host = launcher._script_env("st", Path("/home/u/proj"), {}, mode="host", harness="claude")
        ctr = launcher._script_env("st", Path("/home/u/proj"), {}, mode="container", harness="claude")
        assert host["HARNESSED_PROJECT_DIR"] == ctr["HARNESSED_PROJECT_DIR"] == "/home/u/proj"


class TestSetupScriptIgnoresCondition:
    """Regression: `setup.condition` must NOT gate a `setup.script`.

    A condition is a FIRST-RUN gate (serena's `test ! -d .serena`). Gating the script on it made the
    script fresh-project-only, so a project whose state already existed but was WRONG could never be
    corrected — the observed bug: .serena/project.yml stuck at project_name "main" forever.
    """

    def _recipe(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir(exist_ok=True)
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: http://x\n"
            "  condition: 'false'\n  script: setup.sh\n"  # condition SATISFIED (non-zero) = "done"
        )
        (d / "setup.sh").write_text("#!/usr/bin/env bash\ntrue\n")
        return load_recipe(d, strict=True)

    def test_script_still_pending_when_condition_says_done(self, tmp_path):
        recipe = self._recipe(tmp_path)
        assert launcher._pending_setup_scripts(tmp_path, [recipe]) == [recipe]

    def test_serena_condition_would_have_blocked_an_existing_project(self):
        """The serena recipe still declares a condition (for the NOTICE) — it must not gate."""
        r = load_recipe(CATALOG / "recipes" / "serena", strict=True)
        assert r.setup.condition and r.setup.script
        assert launcher._pending_setup_scripts(Path("/tmp"), [r]) == [r]


class TestSerenaSetupScript:
    """Exercises catalog/recipes/serena/setup.sh directly against a stub `serena` on PATH."""

    SCRIPT = CATALOG / "recipes" / "serena" / "setup.sh"

    def _run(self, tmp_path, project_yml: str | None, name="harnessed"):
        proj = tmp_path / "proj"
        (proj / ".serena").mkdir(parents=True)
        if project_yml is not None:
            (proj / ".serena" / "project.yml").write_text(project_yml)
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        calls = stub_dir / "calls.log"
        stub = stub_dir / "serena"
        stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> {calls}\n')
        stub.chmod(0o755)
        (tmp_path / "home" / ".serena").mkdir(parents=True)
        (tmp_path / "home" / ".serena" / "serena_config.yml").write_text("language_backend: LSP\n")
        env = {
            "PATH": f"{stub_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "HARNESSED_MODE": "container",  # skips the host install branch
            "HARNESSED_PROJECT_DIR": str(proj),
            "HARNESSED_CFG_NAME": name,
        }
        proc = subprocess.run(["bash", str(self.SCRIPT)], env=env, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        yml = (proj / ".serena" / "project.yml")
        return (yml.read_text() if yml.is_file() else None,
                calls.read_text() if calls.is_file() else "")

    def test_corrects_directory_derived_name(self, tmp_path):
        """The reported bug: project_name stuck at the worktree folder name."""
        text, calls = self._run(tmp_path, 'project_name: "main"\nlanguages:\n- python\n')
        assert 'project_name: "harnessed"' in text
        assert "languages:" in text  # rest of the file survives
        assert "project create" not in calls  # create would have errored on an existing project

    def test_is_idempotent(self, tmp_path):
        text, _ = self._run(tmp_path, 'project_name: "harnessed"\nlanguages:\n- python\n')
        assert text.count("project_name:") == 1
        assert 'project_name: "harnessed"' in text

    def test_adds_key_when_absent(self, tmp_path):
        text, _ = self._run(tmp_path, "languages:\n- python\n")
        assert 'project_name: "harnessed"' in text

    def test_creates_project_when_none_exists(self, tmp_path):
        _, calls = self._run(tmp_path, None)
        assert "project create --name harnessed --index ." in calls
