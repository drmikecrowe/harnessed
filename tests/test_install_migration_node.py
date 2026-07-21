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
        "PATH": os.pathsep.join([str(stub_path or (tmp_path / "bin")), "/usr/bin", "/bin"]),
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

    def test_ccstatusline_cache_key_equals_the_pin_in_the_script(self):
        # The cache dir holds the INSTALLED package host-side, so a drifted key would serve a stale
        # binary forever (the cache never refreshes — hit is "the directory exists").
        r = _recipe("ccstatusline")
        assert r.install.cache == "2.2.22"
        assert f'CCSTATUSLINE_VERSION="{r.install.cache}"' in _script("ccstatusline").read_text()

    def test_context_mode_pin_matches_its_install_channels(self):
        # Two channels for the CLI: `tools:` (container, via mise npm backend) and install.sh
        # (host, via PNPM_HOME-redirected pnpm — bd harnessed-zi6.1 retired `provision:`).
        # The omp plugin in install.sh must also match. Drift means different versions across modes.
        r = _recipe("context-mode")
        assert 'CONTEXT_MODE_VERSION="1.0.169"' in _script("context-mode").read_text()
        assert "npm:context-mode@1.0.169" in r.tools


# --- context-mode: harness-conditional, container-only ---------------------------------------------

class TestContextModeOmpBranch:
    @pytest.mark.parametrize("harness", ["claude", "codex", "omp"])
    def test_never_touches_the_config_dir(self, tmp_path, harness):
        # install.sh installs the CLI (via pnpm) and the omp plugin; neither writes the config dir.
        # Every other layer of this recipe is declarative (tools/mcp/hooks/env/persist).
        _stub(tmp_path / "bin", "pnpm", "")  # CLI install runs first in host mode; must succeed
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
        _stub(tmp_path / "bin", "pnpm", "")  # CLI install runs first; must succeed silently
        r = _run("context-mode", tmp_path, mode="host", harness="omp")
        assert r.returncode == 0
        assert not log.exists()  # omp was never invoked, even though it was on PATH
        assert "context-mode" in r.stderr and "SKIPPED" in r.stderr
        assert "~/.omp/plugins" in r.stderr


# --- rtk: binary is container-only, global wiring is both -------------------------------------------

class TestRtkInstall:
    def test_host_without_rtk_warns_and_does_not_touch_mise(self, tmp_path):
        # `mise use -g` writes the USER'S global mise config, and install.sh has no channel for
        # putting an executable on the host agent's PATH (that is `provision:`, bd harnessed-zi6.1).
        log = tmp_path / "mise.log"
        _stub(tmp_path / "bin", "mise", f'printf "%s\\n" "$*" >> {log}\n')
        r = _run("rtk", tmp_path, mode="host", harness="claude")
        assert r.returncode == 0
        assert not log.exists()
        assert "rtk" in r.stderr and "WARNING" in r.stderr

    def test_container_installs_the_pinned_binary_then_wires_globally(self, tmp_path):
        # In a build rtk is NOT yet on PATH — `mise install` is what puts it there, so the stub
        # materializes the rtk stub the way the real backend would.
        mise_log, rtk_log = tmp_path / "mise.log", tmp_path / "rtk.log"
        rtk_bin = tmp_path / "bin" / "rtk"
        _stub(
            tmp_path / "bin", "mise",
            f'printf "%s\\n" "$*" >> {mise_log}\n'
            f"cat > {rtk_bin} <<'EOF'\n"
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> {rtk_log}\n'
            "EOF\n"
            f"chmod +x {rtk_bin}\n",
        )
        # Container: $HOME/.claude IS the config dir, so the script must call rtk init directly.
        home = tmp_path / "ctrhome"
        config = home / ".claude"
        r = _run("rtk", tmp_path, mode="container", harness="claude", home=home, config_dir=config)
        assert r.returncode == 0
        assert mise_log.read_text().splitlines() == [
            "use -g github:rtk-ai/rtk@0.43.0", "install",
        ]
        assert rtk_log.read_text().splitlines() == ["--version", "init -g --auto-patch"]

    def test_host_with_rtk_present_wires_into_the_stack_config_dir_not_the_user_home(self, tmp_path):
        # `rtk init -g` targets $HOME/.claude. Host-side that would be the user's REAL home, so the
        # script redirects $HOME at the stack's config dir. Assert on where the tool actually wrote.
        _stub(
            tmp_path / "bin", "rtk",
            'if [ "$1" = "init" ]; then\n'
            '  mkdir -p "$HOME/.claude"; echo rtk > "$HOME/.claude/RTK.md"\n'
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


# --- ccstatusline: the computed statusLine path -----------------------------------------------------

def _pnpm_installing_stub(tmp_path: Path) -> Path:
    """A `pnpm add` that materializes node_modules/.bin/ccstatusline in the cwd, as pnpm would."""
    return _stub(
        tmp_path / "bin", "pnpm",
        'mkdir -p node_modules/.bin\n'
        'printf "#!/usr/bin/env bash\\necho hi\\n" > node_modules/.bin/ccstatusline\n'
        'chmod +x node_modules/.bin/ccstatusline\n',
    )


class TestCcstatuslineInstall:
    def test_container_writes_the_mise_shim_path(self, tmp_path):
        _stub(tmp_path / "bin", "mise", "true\n")
        home = tmp_path / "ctrhome"
        shim = home / ".local" / "share" / "mise" / "shims"
        shim.mkdir(parents=True)
        (shim / "ccstatusline").write_text("#!/bin/sh\n")
        (shim / "ccstatusline").chmod(0o755)
        r = _run("ccstatusline", tmp_path, mode="container", harness="claude",
                 home=home, config_dir=home / ".claude")
        assert r.returncode == 0
        out = json.loads((home / ".claude" / "settings.json").read_text())
        assert out["statusLine"] == {
            "type": "command", "command": str(shim / "ccstatusline"),
            "padding": 0, "refreshInterval": 10,
        }

    def test_host_writes_a_host_resolvable_path_not_the_container_one(self, tmp_path):
        # The regression the old Dockerfile shipped: /home/harnessed/... baked into a host launch's
        # settings.json, pointing at a directory that does not exist on the host.
        _pnpm_installing_stub(tmp_path)
        cache = tmp_path / "cache" / "ccstatusline" / "2.2.22"
        cache.parent.mkdir(parents=True)
        r = _run("ccstatusline", tmp_path, mode="host", harness="claude", cache=cache)
        assert r.returncode == 0
        cmd = json.loads((tmp_path / "config" / "settings.json").read_text())["statusLine"]["command"]
        assert cmd == str(cache / "node_modules" / ".bin" / "ccstatusline")
        assert not cmd.startswith("/home/harnessed")
        assert os.access(cmd, os.X_OK)

    def test_host_populates_the_cache_via_a_partial_rename(self, tmp_path):
        # An interrupted install must never look like a populated cache: hit == "the dir exists".
        _pnpm_installing_stub(tmp_path)
        cache = tmp_path / "cache" / "ccstatusline" / "2.2.22"
        cache.parent.mkdir(parents=True)
        assert _run("ccstatusline", tmp_path, mode="host", harness="claude", cache=cache).returncode == 0
        assert (cache / "node_modules" / ".bin" / "ccstatusline").is_file()
        assert not list(cache.parent.glob("*.partial.*"))

    def test_host_cache_hit_does_not_reinstall(self, tmp_path):
        log = tmp_path / "pnpm.log"
        _stub(tmp_path / "bin", "pnpm", f'printf "%s\\n" "$*" >> {log}\n')
        cache = tmp_path / "cache" / "ccstatusline" / "2.2.22"
        (cache / "node_modules" / ".bin").mkdir(parents=True)
        binary = cache / "node_modules" / ".bin" / "ccstatusline"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        r = _run("ccstatusline", tmp_path, mode="host", harness="claude", cache=cache)
        assert r.returncode == 0
        assert not log.exists()

    def test_settings_merge_preserves_other_recipes_baked_keys(self, tmp_path):
        # Read-modify-write, not overwrite: install.sh runs after the profile settings.json is in
        # place (host) and alongside other recipes' baked keys (container).
        _pnpm_installing_stub(tmp_path)
        cache = tmp_path / "cache" / "ccstatusline" / "2.2.22"
        cache.parent.mkdir(parents=True)
        config = tmp_path / "config"
        config.mkdir()
        (config / "settings.json").write_text(json.dumps({"model": "sonnet"}))
        r = _run("ccstatusline", tmp_path, mode="host", harness="claude", cache=cache)
        assert r.returncode == 0
        out = json.loads((config / "settings.json").read_text())
        assert out["model"] == "sonnet"
        assert out["statusLine"]["type"] == "command"

    @pytest.mark.parametrize("harness", ["codex", "omp"])
    def test_non_claude_harness_gets_the_binary_but_no_statusline(self, tmp_path, harness):
        # statusLine is a Claude Code concept. The binary install is not gated — same split the
        # Dockerfile's `${HARNESS} = claude` branch had.
        _pnpm_installing_stub(tmp_path)
        cache = tmp_path / "cache" / "ccstatusline" / "2.2.22"
        cache.parent.mkdir(parents=True)
        r = _run("ccstatusline", tmp_path, mode="host", harness=harness, cache=cache)
        assert r.returncode == 0
        assert (cache / "node_modules" / ".bin" / "ccstatusline").is_file()
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
