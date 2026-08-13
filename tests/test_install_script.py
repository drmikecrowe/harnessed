"""The `install:` mechanism — bd harnessed-8px.3.

ONE bash file per recipe, executed by BOTH the container executor and a host launch, so the
deliverables of what used to be a container-only Dockerfile RUN exist in both modes.
That asymmetry is bd harnessed-8px.1: a `--host` launch of a stack containing superpowers shipped
0 of its 14 skills and said nothing.

Four properties carry the whole design, and each has its own class below:

  * PHASE — install's env is a deliberate SUBSET of the folder-env contract (no PROJECT_DIR).
    That subset was fixed when install ran at BUILD time container-side; bd harnessed-8px.21.4
    moved it to container RUNTIME (into a per-stack volume) and the subset deliberately did NOT
    widen — a project is still not part of the install phase in either mode.
  * ORDERING — host installs run AFTER `_materialize_host_home`, which rmtree's the home on every
    launch. Before it, the output is deleted milliseconds later, silently.
  * CACHE — because of that same wipe, "first launch only" is structurally impossible; the install
    runs every launch, and only a pinned-ref content cache makes that affordable.
  * LINT — moving Dockerfile RUN bodies into a .sh blinds `validate_pin` and `validate_no_raw_npm`,
    which read Dockerfile TEXT. `validate_install_script` is what keeps pin enforcement alive.
"""

import inspect
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from harnessed import emit, launcher, paths, update
from harnessed.schema import (
    InstallRef,
    PinValidationError,
    derived_cache_key,
    RecipeLintError,
    SchemaError,
    load_recipe,
    validate_install_script,
    validate_no_claude_writes,
)
from support import patch_all
from harnessed import setupenv

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """rich styles its output; assert against the words, not the escape codes."""
    return _ANSI.sub("", text)


def _recipe(tmp_path, name="r", *, install: str | None = None, script_body: str = "true\n",
            env: str = "", extra: str = ""):
    """A loadable recipe dir carrying an `install:` block and its script file."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    body = f"name: {name}\n{env}{extra}"
    if install is not None:
        body += install
    (d / "recipe.yaml").write_text(body)
    (d / "install.sh").write_text(script_body)
    return load_recipe(d, strict=True)


class TestInstallField:
    def test_minimal_install_parses(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        assert r.install.script == "install.sh"
        assert r.install.cache is None and r.install.system is None

    def test_cache_and_system_parse(self, tmp_path):
        r = _recipe(
            tmp_path,
            install="install:\n  script: install.sh\n  cache: v6.0.3\n  system: 'apt-get cmake'\n",
        )
        assert (r.install.cache, r.install.system) == ("v6.0.3", "apt-get cmake")

    def test_recipe_without_install_is_none(self, tmp_path):
        assert _recipe(tmp_path).install is None

    def test_script_is_required(self, tmp_path):
        with pytest.raises(SchemaError, match="install.script"):
            _recipe(tmp_path, install="install:\n  cache: v1.0.0\n")

    @pytest.mark.parametrize("bad", ["/etc/evil.sh", "../outside/install.sh"])
    def test_script_must_stay_inside_the_recipe_dir(self, tmp_path, bad):
        with pytest.raises(SchemaError, match="relative path inside the recipe dir"):
            _recipe(tmp_path, install=f"install:\n  script: {bad}\n")

    @pytest.mark.parametrize("bad", ["latest", "main", "HEAD", "master", "node:latest", "pkg@latest"])
    def test_floating_cache_key_is_rejected(self, tmp_path, bad):
        """A cache keyed by a MOVING ref never refreshes — it would pin the user to whatever the
        ref meant on the day the cache was first populated. `_FLOATING_REF_RE` alone does not catch
        the BARE forms (`main`), which is why the schema carries a second list."""
        with pytest.raises(SchemaError, match="floating ref"):
            _recipe(tmp_path, install=f"install:\n  script: install.sh\n  cache: {bad!r}\n")

    def test_cache_key_must_be_a_single_path_segment(self, tmp_path):
        with pytest.raises(SchemaError, match="bare ref"):
            _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: 'a/b'\n")

    def test_unknown_install_field_is_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown field"):
            _recipe(tmp_path, install="install:\n  script: install.sh\n  scriptt: x\n")

    def test_install_is_a_known_top_level_field(self, tmp_path):
        """Strict mode rejects unknown top-level keys — `install` must be in the allowlist or every
        migrated recipe fails to load."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        assert r.install is not None  # loaded with strict=True


class TestEnvContract:
    """The contract downstream recipe authors code against."""

    KEYS = {
        "HARNESS",
        "HARNESSED_MODE",
        "HARNESSED_RECIPE_DIR",
        "HARNESSED_CONFIG_DIR",
        "HARNESSED_INSTALL_CACHE",
        "HARNESSED_BIN_DIR",   # portable destination for an executable (bd harnessed-8px.7)
        "HARNESSED_HOME_SHIM",  # stable $HOME whose .claude is the config dir (bd harnessed-8px.9)
    }

    def test_identical_keys_in_both_modes(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        host = emit.install_env(r, mode="host", harness="claude", config_dir="/h", cache_dir="", bin_dir="/hbin", home_shim="/hshim")
        ctr = emit.install_env(r, mode="container", harness="claude", config_dir="/c", cache_dir="", bin_dir="/cbin", home_shim="/cshim")
        assert set(host) == set(ctr) == self.KEYS

    def test_recipe_dir_is_the_catalog_dir_on_host_and_the_copy_target_in_container(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        host = emit.install_env(r, mode="host", harness="claude", config_dir="/h", cache_dir="", bin_dir="/hbin", home_shim="/hshim")
        ctr = emit.install_env(r, mode="container", harness="claude", config_dir="/c", cache_dir="", bin_dir="/cbin", home_shim="/cshim")
        assert host["HARNESSED_RECIPE_DIR"] == str(r.root)
        assert ctr["HARNESSED_RECIPE_DIR"] == f"{emit.CTR_RECIPE_DIR}/r"

    def test_project_vars_are_absent_by_design(self, tmp_path):
        """Install runs at BUILD time container-side — no project is mounted, so PROJECT_DIR is
        unknowable. Exporting it host-side ONLY would give authors a var that works on host and
        silently expands to empty in a build: the exact mode-asymmetry this epic removes. A script
        needing project context belongs in `setup.script`, whose phase has one."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        env = emit.install_env(r, mode="host", harness="claude", config_dir="/h", cache_dir="", bin_dir="/hbin", home_shim="/hshim")
        for absent in ("PROJECT_DIR", "MAIN_REPO_DIR", "HOST_WORKSPACE_DIR",
                       "HARNESSED_PROJECT_DIR"):
            assert absent not in env

    def test_recipe_dir_agrees_with_the_setup_script_mount(self):
        """`$HARNESSED_RECIPE_DIR` must name ONE container path whether the recipe dir arrived by
        install's build-time COPY or setup's runtime bind-mount."""
        assert setupenv._CTR_RECIPE_DIR == emit.CTR_RECIPE_DIR


class TestContainerExecutor:
    """The container half of the install contract.

    It used to be emitted as Dockerfile RUN layers; since bd harnessed-8px.21.4 it is executed at
    container runtime into per-stack volumes by `launcher._run_container_installs`. Every invariant
    below MOVED with it — none was dropped — so these assert against the podman argv the executor
    builds rather than against emitted Dockerfile text.
    """

    def _argv(self, tmp_path, recipes, monkeypatch):
        """Capture the podman command lines the executor would run."""
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        monkeypatch.setattr(
            launcher.paths, "install_cache_dir",
            lambda name, key: tmp_path / "cache" / name / key,
        )
        launcher._run_container_installs(
            "podman", "s", "claude", "img", recipes, "cfgvol", "toolsvol",
        )
        return calls

    def _install_argv(self, tmp_path, recipes, monkeypatch):
        return [c for c in self._argv(tmp_path, recipes, monkeypatch) if "install.sh" in " ".join(c)]

    def test_bind_mounts_the_recipe_dir_and_runs_the_script(self, tmp_path, monkeypatch):
        """A bind mount replaces the build's COPY — there is no build context at runtime, and the
        recipe dir is already on the host."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        assert f"{r.root}:{emit.CTR_RECIPE_DIR}/r:ro" in cmd
        assert f"{emit.CTR_RECIPE_DIR}/r/install.sh" in cmd

    def test_runs_as_the_unprivileged_user(self, tmp_path, monkeypatch):
        """An install writes to ~/.claude and needs no root. Anything that DOES stays in the recipe
        Dockerfile and is declared via `install.system`. The image's own USER is `harnessed`, so the
        executor must never override it."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        assert "--user" not in cmd and "-u" not in cmd

    def test_contract_never_persists_into_the_shipped_image(self, tmp_path, monkeypatch):
        """`ENV HARNESSED_MODE=container` would leak build-phase inputs into the running agent's
        environment. Passed with `-e` to a throwaway container, they die with it — and the derived
        Dockerfile carries no trace of them at all."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        assert "HARNESSED_MODE=container" in cmd
        prof = tmp_path / "prof"
        prof.mkdir(exist_ok=True)
        dockerfile = emit.write_derived_dockerfile(
            prof, "s", "claude", [r]
        ).read_text()
        assert "HARNESSED_MODE" not in dockerfile
        assert "HARNESSED_CONFIG_DIR" not in dockerfile

    def test_config_dir_is_the_container_claude_dir(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        assert "HARNESSED_CONFIG_DIR=/home/harnessed/.claude" in cmd

    def test_cache_dir_is_the_shared_host_cache_and_PERSISTS(self, tmp_path, monkeypatch):
        """INVERTED by bd harnessed-8px.21.4, deliberately. The build had to throw its cache away
        (`rm -rf` in the same layer) or the clone shipped inside the image. A runtime install has no
        layer to bake, so it mounts the SAME persistent host cache the host executor uses — which is
        what finally makes the cache shared ACROSS stacks."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: v6.0.3\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        ctr = f"{emit.CTR_INSTALL_CACHE}/r/v6.0.3"
        assert f"{tmp_path / 'cache' / 'r'}:{emit.CTR_INSTALL_CACHE}/r:rw" in cmd
        assert f"HARNESSED_INSTALL_CACHE={ctr}" in cmd
        assert not any("rm -rf" in a for a in cmd)

    def test_cache_MISS_still_mounts_an_existing_source(self, tmp_path, monkeypatch):
        """bd harnessed-5ie. A miss is "the leaf does not exist" (paths.install_cache_dir), and that
        is the state of EVERY new recipe and every bumped pin. podman statfs's a bind source before
        the script runs, so mounting the leaf failed the build outright:

            Error: statfs …/.cache/harnessed/install/r/v6.0.3: no such file or directory

        Mounting the PARENT fixes it without touching the miss semantics — and mkdir-ing the leaf
        would NOT have, since every shipped cache script uses `[ ! -d "$leaf" ]` as its miss test
        and an empty leaf would read as a permanent hit that installs nothing."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: v6.0.3\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        leaf = tmp_path / "cache" / "r" / "v6.0.3"
        assert not leaf.exists(), "the leaf must stay absent — its absence IS the cache miss"
        sources = [a.split(":")[0] for a in cmd if a.count(":") == 2 and a.endswith(":rw")]
        assert str(leaf.parent) in sources
        for src in sources:
            assert Path(src).is_dir(), f"podman would statfs-fail on a missing bind source: {src}"

    def test_cache_partial_sibling_lands_on_the_same_mount_as_the_leaf(self, tmp_path, monkeypatch):
        """The scripts populate `<leaf>.partial.$$` and rename it onto `<leaf>` so an interrupted
        fetch can never be mistaken for a populated cache. That rename is only atomic while both
        paths sit on one mount — a leaf mount would have made it a cross-device rename onto a busy
        mountpoint."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: v6.0.3\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        ctr_leaf = f"{emit.CTR_INSTALL_CACHE}/r/v6.0.3"
        targets = [a.split(":")[1] for a in cmd if a.count(":") == 2 and a.endswith(":rw")]
        assert any(
            t == str(PurePosixPath(ctr_leaf).parent) for t in targets
        ), "the leaf's parent must be the mount point, so leaf and `<leaf>.partial` share it"

    def test_no_cache_declared_means_empty_cache_var_and_no_mount(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        cmd = self._install_argv(tmp_path, [r], monkeypatch)[0]
        assert "HARNESSED_INSTALL_CACHE=" in cmd
        assert not any(emit.CTR_INSTALL_CACHE in a for a in cmd)

    def test_runs_for_a_recipe_with_no_dockerfile(self, tmp_path, monkeypatch):
        """The whole point of the epic: a recipe migrates OFF its Dockerfile entirely."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        assert not (r.root / "Dockerfile").exists()
        assert self._install_argv(tmp_path, [r], monkeypatch)

    def test_nothing_runs_without_an_install_block(self, tmp_path, monkeypatch):
        assert not self._argv(tmp_path, [_recipe(tmp_path)], monkeypatch)

    def test_every_step_uses_keep_id(self, tmp_path, monkeypatch):
        """bd harnessed-8px.21.1. The pod is created with `paths.USERNS_ARG` and the agent inherits
        it as a pod member. A volume populated under any OTHER mapping is unreadable by the agent:
        uid 1000 sees the files as owner 999 and every write EACCESes.

        The mapping the pod uses is pinned to the image uid (bd harnessed-rv2.1), so the assertion
        is that this step MATCHES THE POD — which is what it always meant — rather than that it
        carries one particular spelling."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n", extra='tools: ["npm:x@1"]\n')
        for cmd in self._argv(tmp_path, [r], monkeypatch):
            assert paths.USERNS_ARG in cmd

    def test_both_volumes_are_mounted_on_every_step(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        for cmd in self._argv(tmp_path, [r], monkeypatch):
            assert "cfgvol:/home/harnessed/.claude" in cmd
            assert "toolsvol:/home/harnessed/.local" in cmd


class TestHostExecutor:
    def _run(self, tmp_path, recipe, monkeypatch, home=None):
        home = home or tmp_path / "home"
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [recipe]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        return home

    def test_runs_the_same_file_the_build_runs(self, tmp_path, monkeypatch):
        r = _recipe(
            tmp_path, install="install:\n  script: install.sh\n",
            script_body='set -eu\nmkdir -p "$HARNESSED_CONFIG_DIR/skills"\n'
                        'echo "$HARNESS/$HARNESSED_MODE" > "$HARNESSED_CONFIG_DIR/skills/marker"\n',
        )
        home = self._run(tmp_path, r, monkeypatch)
        assert (home / "skills" / "marker").read_text().strip() == "claude/host"

    def test_inherited_claude_config_dir_cannot_redirect_an_install(self, tmp_path, monkeypatch):
        """bd harnessed-8px.26.

        `_launch_host` exports CLAUDE_CONFIG_DIR for the agent, so launching a stack from inside
        another stack's host session used to hand that value straight to every install script. An
        upstream installer honours it over both $HARNESSED_CONFIG_DIR and the $HOME shim, so the
        install wrote into the PARENT stack's home. Observed for real: 69 skills plus four
        top-level artifacts landing in an unrelated stack's config dir.
        """
        foreign = tmp_path / "another-stacks-home"
        foreign.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(foreign))
        r = _recipe(
            tmp_path, install="install:\n  script: install.sh\n",
            script_body='set -eu\nmkdir -p "$CLAUDE_CONFIG_DIR/skills"\n'
                        'echo landed > "$CLAUDE_CONFIG_DIR/skills/marker"\n',
        )
        home = self._run(tmp_path, r, monkeypatch)
        assert (home / "skills" / "marker").exists(), \
            "install did not land in this stack's own home"
        assert not (foreign / "skills").exists(), \
            "install escaped into the config dir inherited from the launching process"

    def test_recipe_dir_lets_a_script_cp_where_a_dockerfile_copied(self, tmp_path, monkeypatch):
        r = _recipe(
            tmp_path, install="install:\n  script: install.sh\n",
            script_body='set -eu\ncp "$HARNESSED_RECIPE_DIR/payload.txt" "$HARNESSED_CONFIG_DIR/"\n',
        )
        (r.root / "payload.txt").write_text("shipped")
        home = self._run(tmp_path, r, monkeypatch)
        assert (home / "payload.txt").read_text() == "shipped"

    def test_a_failing_install_aborts_the_launch_loudly(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="exit 3\n")
        with pytest.raises(Exception) as exc:
            self._run(tmp_path, r, monkeypatch)
        assert "Exit" in type(exc.value).__name__

    def test_no_install_block_is_a_no_op(self, tmp_path, monkeypatch):
        home = self._run(tmp_path, _recipe(tmp_path), monkeypatch)
        assert not home.exists()


class TestOrderingAfterMaterialize:
    """`_materialize_host_home` does `shutil.rmtree(home)` on EVERY launch (so a removed recipe's
    files never linger). An install that ran before it would have its output deleted — with no
    error, which is precisely how harnessed-8px.1 presented."""

    def test_materialize_wipes_whatever_preceded_it(self, tmp_path):
        """The property that forces the ordering, asserted directly rather than assumed."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        (prof / ".claude").mkdir(parents=True)
        home.mkdir()
        (home / "installed-too-early").write_text("x")
        launcher._materialize_host_home(prof, home)
        assert not (home / "installed-too-early").exists()

    def test_launch_host_installs_after_materialize_and_before_setup(self):
        # The ordering now lives in the backend seam: the sequencer orders the contract operations,
        # and HostBackend.provision_tools orders the two phases against each other.
        src = inspect.getsource(launcher._launch_host)
        assert src.index("backend.materialize_config(") < src.index(
            "backend.provision_tools(spec, FIRST_START)"
        ), (
            "installs must run AFTER _materialize_host_home (via materialize_config) or their "
            "output is rmtree'd"
        )
        assert src.index("backend.provision_tools(spec, FIRST_START)") < src.index(
            "backend.provision_tools(spec, ATTACH)"
        ), "install bakes the content that setup then configures"
        phases = inspect.getsource(launcher.HostBackend.provision_tools)
        assert phases.index("_host_run_installs(") < phases.index("_host_run_setups("), (
            "install bakes the content that setup then configures"
        )

    def test_output_survives_a_real_materialize_install_sequence(self, tmp_path, monkeypatch):
        """End to end over the two functions in the launcher's order."""
        prof, home = tmp_path / "prof", tmp_path / "home"
        (prof / ".claude" / "skills").mkdir(parents=True)
        (prof / ".claude" / "skills" / "declarative").write_text("from the assembler")
        r = _recipe(
            tmp_path, install="install:\n  script: install.sh\n",
            script_body='set -eu\nmkdir -p "$HARNESSED_CONFIG_DIR/skills"\n'
                        'touch "$HARNESSED_CONFIG_DIR/skills/from-install"\n',
        )
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._materialize_host_home(prof, home)
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "skills" / "from-install").exists()   # the install's own output
        assert (home / "skills" / "declarative").exists()    # and it did not clobber the profile


class TestCache:
    """A per-launch re-run is mandatory (the home is rebuilt each launch), so the SOURCE must be
    cached or every launch re-pays the clone. Safe only because the key is a pinned ref."""

    INSTALL = "install:\n  script: install.sh\n  cache: v6.0.3\n"
    # Cache MISS is "the dir does not exist". Populate it, then copy out of it — and count clones.
    BODY = (
        'set -eu\n'
        'if [ ! -d "$HARNESSED_INSTALL_CACHE" ]; then\n'
        '  mkdir -p "$HARNESSED_INSTALL_CACHE"\n'
        '  echo payload > "$HARNESSED_INSTALL_CACHE/content"\n'
        '  echo miss >> "$HARNESSED_CONFIG_DIR/log"\n'
        'else\n'
        '  echo hit >> "$HARNESSED_CONFIG_DIR/log"\n'
        'fi\n'
        'cp "$HARNESSED_INSTALL_CACHE/content" "$HARNESSED_CONFIG_DIR/content"\n'
    )

    def test_miss_then_hit_across_launches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        r = _recipe(tmp_path, install=self.INSTALL, script_body=self.BODY)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        home = tmp_path / "home"
        home.mkdir()

        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "log").read_text().split() == ["miss"]
        assert (home / "content").read_text().strip() == "payload"

        # Second launch: the home is wiped, the cache is not. The install re-runs and must HIT.
        launcher._materialize_host_home(tmp_path / "empty-prof", home)
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "log").read_text().split() == ["hit"]
        assert (home / "content").read_text().strip() == "payload"

    def test_cache_lives_under_xdg_cache_home_keyed_by_recipe_and_ref(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert paths.install_cache_dir("superpowers", "v6.0.3") == (
            tmp_path / "cache" / "harnessed" / "install" / "superpowers" / "v6.0.3"
        )

    def test_bumping_the_pin_yields_a_fresh_cache_dir(self, tmp_path, monkeypatch):
        """An upgrade can never read stale content: the key IS the version."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert paths.install_cache_dir("r", "v1.0.0") != paths.install_cache_dir("r", "v2.0.0")

    def test_harnessed_creates_only_the_parent_so_existence_is_the_miss_test(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        r = _recipe(tmp_path, install=self.INSTALL,
                    script_body='set -eu\ntest ! -d "$HARNESSED_INSTALL_CACHE"\n'
                                'test -d "$(dirname "$HARNESSED_INSTALL_CACHE")"\n')
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")

    def test_no_cache_declared_hands_the_script_an_empty_string(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body='test -z "$HARNESSED_INSTALL_CACHE"\n')
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")


class TestLint:
    """`validate_pin` and `validate_no_raw_npm` read Dockerfile TEXT and a fixed recipe key list.
    `install:` moves exactly the commands they police into a .sh file. Without this gate, pin
    enforcement silently stops for every migrated recipe — the same hole `validate_setup_script`
    was added to close."""

    def test_floating_ref_in_an_install_script_is_rejected(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="git clone --branch main https://example.com/x.git /tmp/x\n")
        with pytest.raises(PinValidationError, match="floating ref"):
            validate_install_script(r)

    def test_at_latest_in_an_install_script_is_rejected(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="pnpm add -g some-tool@latest\n")
        with pytest.raises(PinValidationError, match="floating ref"):
            validate_install_script(r)

    def test_raw_npm_in_an_install_script_is_rejected(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="npm install -g some-tool@1.2.3\n")
        with pytest.raises(RecipeLintError, match="pnpm install"):
            validate_install_script(r)

    def test_raw_npx_in_an_install_script_is_rejected(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="npx some-tool@1.2.3\n")
        with pytest.raises(RecipeLintError, match="pnpm dlx"):
            validate_install_script(r)

    def test_comments_do_not_self_trigger(self, tmp_path):
        """Same carve-out `validate_pin` makes: a comment explaining the :latest convention must not
        trip the gate that forbids it."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body="# never use --branch main or @latest here\ngit clone -b v1.0.0 u d\n")
        validate_install_script(r)

    def test_missing_script_file_is_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\ninstall:\n  script: nope.sh\n")
        with pytest.raises(RecipeLintError, match="not found"):
            validate_install_script(load_recipe(d, strict=True))

    def test_pinned_ref_passes(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: v6.0.3\n",
                    script_body='git clone --depth 1 --branch "v6.0.3" https://x/y.git /tmp/y\n')
        validate_install_script(r)

    def test_assemble_wires_the_gate(self):
        """A lint nobody calls is not a lint."""
        from harnessed import assemble as _asm
        assert "validate_install_script(recipe)" in inspect.getsource(_asm.assemble)


class TestSystemLevelHostPolicy:
    """DECISION: documented skip, announced LOUDLY — not a hard failure, and never a silent one.

    Loud-fail was rejected: `mikes-universal-setup` (a COPY into /usr/local/bin) sits in the user's
    default stack, so refusing the launch would make `--host` unusable for the stacks that most need
    it. A silent skip was never on the table — that is verbatim how harnessed-8px.1 happened. So the
    system-level part stays in the recipe Dockerfile (containers get it), and the host launch prints
    the recipe name plus the author's own reason string and continues. harnessed never sudos.
    """

    INSTALL = ("install:\n  script: install.sh\n"
               "  system: 'apt-get install cmake pkg-config (needs root)'\n")

    def _capture(self, tmp_path, monkeypatch, capsys, body="true\n"):
        r = _recipe(tmp_path, "sysrecipe", install=self.INSTALL, script_body=body)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")
        return _plain(capsys.readouterr().err)

    def test_warns_naming_the_recipe_and_the_authors_reason(self, tmp_path, monkeypatch, capsys):
        # Substring checks are token-sized: rich styles the output and soft-wraps at the terminal
        # width, so a long phrase can arrive with a newline through the middle of it.
        err = self._capture(tmp_path, monkeypatch, capsys)
        assert "WARNING" in err and "SKIPPED" in err
        assert "sysrecipe" in err    # the recipe is NAMED
        assert "cmake" in err        # the author's own reason string is reproduced

    def test_launch_continues_and_the_portable_half_still_runs(self, tmp_path, monkeypatch, capsys):
        self._capture(tmp_path, monkeypatch, capsys,
                      body='touch "$HARNESSED_CONFIG_DIR/portable-part-ran"\n')
        assert (tmp_path / "home" / "portable-part-ran").exists()

    def test_no_warning_when_nothing_needs_root(self, tmp_path, monkeypatch, capsys):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")
        assert "WARNING" not in capsys.readouterr().err

    def test_system_must_explain_itself(self, tmp_path):
        """An empty marker would be a skip with no explanation — half a silent skip."""
        with pytest.raises(SchemaError, match="non-empty string"):
            _recipe(tmp_path, install="install:\n  script: install.sh\n  system: ''\n")


class TestPrecedence:
    """THREE env sources now reach an install script: the inherited environment, the recipe's own
    `env:`, and the harnessed-owned install contract. Precedence is declared EXPLICITLY and must be
    IDENTICAL in both modes — the defect the harnessed-0tk.7 × harnessed-8px.2 merge exposed was two
    self-consistent branches that together inverted precedence between host and container.

    Winner in both: the harnessed-owned contract. Asserted as ORDER, not as values.
    """

    def test_container_applies_the_contract_after_recipe_env(self, tmp_path, monkeypatch):
        """Since bd harnessed-8px.21.4 the container executor merges `{**recipe_env, **contract}`
        and passes the result as `-e`, so this can assert the VALUE rather than the ordering of two
        Dockerfile lines — a stricter check than the emitted-text version it replaces."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  HARNESSED_MODE: "recipe-tried-to-win"\n')
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        launcher._run_container_installs(
            "podman", "s", "claude", "img", [r], "cfgvol", "toolsvol",
        )
        cmd = calls[0]
        assert "HARNESSED_MODE=container" in cmd
        assert "HARNESSED_MODE=recipe-tried-to-win" not in cmd

    def test_host_applies_the_contract_after_recipe_env(self):
        src = inspect.getsource(launcher._host_run_installs)
        assert src.index("env.update(recipe_env)") < src.index("emit.install_env("), (
            "the harnessed-owned contract must be applied LAST so it wins, matching container mode"
        )

    def test_host_contract_actually_wins_over_recipe_env(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  HARNESSED_MODE: "recipe-tried-to-win"\n',
                    script_body='set -eu\necho "$HARNESSED_MODE" > "$HARNESSED_CONFIG_DIR/mode"\n')
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        home = tmp_path / "home"
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "mode").read_text().strip() == "host"

    def test_recipe_env_still_beats_the_inherited_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RECIPE_DECLARED", "inherited-wrong")
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  RECIPE_DECLARED: "from-the-recipe"\n',
                    script_body='set -eu\necho "$RECIPE_DECLARED" > "$HARNESSED_CONFIG_DIR/v"\n')
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [r]))
        home = tmp_path / "home"
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "v").read_text().strip() == "from-the-recipe"


class TestSuperpowersMigrated:
    """The proving consumer, and the recipe whose absence IS bd harnessed-8px.1."""

    def test_declares_install_with_a_derived_cache_and_no_dockerfile(self):
        r = load_recipe(CATALOG / "recipes" / "superpowers", strict=True)
        assert r.install is not None and r.install.script == "install.sh"
        # The cache key is DERIVED from `install.refs:` now (Phase 3 of #329), not declared as the
        # tag. Asserting the literal "v6.0.3" here would pin the TEST to a version the manifest is
        # free to bump — the drift this epic removes, re-created in the test suite.
        assert r.install.cache and r.install.cache == derived_cache_key(r.install.refs)
        assert r.install.system is None  # pure Markdown under ~/.claude — nothing needs root
        assert not (r.root / "Dockerfile").exists(), (
            "the Dockerfile RUN is what made the skills container-only"
        )

    def test_the_pin_exists_in_exactly_one_place(self):
        """Was: assert the script's `SUPERPOWERS_REF=` literal equals `install.cache`.

        That guarded a drifting PAIR. Phase 3 deleted the pair — the ref lives only in
        `install.refs:` and reaches the script as env — so the successor guarantee is that no copy
        exists to drift: the version appears nowhere in the script, comments included, and the
        script actually reads both variables it is given.
        """
        r = load_recipe(CATALOG / "recipes" / "superpowers", strict=True)
        assert r.install is not None and r.install.script
        raw = (r.root / r.install.script).read_text()
        # Two different rules, deliberately. A local ASSIGNMENT is checked against code only — the
        # comment explaining what was removed may name `SUPERPOWERS_REF` without recreating it. A
        # VALUE is checked against the raw file, comments included, because a comment carrying the
        # version drifts exactly like an assignment does (learned the hard way in #352).
        code = "\n".join(
            ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")
        )
        assert "SUPERPOWERS_REF=" not in code
        for key, ref in r.install.refs.items():
            assert ref.ref not in raw and ref.repo not in raw
            assert f"HARNESSED_REF_{key.upper()}" in raw
            assert f"HARNESSED_REPO_{key.upper()}" in raw

    def test_passes_the_install_lint(self):
        validate_install_script(load_recipe(CATALOG / "recipes" / "superpowers", strict=True))

    def test_no_recipe_dockerfile_delivers_content_via_claude_dir(self):
        """Replaces the old `_merge_baked_extensions` gate assertion (bd harnessed-8px.7).

        That pass copied image-baked ~/.claude content back out into the profile, because the
        profile bind-mount would hide it. It is deleted: content goes through `install:`, which
        writes $HARNESSED_CONFIG_DIR in both modes. Deleting a safety net silently would just move
        the failure, so the invariant it protected is asserted directly instead — no recipe
        Dockerfile may reference ~/.claude at all.
        """
        offenders = []
        for recipe_yaml in sorted((CATALOG / "recipes").glob("*/recipe.yaml")):
            r = load_recipe(recipe_yaml.parent, strict=True)
            dockerfile = r.root / "Dockerfile"
            if not dockerfile.is_file():
                continue
            try:
                validate_no_claude_writes(r, dockerfile.read_text(encoding="utf-8"))
            except RecipeLintError:
                offenders.append(r.name)
        assert offenders == [], (
            f"recipe Dockerfiles referencing ~/.claude: {offenders}. That content is invisible to a "
            "host launch and hidden by the bind-mount in a container — deliver it from install.script."
        )




class TestGstackMigrated:
    """Phase 3 unit 3 of #329 — the STRADDLER, and the first recipe ref to carry a `hold:`.

    caveman and superpowers are Class A: upstream publishes releases, `_github_releases` resolves
    the tag, and AC-2 counts them *resolvable*. `garrytan/gstack` publishes **0 releases and 0
    tags**, so there is nothing for any resolver to return. That makes its hold **structural**
    rather than policy — lifting #240's hold policy would change nothing — and AC-2 requires the
    reason string to say which of the two it is, so a future reader cannot "fix" a hold that is not
    fixable.

    gstack also keeps its Dockerfile, because one step needs root. That half is asserted in
    test_install_migration_content.py::TestGstackStraddles, which this class deliberately does not
    duplicate.
    """

    def _recipe(self):
        return load_recipe(CATALOG / "recipes" / "gstack", strict=True)

    def test_declares_the_ref_once_as_data(self):
        r = self._recipe()
        assert r.install is not None and r.install.script == "install.sh"
        assert list(r.install.refs) == ["gstack"]
        ref = r.install.refs["gstack"]
        assert ref.repo == "garrytan/gstack"
        # A FULL 40-char SHA. An abbreviated one is not a stable identifier, and upstream offers no
        # tag to prefer over it.
        assert len(ref.ref) == 40 and re.fullmatch(r"[0-9a-f]{40}", ref.ref)

    def test_the_hold_names_its_class_and_the_fact_behind_it(self):
        """AC-2: "held" alone is not a stated reason.

        `structural` is the word that stops a future reader lifting this. It is not decorative —
        the reason must also carry the FACT that makes it structural, because a class name with no
        evidence behind it is just a different unexplained label.
        """
        r = self._recipe()
        assert r.install is not None
        hold = r.install.refs["gstack"].hold
        assert hold and "structural" in hold.lower()
        assert "release" in hold.lower() and "tag" in hold.lower()

    def test_the_cache_key_is_derived_rather_than_declared(self):
        """The manifest must not declare `cache:` at all — the value comes from `refs:`.

        Adversarial review killed the first version of this test, correctly. It asserted
        `install.cache == derived_cache_key(install.refs)`, but `_parse_install` ASSIGNS
        `cache = derived_cache_key(refs)`, so that compared the function to itself: a wrong-but
        deterministic derivation (bad byte order, wrong separator, off-by-one truncation) satisfied
        both sides. Asserting the literal digest is not the fix either — that pins this test to a
        value the manifest is free to bump, which is the drift this epic exists to remove, recreated
        in the suite.

        What is left is what this test can actually prove: the manifest declares no cache, the key
        is populated, and the derivation genuinely consumes the ref. The derivation's own
        CORRECTNESS is pinned by the golden vector in tests/test_install_refs.py, which is where a
        constant belongs.
        """
        r = self._recipe()
        assert r.install is not None
        manifest = (r.root / "recipe.yaml").read_text(encoding="utf-8")
        assert not re.search(r"^\s*cache:", manifest, re.M), (
            "install.cache must be DERIVED from refs, never declared — declaring both is a schema "
            "error, not a precedence rule"
        )
        assert r.install.cache
        # The non-vacuous half: bump the ref and the key must move. A derivation that ignored the
        # ref would return the same digest here and leave an upgrade reading stale cached content.
        bumped = {
            k: InstallRef(repo=v.repo, ref="0" * 40, hold=v.hold)
            for k, v in r.install.refs.items()
        }
        assert derived_cache_key(bumped) != r.install.cache

    def test_the_pin_exists_in_exactly_one_place(self):
        """Was: `GSTACK_REF=` in install.sh kept equal to `install.cache` by a comment.

        That guarded a drifting PAIR. There is no pair left, so the successor guarantee is that no
        copy exists to drift.
        """
        r = self._recipe()
        assert r.install is not None and r.install.script
        raw = (r.root / r.install.script).read_text()
        # Two different rules, deliberately (the #352 lesson). A local ASSIGNMENT is checked against
        # CODE only — a comment may name `GSTACK_REF` while explaining that it was removed. A VALUE
        # is checked against the RAW file, comments included, because a comment carrying the SHA
        # drifts exactly like an assignment does, only more quietly.
        code = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
        assert "GSTACK_REF=" not in code
        for key, ref in r.install.refs.items():
            assert ref.ref not in raw and ref.repo not in raw
            assert f"HARNESSED_REF_{key.upper()}" in raw
            assert f"HARNESSED_REPO_{key.upper()}" in raw

    @pytest.mark.parametrize("missing", ["HARNESSED_REF_GSTACK", "HARNESSED_REPO_GSTACK"])
    def test_an_absent_ref_aborts_before_it_fetches_anything(self, tmp_path, missing):
        """The `:?` contract, executed rather than asserted about.

        An unset ref means the manifest and the script disagree about the key name. A default would
        paper over that by fetching the default branch — a floating fetch wearing a pinned recipe's
        clothes. This runs the real script with the variable missing and requires it to die naming
        the variable, before any network call.

        Parametrized because adversarial review caught the first version asserting only the FIRST
        guard: it supplied neither variable, and since the guards are sequential the script died on
        `HARNESSED_REF_GSTACK` and never reached the other one. Deleting the `HARNESSED_REPO_GSTACK`
        guard outright would have left that test green, while a caller supplying a ref and no repo
        got `https://github.com/.git` instead of a named abort. Each guard now has to earn its own
        pass. Empty-not-just-unset is the case that matters most in practice — an install env that
        carries the key with an empty value is what a manifest/script key-name mismatch actually
        produces — and `:?` fires on both, which is why this passes the empty string rather than
        dropping the key.
        """
        r = self._recipe()
        assert r.install is not None and r.install.script
        script = r.root / r.install.script
        # Built from the manifest, never typed in: a literal copy of the pin HERE would be the same
        # drift defect this unit deletes, just relocated into the suite.
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "HARNESSED_CONFIG_DIR": str(tmp_path / "config"),
            **emit.install_env(r, harness="claude", mode="host",
                               config_dir=str(tmp_path / "config"),
                               cache_dir="", bin_dir=str(tmp_path / "bin"),
                               home_shim=str(tmp_path / "shim")),
        }
        env[missing] = ""
        proc = subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode != 0
        assert missing in proc.stderr
        # It must not have got as far as writing anything.
        assert not (tmp_path / "config").exists()

    def test_passes_the_install_lint(self):
        # The fetch-by-SHA gate (#355) resolves `$HARNESSED_REF_GSTACK` BY NAME against the declared
        # ref. gstack is that gate's first real catalog consumer, so this is asserted, not assumed.
        validate_install_script(self._recipe())

    def test_the_script_declares_no_version_of_its_own(self):
        """AC-4 — `install.sh` performs no version-bearing download whose version it declares itself.

        Asserted through the scanner `harnessed update` itself uses to find literal pins in a
        script, rather than by a second regex written here: a private copy of the rule would agree
        with my reading of it forever, including after the real one changes.
        """
        r = self._recipe()
        assert r.install is not None and r.install.script
        script = r.root / r.install.script
        literals = update._opaque_pins_from_text(
            script.read_text(encoding="utf-8"),
            recipe="gstack", path=script, note="", hold=None,
        )
        assert [p.spec for p in literals] == []

    def test_the_cache_address_is_stable_across_loads(self):
        """Phase 3 acceptance: the derived key "still hits on a second launch".

        A second launch re-reads the manifest from disk and recomputes the key. If that key moved,
        every launch would be a miss and the cache would be write-only. This proves the ADDRESS is
        stable and that it is the leaf the host executor builds its path from; it cannot prove a
        real second launch found the directory populated, which needs a build.
        """
        first = self._recipe()
        second = self._recipe()
        assert first.install is not None and second.install is not None
        key = first.install.cache
        assert key and key == second.install.cache
        # The key IS the leaf, so bumping `ref:` moves the cache dir automatically rather than
        # needing a second edit someone has to remember.
        assert paths.install_cache_dir("gstack", key).name == key

    def test_every_pin_is_held_rather_than_unresolved(self):
        """AC-2's actual criterion: the unresolved list is empty.

        Before this migration gstack sat in the unresolved bucket — a bare `install.cache` with no
        `install.hold`, reported as an opaque pin no backend could answer for.

        Adversarial review killed the first version of this test, correctly. It asserted that every
        discovered `Pin` carried a `hold`, which is NOT what `update --check` computes: a
        `github`-backed pin is `resolvable`, so it skips the held branch, gets sent to the resolver,
        and — for a repo with no releases — was appended to `unresolved` with the hold never
        consulted. The test passed while the property it names failed. So it now runs the real
        bucketing with a resolver that answers the way GitHub actually answers for this repo:
        nothing.
        """
        pins = update.discover_pins(CATALOG / "recipes" / "gstack")
        assert pins, "a recipe that declares a ref must yield at least one pin"
        # The derived cache key is NOT an upstream pin — reporting it would double-count the ref it
        # is computed from and offer a bump against a digest no human can act on.
        assert "install.cache" not in [p.name for p in pins]

        report = update.build_report(
            [CATALOG / "recipes" / "gstack"],
            resolve=lambda _b, _n: [],   # 0 releases, 0 tags — the measured upstream state
            minimum_release_age_minutes=0,
        )
        assert [f.pin.name for f in report.unresolved] == []
        assert "garrytan/gstack" in [f.pin.name for f in report.held]


class TestRawDownloadsAreIntegrityAnchored:
    """bd harnessed-8px.13 — a PIN IS NOT INTEGRITY.

    `validate_pin` enforces a VERSION, which declares intent; it does not verify CONTENT. A release
    asset can be replaced and a tag can be re-pointed, and https protects transit, not the artifact.
    So any install.sh that downloads a raw archive must anchor it to CONTENT somehow.

    TWO anchors are accepted, deliberately:

      * a sha256 of the artifact, verified before extraction
      * a content-addressed URL — a full 40-hex git commit SHA (mikes-universal-setup)

    The second is not a loophole. A commit SHA pins the tree cryptographically, and demanding a
    tarball sha256 there would be actively worse: GitHub has changed archive compression before, so
    the bytes are not stable over time and a byte hash would break builds for a non-event.

    This matters more since bd harnessed-8px.21.3: the install cache is now SHARED across stacks and
    persistent, so an unverified artifact is reused rather than refetched.
    """

    DOWNLOADS_TO_FILE = re.compile(r"curl[^|\n]*\s-[oO]\b")
    SHA256_VERIFY = re.compile(r"sha256sum\s+-c")
    COMMIT_SHA = re.compile(r"\b[0-9a-f]{40}\b")

    def _scripts(self):
        return sorted((CATALOG / "recipes").glob("*/install.sh"))

    def test_at_least_one_script_downloads(self):
        """Guards the guard: if the detector silently stops matching, the sweep below passes by
        checking nothing at all."""
        assert any(
            self.DOWNLOADS_TO_FILE.search(p.read_text(encoding="utf-8")) for p in self._scripts()
        ), "no install.sh matched the download detector — the pattern has probably drifted"

    def test_every_raw_download_is_anchored(self):
        unanchored = []
        for p in self._scripts():
            body = p.read_text(encoding="utf-8")
            if not self.DOWNLOADS_TO_FILE.search(body):
                continue
            if self.SHA256_VERIFY.search(body) or self.COMMIT_SHA.search(body):
                continue
            unanchored.append(p.parent.name)
        assert not unanchored, (
            "these install.sh scripts download an artifact with neither a sha256 check nor a "
            f"content-addressed (commit-SHA) URL: {unanchored}. A version pin is not integrity."
        )

