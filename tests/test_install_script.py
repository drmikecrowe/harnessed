"""The `install:` mechanism — bd harnessed-8px.3.

ONE bash file per recipe, executed by BOTH the container build (`RUN bash install.sh`) and a host
launch, so the deliverables of what used to be a container-only Dockerfile RUN exist in both modes.
That asymmetry is bd harnessed-8px.1: a `--host` launch of a stack containing superpowers shipped
0 of its 14 skills and said nothing.

Four properties carry the whole design, and each has its own class below:

  * PHASE — install is BUILD-time container-side, so its env is a deliberate SUBSET of the
    folder-env contract (no PROJECT_DIR: a build has no project mounted).
  * ORDERING — host installs run AFTER `_materialize_host_home`, which rmtree's the home on every
    launch. Before it, the output is deleted milliseconds later, silently.
  * CACHE — because of that same wipe, "first launch only" is structurally impossible; the install
    runs every launch, and only a pinned-ref content cache makes that affordable.
  * LINT — moving Dockerfile RUN bodies into a .sh blinds `validate_pin` and `validate_no_raw_npm`,
    which read Dockerfile TEXT. `validate_install_script` is what keeps pin enforcement alive.
"""

import inspect
import re
from pathlib import Path

import pytest

from harnessed import emit, launcher, paths
from harnessed.schema import (
    PinValidationError,
    RecipeLintError,
    SchemaError,
    load_recipe,
    validate_install_script,
    validate_no_claude_writes,
)

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
        assert launcher._CTR_RECIPE_DIR == emit.CTR_RECIPE_DIR


class TestContainerExecutor:
    def _emit(self, tmp_path, recipes) -> str:
        prof = tmp_path / "prof"
        prof.mkdir(exist_ok=True)
        return emit.write_derived_dockerfile(
            prof, "s", "claude", recipes, with_scan=False
        ).read_text()

    def test_copies_the_recipe_dir_and_runs_the_script(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        out = self._emit(tmp_path, [r])
        assert f"COPY catalog/recipes/r {emit.CTR_RECIPE_DIR}/r" in out
        assert f"bash {emit.CTR_RECIPE_DIR}/r/install.sh" in out
        assert out.index("COPY catalog/recipes/r") < out.index("bash ")

    def test_runs_as_the_unprivileged_user(self, tmp_path):
        """An install writes to ~/.claude and needs no root. Anything that DOES stays in the
        recipe Dockerfile and is declared via `install.system`."""
        out = self._emit(tmp_path, [_recipe(tmp_path, install="install:\n  script: install.sh\n")])
        assert out.index("USER harnessed") < out.index("bash ")

    def test_contract_is_inline_on_the_run_not_persisted_as_image_env(self, tmp_path):
        """`ENV HARNESSED_MODE=container` would leak build-phase inputs into the shipped image and
        therefore into the running agent's environment. Inline assignments die with the RUN."""
        out = self._emit(tmp_path, [_recipe(tmp_path, install="install:\n  script: install.sh\n")])
        assert 'HARNESSED_MODE="container" ' in out
        assert "ENV HARNESSED_MODE" not in out
        assert "ENV HARNESSED_CONFIG_DIR" not in out

    def test_config_dir_is_the_image_claude_dir(self, tmp_path):
        out = self._emit(tmp_path, [_recipe(tmp_path, install="install:\n  script: install.sh\n")])
        assert 'HARNESSED_CONFIG_DIR="/home/harnessed/.claude"' in out

    def test_cache_dir_is_build_scratch_removed_in_the_same_layer(self, tmp_path):
        """The HOST cache persists — that is its point. The container's must not: a build layer
        that kept the clone would bake it into the shipped image."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  cache: v6.0.3\n")
        out = self._emit(tmp_path, [r])
        run = next(ln for ln in out.splitlines() if ln.startswith("RUN ") and "install.sh" in ln)
        assert "/tmp/harnessed-install-cache/r/v6.0.3" in run
        assert run.rstrip().endswith("&& rm -rf /tmp/harnessed-install-cache")

    def test_no_cache_declared_means_empty_cache_var(self, tmp_path):
        out = self._emit(tmp_path, [_recipe(tmp_path, install="install:\n  script: install.sh\n")])
        assert 'HARNESSED_INSTALL_CACHE=""' in out
        assert "rm -rf /tmp/harnessed-install-cache" not in out

    def test_emitted_for_a_recipe_with_no_dockerfile(self, tmp_path):
        """The whole point of the epic: a recipe migrates OFF its Dockerfile entirely."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        assert not (r.root / "Dockerfile").exists()
        assert "install.sh" in self._emit(tmp_path, [r])

    def test_nothing_emitted_without_an_install_block(self, tmp_path):
        out = self._emit(tmp_path, [_recipe(tmp_path)])
        assert "recipe install" not in out


class TestHostExecutor:
    def _run(self, tmp_path, recipe, monkeypatch, home=None):
        home = home or tmp_path / "home"
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [recipe]))
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
        src = inspect.getsource(launcher._launch_host)
        assert src.index("_host_launch_plan(") < src.index("_host_run_installs("), (
            "installs must run AFTER _materialize_host_home (via _host_launch_plan) or their "
            "output is rmtree'd"
        )
        assert src.index("_host_run_installs(") < src.index("_host_run_setups("), (
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
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
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
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
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
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")

    def test_no_cache_declared_hands_the_script_an_empty_string(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    script_body='test -z "$HARNESSED_INSTALL_CACHE"\n')
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
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
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
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
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
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

    def test_container_applies_the_contract_after_recipe_env(self, tmp_path):
        """Dockerfile: `ENV` lines for `env:` come first; the contract rides inline on the RUN,
        and an inline assignment beats an inherited ENV."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  HARNESSED_MODE: "recipe-tried-to-win"\n')
        prof = tmp_path / "prof"
        prof.mkdir()
        out = emit.write_derived_dockerfile(prof, "s", "claude", [r], with_scan=False).read_text()
        assert out.index('ENV HARNESSED_MODE="recipe-tried-to-win"') < out.index(
            'RUN HARNESS="claude" HARNESSED_MODE="container"'
        )

    def test_host_applies_the_contract_after_recipe_env(self):
        src = inspect.getsource(launcher._host_run_installs)
        assert src.index("env.update(recipe_env)") < src.index("emit.install_env("), (
            "the harnessed-owned contract must be applied LAST so it wins, matching container mode"
        )

    def test_host_contract_actually_wins_over_recipe_env(self, tmp_path, monkeypatch):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  HARNESSED_MODE: "recipe-tried-to-win"\n',
                    script_body='set -eu\necho "$HARNESSED_MODE" > "$HARNESSED_CONFIG_DIR/mode"\n')
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
        home = tmp_path / "home"
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "mode").read_text().strip() == "host"

    def test_recipe_env_still_beats_the_inherited_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RECIPE_DECLARED", "inherited-wrong")
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n",
                    env='env:\n  RECIPE_DECLARED: "from-the-recipe"\n',
                    script_body='set -eu\necho "$RECIPE_DECLARED" > "$HARNESSED_CONFIG_DIR/v"\n')
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [r]))
        home = tmp_path / "home"
        launcher._host_run_installs("s", tmp_path, harness="claude", home=home)
        assert (home / "v").read_text().strip() == "from-the-recipe"


class TestSuperpowersMigrated:
    """The proving consumer, and the recipe whose absence IS bd harnessed-8px.1."""

    def test_declares_install_with_a_pinned_cache_and_no_dockerfile(self):
        r = load_recipe(CATALOG / "recipes" / "superpowers", strict=True)
        assert r.install.script == "install.sh"
        assert r.install.cache == "v6.0.3"
        assert r.install.system is None  # pure Markdown under ~/.claude — nothing needs root
        assert not (r.root / "Dockerfile").exists(), (
            "the Dockerfile RUN is what made the skills container-only"
        )

    def test_the_scripts_pinned_ref_matches_the_cache_key(self):
        """A drifting pair would key the cache by one version and clone another — the cache would
        hold v6.0.3's name over v6.0.4's content, forever."""
        r = load_recipe(CATALOG / "recipes" / "superpowers", strict=True)
        body = (r.root / r.install.script).read_text()
        assert f'SUPERPOWERS_REF="{r.install.cache}"' in body

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


