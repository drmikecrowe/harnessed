"""bd harnessed-1t4.3 — `tools:` owns WHAT BINARY; install.sh owns configuration and content.

Fifteen recipes each fetched their tool from their own `install.sh`, one serial layer and one
network round trip apiece, while the declarative `tools:` field — which the assembler already
flattens into ONE parallel `mise use -g … && mise install` layer — was used by two.

Moving a tool install into `tools:` is only safe if BOTH executors honour it. Before this change the
field was read in exactly one place (the derived Dockerfile), so a migrated recipe would have
silently lost its binary on `launch --host`. These tests state that requirement against SYNTHETIC
recipes: the subject is the executor, not any catalog entry. Catalog-wide recipe rules live in
test_recipe_uniformity.py.
"""
from __future__ import annotations

from pathlib import Path

from harnessed import launcher
from harnessed.schema import Recipe
from support import patch_all


class TestHostLaunchHonoursTools:
    """`tools:` must deliver the binary on a --host launch too, or migrating a recipe REMOVES it."""

    def _fake_mise(self, monkeypatch, calls):
        monkeypatch.setattr(launcher.shutil, "which", lambda cmd: "/usr/bin/mise")

        class Result:
            returncode = 0

        def run(argv, **kwargs):
            calls.append((argv, kwargs.get("env") or {}))
            return Result()

        monkeypatch.setattr(launcher.subprocess, "run", run)

    def test_declared_tools_are_installed_on_a_host_launch(self, tmp_path, monkeypatch):
        calls: list = []
        self._fake_mise(monkeypatch, calls)
        recipes = [Recipe(name="a", root=tmp_path, tools=["pipx:serena-agent@1.5.3"])]
        launcher._host_install_tools("s", recipes)
        assert calls, "a stack declaring tools: must install them on a host launch"
        argv = " ".join(calls[0][0])
        assert "mise" in argv and "pipx:serena-agent@1.5.3" in argv

    def test_the_install_is_stack_scoped_not_the_users_global_mise(self, tmp_path, monkeypatch):
        # The reason rtk's install.sh refused to use mise host-side: mise's global config and data
        # dir belong to the user. Redirecting both is what makes `tools:` usable on the host.
        calls: list = []
        self._fake_mise(monkeypatch, calls)
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path, tools=["pipx:x@1"])])
        env = calls[0][1]
        stack_root = str(launcher._stack_tools_dirs("s")[0])
        # NOT MISE_STATE_DIR. It holds mise's TRUST store, which is a fact about the user and a
        # config file rather than about a stack, and scoping it here threw the user's trust away on
        # every launch — see TestHostLaunchKeepsTheUsersMiseTrustStore.
        for var in ("MISE_DATA_DIR", "MISE_CONFIG_DIR"):
            assert env.get(var, "").startswith(stack_root), f"{var}={env.get(var)!r} escapes the stack"

    def test_no_tools_means_no_mise_invocation(self, tmp_path, monkeypatch):
        calls: list = []
        self._fake_mise(monkeypatch, calls)
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path)])
        assert calls == []

    def test_a_missing_mise_is_announced_not_silently_skipped(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(launcher.shutil, "which", lambda cmd: None)
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path, tools=["pipx:x@1"])])
        out = capsys.readouterr()
        assert "mise" in (out.err + out.out).lower()

    def test_the_tool_bin_dir_is_on_the_launch_path(self):
        # Installing into a stack-scoped dir is useless if the agent cannot resolve the binary.
        shims = launcher._host_tool_shims_dir("s")
        assert str(shims).startswith(str(launcher._stack_tools_dirs("s")[0]))

    def test_tools_are_installed_before_install_scripts_run(self):
        # serena's install.sh keeps `serena init` — it configures a binary that tools: now provides,
        # so the tool layer must land first.
        import inspect

        src = inspect.getsource(launcher.HostBackend.provision_tools)
        assert src.index("_host_install_tools") < src.index("_host_run_installs")


class TestContainerExecutorInstallsToolsBeforeInstallScripts:
    """The CONTAINER half of the same ordering the host launch enforces (bd harnessed-1t4.3).

    A real build broke here: ccstatusline's install.sh does `command -v ccstatusline`, but the merged
    `mise use -g` layer was emitted AFTER every recipe's install.sh, so in a container the binary did
    not exist yet and the script exited non-zero. `tools:` owns the binary; install.sh configures it;
    the binary must be installed first — in both executors, not just on the host.
    """

    def _steps(self, recipes, monkeypatch):
        """The flattened command lines the container executor would run, in order."""
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        launcher._run_container_installs(
            "podman", "s", "claude", "img", list(recipes), "cfgvol", "toolsvol",
        )
        return [" ".join(c) for c in calls]

    def test_the_mise_step_precedes_the_recipe_install_step(self, tmp_path, monkeypatch):
        from harnessed.schema import InstallSpec

        recipe = tmp_path / "cc"
        recipe.mkdir(parents=True)
        (recipe / "install.sh").write_text("command -v ccstatusline\n", encoding="utf-8")
        r = Recipe(name="cc", root=recipe, tools=["npm:ccstatusline@2.2.22"])
        r.install = InstallSpec(script="install.sh")
        steps = self._steps([r], monkeypatch)
        joined = "\n".join(steps)
        assert joined.index("mise use -g") < joined.index("install.sh"), (
            "tools: must be installed before any recipe install.sh runs"
        )


class TestNpmToolsResolveThroughPnpmNotAube:
    """A correctly-pinned `npm:` tool must still install once mise's default backend rejects it.

    mise 2026.7.x defaults `npm.package_manager` to `auto`, which selects mise's own resolver
    (`aube`). aube enforces publisher-trust over the ENTIRE dependency tree, so ONE transitive dep
    published without trust evidence fails the whole install — of a package that is itself fine.
    `npm:context-mode@1.0.169` is the live case: it dies on `@hono/node-server@1.19.15`, and the pin
    is already the latest release, so there is no version to move to.

    Routing the `npm:` backend through pnpm keeps mise as the installer and the pin exact while
    dropping the tree-wide veto. Both executors must set it, or the failure simply moves.
    """

    ENV_VAR = "MISE_NPM_PACKAGE_MANAGER"

    def test_the_host_launch_sets_the_pnpm_backend(self, tmp_path, monkeypatch):
        calls: list = []
        TestHostLaunchHonoursTools()._fake_mise(monkeypatch, calls)
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path, tools=["npm:x@1"])])
        assert calls[0][1].get(self.ENV_VAR) == "pnpm", (
            "a host launch must route npm: through pnpm — aube vetoes untrusted transitive deps"
        )

    def test_the_host_override_wins_over_the_inherited_environment(self, tmp_path, monkeypatch):
        # `**os.environ` is splatted first; an inherited `auto` must not survive it, because `auto`
        # is not a preference the user can usefully hold here — it just fails.
        monkeypatch.setenv(self.ENV_VAR, "auto")
        calls: list = []
        TestHostLaunchHonoursTools()._fake_mise(monkeypatch, calls)
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path, tools=["npm:x@1"])])
        assert calls[0][1].get(self.ENV_VAR) == "pnpm"

    def test_the_container_executor_sets_it_on_the_tools_step(self, tmp_path, monkeypatch):
        r = Recipe(name="a", root=tmp_path, tools=["npm:context-mode@1.0.169"])
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        launcher._run_container_installs(
            "podman", "s", "claude", "img", [r], "cfgvol", "toolsvol",
        )
        assert f"{self.ENV_VAR}=pnpm" in calls[0], (
            f"the tools: step must set {self.ENV_VAR}=pnpm, got: {calls[0]}"
        )

    def test_it_is_scoped_to_the_build_and_not_leaked_as_image_env(self, tmp_path):
        # It governs build-time tool installation only; the agent's runtime has no use for it.
        from harnessed.emit import write_derived_dockerfile

        r = Recipe(name="a", root=tmp_path, tools=["npm:context-mode@1.0.169"])
        body = write_derived_dockerfile(tmp_path, "s", "claude", [r]).read_text(encoding="utf-8")
        assert not any(
            ln.startswith("ENV") and self.ENV_VAR in ln for ln in body.splitlines()
        ), f"{self.ENV_VAR} must be inline on the RUN, not a persistent image ENV"


class TestMiseShimsResolveAtRunTimeNotJustInstallTime:
    """A mise shim is a symlink to the mise binary — it re-resolves the tool by argv[0] against
    MISE_DATA_DIR EVERY TIME IT RUNS, not once at install.

    `_launch_host` put the stack's shims dir on the agent's PATH but left MISE_DATA_DIR unset, so
    mise fell back to the user's ~/.local/share/mise — where the stack installed nothing — and every
    shim on that PATH entry died with `mise ERROR <tool> is not a valid shim`. Surfaced as a dead
    ccstatusline statusLine on `launch --host`: settings.json recorded the shim path, and Claude Code
    spawns statusLine as a plain subprocess.
    """

    def test_the_shims_dir_lives_under_the_data_dir_the_env_points_at(self):
        env = launcher._host_mise_env("s")
        shims = launcher._host_tool_shims_dir("s")
        assert shims.parent == Path(env["MISE_DATA_DIR"]), (
            "a shim resolves against MISE_DATA_DIR; a shims dir that does not live under it is a "
            f"dir of broken symlinks (shims={shims}, MISE_DATA_DIR={env['MISE_DATA_DIR']})"
        )

    def test_install_time_and_run_time_see_the_same_mise_instance(self, tmp_path, monkeypatch):
        # The drift that caused the bug: _host_install_tools redirected mise into the stack tree in a
        # PRIVATE env dict, so the binary landed somewhere the run-time shim could never look.
        calls: list = []
        monkeypatch.setattr(launcher.shutil, "which", lambda cmd: "/usr/bin/mise")

        class Result:
            returncode = 0

        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda argv, **kw: (calls.append(kw.get("env") or {}), Result())[1],
        )
        launcher._host_install_tools("s", [Recipe(name="a", root=tmp_path, tools=["pipx:x@1"])])
        run_time = launcher._host_mise_env("s")
        for var, value in run_time.items():
            assert calls[0].get(var) == value, (
                f"{var} differs between install time ({calls[0].get(var)!r}) and the agent's "
                f"environment ({value!r}) — the shim will look in the wrong place"
            )


