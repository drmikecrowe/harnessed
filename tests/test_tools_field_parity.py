"""bd harnessed-1t4.3 — `tools:` owns WHAT BINARY; install.sh owns configuration and content.

Fifteen recipes each fetched their tool from their own `install.sh`, one serial layer and one
network round trip apiece, while the declarative `tools:` field — which the assembler already
flattens into ONE parallel `mise use -g … && mise install` layer — was used by two.

Moving a tool install into `tools:` is only safe if BOTH executors honour it. Before this change the
field was read in exactly one place (the derived Dockerfile), so a migrated recipe would have
silently lost its binary on `launch --host`. These tests state that requirement first, then the
per-recipe migration.
"""
from __future__ import annotations

import pytest

from harnessed import launcher, paths
from harnessed.schema import Recipe, load_recipe

# recipe name → the tool spec it must declare, and the fetch that must no longer be in its install.sh
MIGRATED = {
    "agent-carnet": ("npm:agent-carnet@", "pnpm add -g"),
    "agentmemory": ("npm:@agentmemory/mcp@", "pnpm add -g"),
    "context-mode": ("npm:context-mode@", "pnpm add -g"),
    "repowise": ("pipx:repowise@", "uv tool install"),
    "serena": ("pipx:serena-agent@", "uv tool install"),
    "rtk": ("github:rtk-ai/rtk@", "mise use -g"),
    "ccstatusline": ("npm:ccstatusline@", "mise use -g"),
}


def _recipe(name: str) -> Recipe:
    return load_recipe(paths.harnessed_home() / "catalog" / "recipes" / name)


class TestRecipesDeclareTheirBinary:
    @pytest.mark.parametrize("name", sorted(MIGRATED))
    def test_the_tool_is_declared_in_tools(self, name):
        prefix = MIGRATED[name][0]
        assert any(t.startswith(prefix) for t in _recipe(name).tools), (
            f"{name} must declare {prefix}<version> in tools:, got {_recipe(name).tools}"
        )

    @pytest.mark.parametrize("name", sorted(MIGRATED))
    def test_install_sh_no_longer_fetches_the_binary(self, name):
        recipe = _recipe(name)
        script = recipe.root / recipe.install.script if recipe.install and recipe.install.script else None
        if script is None:
            return  # a recipe whose whole install.sh was the fetch may legitimately have none left
        body = "\n".join(
            ln for ln in script.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert MIGRATED[name][1] not in body, (
            f"{name}/install.sh still runs '{MIGRATED[name][1]}' — the binary is tools:' job now"
        )

    @pytest.mark.parametrize("name", sorted(MIGRATED))
    def test_the_declared_pin_is_exact(self, name):
        for spec in _recipe(name).tools:
            assert "@" in spec.rsplit(":", 1)[-1], f"{name}: unpinned tool spec {spec!r}"
            assert not spec.endswith("@latest"), f"{name}: floating tool spec {spec!r}"

    def test_content_only_recipes_were_not_migrated(self):
        # mise has no clone backend: these deliver CONTENT into the config dir, not a binary.
        for name in ("superpowers", "hyperpowers", "caveman", "gstack", "gsd-core"):
            assert _recipe(name).tools == [], f"{name} must not be expressed as tools:"


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
        for var in ("MISE_DATA_DIR", "MISE_CONFIG_DIR", "MISE_STATE_DIR"):
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

        src = inspect.getsource(launcher._launch_host)
        assert src.index("_host_install_tools") < src.index("_host_run_installs")


class TestEmittedDockerfileInstallsToolsBeforeInstallScripts:
    """The CONTAINER half of the same ordering the host launch enforces (bd harnessed-1t4.3).

    A real build broke here: ccstatusline's install.sh does `command -v ccstatusline`, but the merged
    `mise use -g` layer was emitted AFTER every recipe's install.sh, so in a container the binary did
    not exist yet and the script exited non-zero. `tools:` owns the binary; install.sh configures it;
    the binary must be installed first — in both executors, not just on the host.
    """

    def _derived_body(self, tmp_path):
        from harnessed.emit import write_derived_dockerfile
        from harnessed.schema import InstallSpec

        recipe = tmp_path / "cc"
        recipe.mkdir(parents=True)
        (recipe / "install.sh").write_text("command -v ccstatusline\n", encoding="utf-8")
        r = Recipe(name="cc", root=recipe, tools=["npm:ccstatusline@2.2.22"])
        r.install = InstallSpec(script="install.sh")
        return write_derived_dockerfile(tmp_path, "s", "claude", [r]).read_text(encoding="utf-8")

    def test_the_mise_layer_precedes_the_recipe_install_layer(self, tmp_path):
        body = self._derived_body(tmp_path)
        assert body.index("mise use -g") < body.index("install.sh"), (
            "the tools: layer must be emitted before any recipe install.sh runs"
        )

    def test_the_real_ccstatusline_recipe_has_its_tool_before_its_install(self, tmp_path):
        # The recipe that actually broke: its tools: pin must land before the RUN that executes its
        # install.sh (the script does `command -v ccstatusline`). The Dockerfile carries the pin and
        # the `bash …/ccstatusline/install.sh` invocation, not the script body.
        from harnessed.emit import write_derived_dockerfile

        recipe = load_recipe(paths.harnessed_home() / "catalog" / "recipes" / "ccstatusline")
        body = write_derived_dockerfile(tmp_path, "s", "claude", [recipe]).read_text(encoding="utf-8")
        assert body.index("npm:ccstatusline@") < body.index("ccstatusline/install.sh")
