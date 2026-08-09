"""Batch C of the `install:` migration — the node/npm and mise-backed tool recipes (bd harnessed-8px.5).

context-mode, rtk, ccstatusline, gsd-core each had a container-ONLY Dockerfile RUN. Those bodies are
now one `install.sh` per recipe, run by the build AND by a host launch. What has to hold, and is
asserted here by actually EXECUTING the scripts against stub binaries rather than reading them:

  * MODE SYMMETRY where it is possible — gsd-core and ccstatusline deliver on host too, and the
    "global" install lands in $HARNESSED_CONFIG_DIR, never the user's real ~/.claude.
  * A LOUD SKIP where it is not — context-mode's omp plugin (writes the user's own ~/.omp) and rtk's
    binary (an install.sh cannot put an executable on the host agent's PATH) warn and exit 0.
    Silence is the bug this epic exists to remove (bd harnessed-8px.1).
  * NO CONTAINER-ABSOLUTE LITERALS — ccstatusline's statusLine command is computed per mode; the old
    Dockerfile baked /home/harnessed/... into a host launch's settings.json.
  * The catalog still LINTS: pins live in the .sh now, so validate_install_script is what keeps
    `validate_pin` from going blind (it only ever read Dockerfile text).
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from harnessed.schema import load_recipe, validate_install_script

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# The batch. Every one of these had its whole Dockerfile body moved into install.sh.
MIGRATED = ["context-mode", "rtk", "ccstatusline", "gsd-core"]


def _recipe(name: str):
    return load_recipe(CATALOG / "recipes" / name, strict=True)


def _script(name: str) -> Path:
    return CATALOG / "recipes" / name / "install.sh"


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    """Drop an executable stub on a scratch PATH. Stubs record their argv + $HOME to a log file."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(0o755)
    return p


# A pnpm stub that enforces the ONE rule real pnpm enforces about global installs: its global bin dir
# is "$PNPM_HOME/bin", and that dir must be on PATH or the install hard-errors. A no-op stub cannot
# catch PNPM_HOME="$HARNESSED_BIN_DIR" (one level too deep), which is exactly what shipped and broke
# a real host launch — bd harnessed-8px.15.
_PNPM_STUB = """
if [ "$1" = "add" ] && [ "$2" = "-g" ]; then
  gbin="${PNPM_HOME:?pnpm add -g needs PNPM_HOME}/bin"
  case ":$PATH:" in
    *":$gbin:"*) ;;
    *) echo "ERROR  The configured global bin directory \"$gbin\" is not in PATH" >&2; exit 1 ;;
  esac
fi
"""


def _run(recipe: str, tmp_path: Path, *, mode: str, harness: str, cache: Path | None = None,
         stub_path: Path | None = None, config_dir: Path | None = None, home: Path | None = None):
    """Execute a recipe's install.sh under the emit.install_env contract, with a controlled PATH."""
    config_dir = config_dir or (tmp_path / "config")
    config_dir.mkdir(parents=True, exist_ok=True)
    home = home or (tmp_path / "userhome")
    home.mkdir(parents=True, exist_ok=True)
    # $HARNESSED_HOME_SHIM is a dir whose .claude IS the config dir, so an installer that only knows
    # how to write "globally" into $HOME/.claude lands in the stack's config dir. Container-side that
    # is already true of the real home, so the shim IS the home; host-side harnessed makes a stable
    # sibling and symlinks it (paths.host_home_shim). Mirrored here so the scripts see the real shape.
    if config_dir == home / ".claude":
        home_shim = home
    else:
        home_shim = tmp_path / "homeshim"
        home_shim.mkdir(parents=True, exist_ok=True)
        link = home_shim / ".claude"
        if not link.is_symlink():
            link.symlink_to(config_dir)
    bin_dir = tmp_path / "stackbin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    env = {
        # bin_dir FIRST, mirroring _host_run_installs — a script may install a tool and then use it.
        "PATH": os.pathsep.join(
            [str(bin_dir), str(stub_path or (tmp_path / "bin")), "/usr/bin", "/bin"]
        ),
        "HOME": str(home),
        # The contract — identical keys in both modes (emit.install_env).
        "HARNESS": harness,
        "HARNESSED_MODE": mode,
        "HARNESSED_RECIPE_DIR": str(CATALOG / "recipes" / recipe),
        "HARNESSED_CONFIG_DIR": str(config_dir),
        "HARNESSED_INSTALL_CACHE": str(cache) if cache else "",
        "HARNESSED_BIN_DIR": str(bin_dir),
        "HARNESSED_HOME_SHIM": str(home_shim),
    }
    return subprocess.run(
        ["bash", str(_script(recipe))], env=env, capture_output=True, text=True
    )


def _pinned_version(recipe, prefix: str) -> str:
    """The version a recipe pins for `prefix` in `tools:`, e.g. 'npm:ccstatusline@' -> '2.2.27'."""
    pins = [t for t in recipe.tools if t.startswith(prefix)]
    assert len(pins) == 1, f"expected exactly one {prefix!r} pin in {recipe.name}, got {pins}"
    version = pins[0][len(prefix):]
    # A floating ref would make the lockstep check below vacuous — two channels can agree on
    # "latest" and still install different builds an hour apart. validate_pin enforces this
    # repo-wide; asserting it here keeps THIS test honest about what it just derived.
    assert re.fullmatch(r"[0-9]+(\.[0-9]+)*", version), f"{recipe.name} pin is not a version: {version!r}"
    return version


def _assert_channels_agree(recipe, prefix: str, script_var: str) -> None:
    """A recipe with two install channels must ship ONE version through both.

    Derived from the recipe's own pin rather than restated as a literal, deliberately: a test that
    hard-codes the version has to be edited on every dependency bump, which trains people to edit
    tests to make them pass. It also tests nothing extra — the number in the test is just a second
    copy of the number in the recipe. What actually matters is that the container channel (`tools:`)
    and the host channel (install.sh) never drift apart, and that survives any bump untouched.
    """
    version = _pinned_version(recipe, prefix)
    script = _script(recipe.name).read_text()
    assert f'{script_var}="{version}"' in script, (
        f"{recipe.name}: install.sh {script_var} disagrees with the `tools:` pin ({version}) — the "
        "host and container channels would install different versions"
    )


# --- catalog shape --------------------------------------------------------------------------------

class TestMigratedRecipesDeclareInstall:
    @pytest.mark.parametrize("name", MIGRATED)
    def test_dockerfile_is_gone(self, name):
        # The whole body moved. A leftover Dockerfile would silently reintroduce the container-only
        # half of the very asymmetry this migration removes.
        assert not (CATALOG / "recipes" / name / "Dockerfile").exists()

    @pytest.mark.parametrize("name", MIGRATED)
    def test_declares_install_script_that_exists(self, name):
        r = _recipe(name)
        assert r.install is not None and r.install.script == "install.sh"
        assert _script(name).is_file()

    @pytest.mark.parametrize("name", MIGRATED)
    def test_passes_the_install_script_lint(self, name):
        # raw npm/npx and floating refs, inside the .sh where validate_pin cannot see them.
        validate_install_script(_recipe(name))

    @pytest.mark.parametrize("name", MIGRATED)
    def test_no_recipe_declares_a_system_step(self, name):
        # None of batch C needs root; a `system:` reason would be a false explanation for the two
        # host skips, which have nothing to do with privilege.
        assert _recipe(name).install.system is None

    def test_ccstatusline_declares_no_content_cache(self):
        # bd harnessed-1t4.3: `install.cache` existed only to park a host-side pnpm install somewhere
        # durable, because the config dir is wiped every launch. `tools:` installs into mise's
        # stack-scoped tree, which already outlives the wipe — so a cache here would be dead state.
        r = _recipe("ccstatusline")
        assert r.install.cache is None
        # The script no longer carries a second copy of the version to agree WITH (AC-1): it
        # resolves the binary through `command -v`, so `tools:` is the only place the pin is
        # written. Asserting the absence is the stronger property — agreement between two copies
        # can only ever be maintained, never guaranteed.
        assert "CCSTATUSLINE_VERSION" not in (r.root / "install.sh").read_text(encoding="utf-8")

    def test_context_mode_pin_matches_its_install_channels(self):
        # Two channels for the CLI: `tools:` (container, via mise npm backend) and install.sh
        # (host, via PNPM_HOME-redirected pnpm — bd harnessed-zi6.1 retired `provision:`).
        # The omp plugin in install.sh must also match. Drift means different versions across modes.
        _assert_channels_agree(_recipe("context-mode"), "npm:context-mode@", "CONTEXT_MODE_VERSION")


# --- context-mode: harness-conditional, container-only ---------------------------------------------

class TestContextModeOmpBranch:
    @pytest.mark.parametrize("harness", ["claude", "codex", "omp"])
    def test_never_touches_the_config_dir(self, tmp_path, harness):
        # install.sh installs the CLI (via pnpm) and the omp plugin; neither writes the config dir.
        # Every other layer of this recipe is declarative (tools/mcp/hooks/env/persist).
        _stub(tmp_path / "bin", "pnpm", _PNPM_STUB)  # faithful stub: enforces $PNPM_HOME/bin on PATH
        r = _run("context-mode", tmp_path, mode="host", harness=harness)
        assert r.returncode == 0
        assert list((tmp_path / "config").iterdir()) == []

    @pytest.mark.parametrize("harness", ["claude", "codex"])
    def test_non_omp_harness_is_a_silent_no_op(self, tmp_path, harness):
        # Not a skip to announce: these harnesses get the hooks instead, in BOTH modes.
        r = _run("context-mode", tmp_path, mode="container", harness=harness)
        assert r.returncode == 0
        assert r.stderr.strip() == ""

    def test_omp_container_runs_the_pinned_plugin_install(self, tmp_path):
        log = tmp_path / "omp.log"
        _stub(tmp_path / "bin", "omp", f'printf "%s\\n" "$*" >> {log}\n')
        r = _run("context-mode", tmp_path, mode="container", harness="omp")
        assert r.returncode == 0
        assert log.read_text().strip() == "plugin install context-mode@1.0.169"

    def test_omp_host_skips_the_plugin_install_loudly(self, tmp_path):
        # THE decision this recipe forced: `omp plugin install` writes ~/.omp/plugins, which is an
        # image layer in a container but the USER'S OWN omp install on a host. harnessed does not
        # write there, so the step is skipped — named, with a reason, on stderr, exit 0.
        log = tmp_path / "omp.log"
        _stub(tmp_path / "bin", "omp", f'printf "%s\\n" "$*" >> {log}\n')
        _stub(tmp_path / "bin", "pnpm", _PNPM_STUB)  # faithful stub: enforces $PNPM_HOME/bin on PATH
        r = _run("context-mode", tmp_path, mode="host", harness="omp")
        assert r.returncode == 0
        assert not log.exists()  # omp was never invoked, even though it was on PATH
        assert "context-mode" in r.stderr and "SKIPPED" in r.stderr
        assert "~/.omp/plugins" in r.stderr


# --- rtk: binary is container-only, global wiring is both -------------------------------------------

class TestRtkInstall:
    """bd harnessed-1t4.3 moved the BINARY to `tools:`; this script owns the global wiring only."""

    def test_the_script_no_longer_installs_the_binary_itself(self, tmp_path):
        # `tools: [github:rtk-ai/rtk@…]` owns it now, in both modes — so a mise call from here would
        # be a second, competing install channel.
        log = tmp_path / "mise.log"
        _stub(tmp_path / "bin", "mise", f'printf "%s\\n" "$*" >> {log}\n')
        _stub(tmp_path / "bin", "rtk", "true\n")
        assert _run("rtk", tmp_path, mode="host", harness="claude").returncode == 0
        assert not log.exists()

    def test_container_wires_globally_against_the_tools_provided_binary(self, tmp_path):
        rtk_log = tmp_path / "rtk.log"
        _stub(tmp_path / "bin", "rtk", f'printf "%s\\n" "$*" >> {rtk_log}\n')
        home = tmp_path / "ctrhome"
        r = _run("rtk", tmp_path, mode="container", harness="claude",
                 home=home, config_dir=home / ".claude")
        assert r.returncode == 0
        # `init -g`, deliberately WITHOUT `--auto-patch`: that flag also patches settings.json, and
        # the assembler regenerates that file after install.sh runs, so the patch was silently
        # dropped. The hook now comes from recipe.yaml `hooks:` instead.
        assert rtk_log.read_text().splitlines() == ["--version", "init -g"]

    def test_the_pretooluse_hook_is_declared_in_the_recipe_not_left_to_the_installer(self):
        # The hook is the whole capability: without it nothing rewrites the agent's commands and rtk
        # never fires, however healthy the binary is. It has to live in `hooks:` because the
        # assembler owns settings.json and regenerates it AFTER install.sh runs, silently dropping
        # anything the installer patched in. The live capability test (catalog/recipes/rtk/tests/
        # rtk-runs.sh) checks the ASSEMBLED result, but that one is podman-gated and skipped by
        # default — so the source of truth is asserted here, where it always runs.
        recipe = load_recipe(CATALOG / "recipes" / "rtk")
        entries = recipe.hooks.get("PreToolUse", [])
        assert [(e.command, e.matcher) for e in entries] == [("rtk hook claude", "Bash")]

    def test_a_missing_binary_fails_loudly_rather_than_wiring_nothing(self, tmp_path):
        # If `tools:` did not deliver rtk, wiring hooks that shell out to it would produce a config
        # that is broken at RUNTIME instead of at install time.
        assert _run("rtk", tmp_path, mode="host", harness="claude").returncode != 0

    def test_host_with_rtk_present_wires_into_the_stack_config_dir_not_the_user_home(self, tmp_path):
        # `rtk init -g` resolves its target from $CLAUDE_CONFIG_DIR FIRST, falling back to
        # $HOME/.claude — so redirecting $HOME alone does NOT steer it. Host-side the fallback would
        # be the user's REAL home, so the script pins BOTH. The stub mirrors that precedence exactly,
        # which is what makes this a regression test rather than a restatement of the old assumption.
        _stub(
            tmp_path / "bin", "rtk",
            'if [ "$1" = "init" ]; then\n'
            '  target="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"\n'
            '  mkdir -p "$target"; echo rtk > "$target/RTK.md"\n'
            'fi\n',
        )
        r = _run("rtk", tmp_path, mode="host", harness="claude")
        assert r.returncode == 0
        assert (tmp_path / "config" / "RTK.md").read_text().strip() == "rtk"
        assert not (tmp_path / "userhome" / ".claude").exists()


# --- gsd-core: fully host-capable content install ---------------------------------------------------

class TestGsdCoreInstall:
    def test_missing_pnpm_fails_loudly_rather_than_shipping_no_skills(self, tmp_path):
        r = _run("gsd-core", tmp_path, mode="host", harness="claude")
        assert r.returncode == 1
        assert "gsd-core" in r.stderr and "pnpm" in r.stderr

    def test_runs_the_pinned_installer_via_pnpm_dlx_not_npx(self, tmp_path):
        log = tmp_path / "pnpm.log"
        _stub(tmp_path / "bin", "pnpm", f'printf "%s\\n" "$*" >> {log}\n')
        home = tmp_path / "ctrhome"
        r = _run("gsd-core", tmp_path, mode="container", harness="claude",
                 home=home, config_dir=home / ".claude")
        assert r.returncode == 0
        # `store path` precedes the install in BOTH modes now: $HARNESSED_HOME_SHIM removed the
        # host/container branch, so the store pin runs unconditionally. Container-side it is a no-op
        # (the shim IS the real home, so it pins the store to where pnpm would have put it anyway) —
        # one cheap extra call, in exchange for the two modes running byte-identical script.
        assert log.read_text().splitlines() == [
            "store path",
            "dlx @opengsd/gsd-core@1.6.1 --claude --global",
        ]

    def test_host_global_install_lands_in_the_stack_config_dir(self, tmp_path):
        # The installer writes to os.homedir()/.claude. On a host launch that must NOT be the user's
        # real ~/.claude — the script points a throwaway $HOME at $HARNESSED_CONFIG_DIR.
        _stub(
            tmp_path / "bin", "pnpm",
            'if [ "$1" = "store" ]; then echo /tmp/fake-store; exit 0; fi\n'
            'mkdir -p "$HOME/.claude/skills/gsd-new-project"\n'
            'echo skill > "$HOME/.claude/skills/gsd-new-project/SKILL.md"\n',
        )
        r = _run("gsd-core", tmp_path, mode="host", harness="claude")
        assert r.returncode == 0
        assert (tmp_path / "config" / "skills" / "gsd-new-project" / "SKILL.md").is_file()
        assert not (tmp_path / "userhome" / ".claude").exists()


# --- ccstatusline: the resolved statusLine path -----------------------------------------------------

def _ccstatusline_on_path(tmp_path: Path) -> Path:
    """The binary `tools:` provides, wherever the mode puts it — the script must just resolve it."""
    return _stub(tmp_path / "toolshims", "ccstatusline", "echo hi\n")


class TestCcstatuslineInstall:
    """bd harnessed-1t4.3: `tools:` owns the binary in both modes, so the script records the path
    the tool RESOLVES to instead of computing a different one per mode."""

    def _run_with_tool(self, tmp_path, *, mode, harness, config_dir=None, home=None):
        shims = _ccstatusline_on_path(tmp_path).parent
        return _run("ccstatusline", tmp_path, mode=mode, harness=harness,
                    stub_path=shims, config_dir=config_dir, home=home)

    def test_the_recorded_path_is_the_resolved_binary(self, tmp_path):
        r = self._run_with_tool(tmp_path, mode="container", harness="claude")
        assert r.returncode == 0, r.stderr
        cmd = json.loads((tmp_path / "config" / "settings.json").read_text())["statusLine"]["command"]
        assert cmd == str(tmp_path / "toolshims" / "ccstatusline")
        assert os.access(cmd, os.X_OK)

    def test_the_same_script_records_a_host_resolvable_path(self, tmp_path):
        # The regression the old Dockerfile shipped: /home/harnessed/... baked into a host launch's
        # settings.json, pointing at a directory that does not exist on the host.
        r = self._run_with_tool(tmp_path, mode="host", harness="claude")
        assert r.returncode == 0, r.stderr
        cmd = json.loads((tmp_path / "config" / "settings.json").read_text())["statusLine"]["command"]
        assert not cmd.startswith("/home/harnessed")
        assert os.access(cmd, os.X_OK)

    def test_a_missing_binary_fails_loudly_rather_than_recording_a_dead_path(self, tmp_path):
        # statusLine is exec'd for the whole session; a bad path fails at RUNTIME, invisibly.
        r = _run("ccstatusline", tmp_path, mode="host", harness="claude")
        assert r.returncode != 0
        assert not (tmp_path / "config" / "settings.json").exists()

    def test_settings_merge_preserves_other_recipes_baked_keys(self, tmp_path):
        # Read-modify-write, not overwrite: install.sh runs after the profile settings.json is in
        # place (host) and alongside other recipes' baked keys (container).
        config = tmp_path / "config"
        config.mkdir()
        (config / "settings.json").write_text(json.dumps({"model": "sonnet"}))
        r = self._run_with_tool(tmp_path, mode="host", harness="claude", config_dir=config)
        assert r.returncode == 0, r.stderr
        out = json.loads((config / "settings.json").read_text())
        assert out["model"] == "sonnet"
        assert out["statusLine"]["type"] == "command"

    @pytest.mark.parametrize("harness", ["codex", "omp"])
    def test_non_claude_harness_gets_no_statusline(self, tmp_path, harness):
        # statusLine is a Claude Code concept; the binary itself is unconditional (`tools:`).
        r = self._run_with_tool(tmp_path, mode="host", harness=harness)
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "config" / "settings.json").exists()


# --- the class of bug this batch removes ------------------------------------------------------------

class TestNoContainerAbsolutePathsSurviveIntoHostMode:
    @pytest.mark.parametrize("name", MIGRATED)
    def test_no_hardcoded_harnessed_home_literal(self, name):
        # `/home/harnessed/...` in a script that also runs host-side is a path that cannot resolve
        # there. Paths must come from $HARNESSED_CONFIG_DIR / $HARNESSED_INSTALL_CACHE / $HOME.
        body = "\n".join(
            line for line in _script(name).read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        assert not re.search(r"/home/harnessed\b", body)
