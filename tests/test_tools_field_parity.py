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

from harnessed import hostrun, launcher
from harnessed.schema import Recipe
from support import patch_all


def _fake_bin_paths(monkeypatch, lines, *, returncode=0, stderr=""):
    """Stand in for the `mise bin-paths` subprocess, and record how it was invoked.

    Returns the recorded call list. Every path in `lines` is reported as an existing directory —
    `_host_tool_bin_dirs` drops entries that are not, and a tmp-path fixture per test would only
    restate mise's own output contract.
    """
    calls: list[dict] = []
    monkeypatch.setattr(hostrun.shutil, "which", lambda cmd: "/usr/bin/mise")
    monkeypatch.setattr(hostrun.Path, "is_dir", lambda self: True)

    class Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = "".join(f"{line}\n" for line in lines)
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return Result()

    monkeypatch.setattr(hostrun.subprocess, "run", fake_run)
    return calls


class TestHostLaunchHonoursTools:
    """`tools:` must deliver the binary on a --host launch too, or migrating a recipe REMOVES it."""

    def _fake_mise(self, monkeypatch, calls):
        monkeypatch.setattr(launcher.shutil, "which", lambda cmd: "/usr/bin/mise")

        class Result:
            # `stdout`/`stderr` are for the `mise bin-paths` call `_host_install_tools` ends with
            # (#449); the `mise use -g`/`mise install` calls read neither.
            returncode = 0
            stdout = ""
            stderr = ""

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
        stack_root = str(hostrun._stack_tools_dirs("s")[0])
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

    def test_the_tool_bin_dir_is_on_the_launch_path(self, monkeypatch):
        # Installing into a stack-scoped dir is useless if the agent cannot resolve the binary.
        # Behind the stack bin dir — see TestTheStackBinDirLeadsThePath for why that order.
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0"])
        hostrun._apply_host_tool_path(env, "s")
        assert "/t/installs/rtk/0.45.0" in env["PATH"].split(":")[:2]

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

    That shims dir is no longer on the PATH (#449 — see TestTheToolPathIsScopedToTheStacksOwnTools),
    but the redirect it forced still governs every `mise` run inside the session, and the two halves
    must still agree. These tests hold that agreement, not the PATH entry that first exposed it.
    """

    def test_the_shims_dir_lives_under_the_data_dir_the_env_points_at(self):
        env = launcher._host_mise_env("s")
        shims = hostrun._host_tool_shims_dir("s")
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
            stdout = ""
            stderr = ""

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




class TestTheToolPathIsScopedToTheStacksOwnTools:
    """#449 — the launch PATH carries the tools' REAL install dirs, never mise's shims dir.

    mise writes one shim per binary of every version ever installed under MISE_DATA_DIR and removes
    none when a tool leaves the config, so the shims dir is not scoped to what the stack declares.
    Measured on stack `default` when this was reported: 96 shims, 6 declared tools, 28 installs —
    the user's entire global tool set, left by a release that redirected MISE_DATA_DIR at install
    time without MISE_CONFIG_DIR. Prepended to PATH that dir failed two ways at once:

      1. A shim whose tool has no version in the STACK config dies with `mise ERROR No version is
         set for shim: <tool>`. `omp` was one of them, so the AGENT BINARY was shadowed by a broken
         shim and `host-run omp` could not start.
      2. A shim that does resolve shadows the user's pin with the stack's — `node` came back as
         v26.8.1 out of the stack tree against the user's global `node = "24"`.
    """

    def test_only_the_declared_tools_reach_the_path(self, monkeypatch):
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0", "/t/installs/pulumi/3.251.0/pulumi"])
        hostrun._apply_host_tool_path(env, "s")
        bin_dir = str(hostrun._stack_tools_dirs("s")[1])
        assert env["PATH"] == ":".join(
            [bin_dir, "/t/installs/rtk/0.45.0", "/t/installs/pulumi/3.251.0/pulumi", "/usr/bin"]
        )

    def test_the_shims_dir_is_not_on_the_path(self, monkeypatch):
        # The whole point. A regression here reinstates both failure modes above at once.
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0"])
        hostrun._apply_host_tool_path(env, "s")
        assert str(hostrun._host_tool_shims_dir("s")) not in env["PATH"].split(":")

    def test_bin_paths_resolves_at_the_stack_mise_root_not_the_project(self, monkeypatch):
        # mise merges every config from the cwd upward. Run in the project, this puts the PROJECT's
        # mise.toml tools on the agent's PATH — measured, 8 paths against the 6 the stack declares.
        calls = _fake_bin_paths(monkeypatch, [])
        hostrun._host_tool_bin_dirs("s")
        assert calls[0]["cmd"] == ["mise", "bin-paths"]
        assert calls[0]["cwd"] == str(hostrun._stack_tools_dirs("s")[0] / "mise")

    def test_a_second_call_does_not_double_the_path(self, monkeypatch):
        # _launch_host and _host_install_tools BOTH call it — the first is the only one that fires
        # when the fingerprint matched, the second the only one that sees a first launch's installs.
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0"])
        hostrun._apply_host_tool_path(env, "s")
        hostrun._apply_host_tool_path(env, "s")
        assert env["PATH"].count("/t/installs/rtk/0.45.0") == 1

    def test_a_failing_mise_warns_and_contributes_no_tool_dirs(self, monkeypatch, capsys):
        # Never a SILENT empty contribution: the tools are missing and the user must know. The stack
        # bin dir is still placed — `install.sh` fills that one, and mise has no say in it.
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, [], returncode=1, stderr="boom")
        hostrun._apply_host_tool_path(env, "s")
        assert env["PATH"] == f"{hostrun._stack_tools_dirs('s')[1]}:/usr/bin"
        out = capsys.readouterr()
        assert "bin-paths" in (out.err + out.out)


class TestTheSessionGetsTheUsersOwnMiseBack:
    """#449, second cause — the redirect provisions the stack; it does not own the session.

    Removing the shims dir from PATH was only half the report. `_launch_host` also exported the
    MISE_DATA_DIR / MISE_CONFIG_DIR redirect onto the AGENT, and a mise shim re-resolves its tool by
    argv[0] against MISE_DATA_DIR every time it runs — so the redirect broke every shim on the
    USER's own PATH instead. `node`, `gh`, `python`, and `omp` itself, which is mise-installed:

        mise ERROR No version is set for shim: omp

    Verified live before and after: `host-run omp` reached the same error with the PATH fix alone,
    and started the agent once the session got the user's mise back.
    """

    def _outer_stack_mise_root(self) -> str:
        """A value shaped exactly like the one `_host_mise_env` emits, for some other stack."""
        return str(hostrun._stack_tools_dirs("outer")[0] / "mise")

    def test_a_users_own_value_is_restored(self):
        env = {"MISE_DATA_DIR": "/stack/redirect"}
        hostrun._restore_user_mise_env(env, {"MISE_DATA_DIR": "/home/u/.local/share/mise"})
        assert env["MISE_DATA_DIR"] == "/home/u/.local/share/mise"

    def test_a_variable_the_user_never_set_ends_unset(self):
        # Not "restored to empty" — an empty MISE_DATA_DIR is not the same as mise's default.
        env = {"MISE_DATA_DIR": "/stack/redirect"}
        hostrun._restore_user_mise_env(env, {"MISE_DATA_DIR": None})
        assert "MISE_DATA_DIR" not in env

    def test_an_inherited_harnessed_redirect_is_dropped_not_restored(self):
        # Launching a stack from inside another stack's host session is routine. Restoring the OUTER
        # stack's data dir hands the agent a tree its own binary was never installed into — measured
        # live as `mise ERROR omp is not a valid shim`, the same bug one level out.
        outer = self._outer_stack_mise_root()
        env = {"MISE_DATA_DIR": "/inner/redirect"}
        hostrun._restore_user_mise_env(env, {"MISE_DATA_DIR": outer})
        assert "MISE_DATA_DIR" not in env

    def test_the_trusted_paths_are_restored_verbatim(self):
        # NOT in `_NOT_THE_USERS`: `_apply_host_mise_env` only ever carries entries read out of the
        # user's OWN config into this one, so an inherited value is theirs by construction.
        env = {"MISE_TRUSTED_CONFIG_PATHS": "/stack/x"}
        hostrun._restore_user_mise_env(env, {"MISE_TRUSTED_CONFIG_PATHS": "/home/u/repo"})
        assert env["MISE_TRUSTED_CONFIG_PATHS"] == "/home/u/repo"

    def test_the_snapshot_covers_every_variable_the_redirect_touches(self):
        # A variable restored on one side only leaves the session half-redirected, which is worse
        # than either state.
        touched = set(launcher._host_mise_env("s")) | {"MISE_STATE_DIR", "MISE_TRUSTED_CONFIG_PATHS"}
        assert touched <= set(hostrun._MISE_SESSION_VARS)

    def test_the_data_dir_shape_is_recognised(self):
        assert hostrun._is_a_harnessed_stack_data_dir(self._outer_stack_mise_root())

    def test_a_users_own_data_dir_is_never_second_guessed(self, tmp_path):
        # Narrowness rule: only the shape harnessed itself emits is eligible to be dropped.
        assert not hostrun._is_a_harnessed_stack_data_dir(str(tmp_path))
        assert not hostrun._is_a_harnessed_stack_data_dir("")


class TestTheStackBinDirLeadsThePath:
    """#449 adversary finding 5 — a recipe's own binary must keep beating the stack's `tools:`.

    An `install.sh` installs into the stack bin dir (via the UV_TOOL_BIN_DIR / PNPM_HOME redirects)
    and may install a name `tools:` also declares. The old PATH was `[stack_bin, shims, …]`, so the
    recipe's copy won. Prepending the bin dirs as a separate step put them in front instead —
    silently, since only a same-name collision shows it.
    """

    def test_the_bin_dir_comes_before_the_tool_dirs(self, monkeypatch):
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0"])
        env = {"PATH": "/usr/bin"}
        hostrun._apply_host_tool_path(env, "s")
        entries = env["PATH"].split(":")
        assert entries[0] == str(hostrun._stack_tools_dirs("s")[1])
        assert entries[1] == "/t/installs/rtk/0.45.0"
        assert entries[-1] == "/usr/bin"

    def test_the_second_call_lands_on_the_same_order(self, monkeypatch):
        # `_launch_host` calls it against an empty tools tree on a first launch; `_host_install_tools`
        # calls it again once the installs exist. Skipping entries already present would leave the
        # freshly-installed tool dir ahead of the bin dir the first call placed.
        env = {"PATH": "/usr/bin"}
        _fake_bin_paths(monkeypatch, [])
        hostrun._apply_host_tool_path(env, "s")
        _fake_bin_paths(monkeypatch, ["/t/installs/rtk/0.45.0"])
        hostrun._apply_host_tool_path(env, "s")
        entries = env["PATH"].split(":")
        assert entries[0] == str(hostrun._stack_tools_dirs("s")[1])
        assert entries[1] == "/t/installs/rtk/0.45.0"
        assert entries.count(entries[0]) == 1, "repeated launches must not grow the PATH"
