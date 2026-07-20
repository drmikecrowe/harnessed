"""Recipe `env:` — one declaration, mode-portable values, three consumers (bd harnessed-8px.2).

`env:` exists because a Dockerfile ENV is the one recipe deliverable no bash script can replace:
an `export` dies with the script that ran it, while this env must be LIVE for the running agent.

The tests below are organised around the trap the field exists to avoid: a value like
`/home/harnessed/.beads` is CONTAINER-absolute, and copying it literally into a `launch --host`
names a directory that does not exist. So values are templates resolved against the launcher's
path contract, and the same declaration must yield a DIFFERENT, correct absolute path per mode.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from harnessed import emit, launcher, paths
from harnessed.schema import (
    PersistEntry,
    PersistSpec,
    Recipe,
    SchemaError,
    Stack,
    load_recipe,
    resolve_recipe_env,
)


def _entry(name: str, scope: str = "workspace", location: str = "host") -> PersistEntry:
    return PersistEntry(scope=scope, location=location, name=name, path=None, vcs=None)


def _recipe(tmp_path: Path, body: str) -> Recipe:
    d = tmp_path / "recipe"
    d.mkdir(exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    return load_recipe(d)


class TestEnvParsing:
    def test_parses_mapping(self, tmp_path):
        r = _recipe(tmp_path, 'name: x\nenv:\n  FOO: "1"\n  BAR: baz\n')
        assert r.env == {"FOO": "1", "BAR": "baz"}

    def test_absent_defaults_empty(self, tmp_path):
        assert _recipe(tmp_path, "name: x\n").env == {}

    def test_number_is_stringified(self, tmp_path):
        assert _recipe(tmp_path, "name: x\nenv:\n  N: 1\n").env == {"N": "1"}

    def test_rejects_list(self, tmp_path):
        with pytest.raises(SchemaError, match="must be a mapping"):
            _recipe(tmp_path, "name: x\nenv: [FOO=1]\n")

    def test_rejects_invalid_var_name(self, tmp_path):
        with pytest.raises(SchemaError, match="not a valid environment variable name"):
            _recipe(tmp_path, 'name: x\nenv:\n  "2FOO": "1"\n')

    def test_rejects_bool(self, tmp_path):
        # YAML `true` would silently become the Python literal `True`, not the string a shell wants.
        with pytest.raises(SchemaError, match="must be a string or number"):
            _recipe(tmp_path, "name: x\nenv:\n  FOO: true\n")

    def test_is_not_the_per_mcp_server_env(self, tmp_path):
        """schema.McpServer.env is an unrelated pre-existing field — the two must not collide."""
        r = _recipe(
            tmp_path,
            'name: x\nenv:\n  AGENT_VAR: "1"\n'
            "mcp:\n  servers:\n    - name: s\n      command: s\n      env:\n        SRV_VAR: '2'\n",
        )
        assert r.env == {"AGENT_VAR": "1"}
        assert r.servers[0].env == {"SRV_VAR": "2"}


class TestEnvTemplateValidation:
    """A typo must fail at LOAD — otherwise it reaches the agent as a literal `{persist:.bead}`."""

    def test_rejects_unknown_placeholder(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown placeholder"):
            _recipe(tmp_path, 'name: x\nenv:\n  D: "{home}/foo"\n')

    def test_rejects_dangling_persist_ref(self, tmp_path):
        with pytest.raises(SchemaError, match="does not declare"):
            _recipe(
                tmp_path,
                'name: x\nenv:\n  D: "{persist:.bead}"\n'
                "persist:\n  - name: .beads\n    scope: project\n    location: host\n",
            )

    def test_accepts_declared_persist_ref(self, tmp_path):
        r = _recipe(
            tmp_path,
            'name: x\nenv:\n  D: "{persist:.beads}"\n'
            "persist:\n  - name: .beads\n    scope: project\n    location: host\n",
        )
        assert r.env == {"D": "{persist:.beads}"}

    def test_strict_mode_accepts_env_field(self, tmp_path):
        """`env` must be in KNOWN_RECIPE_FIELDS — recipe parsing is otherwise tolerant of unknown
        fields (D-14), so without it a --strict build rejects the recipe outright."""
        d = tmp_path / "recipe"
        d.mkdir()
        (d / "recipe.yaml").write_text('name: x\nenv:\n  FOO: "1"\n')
        assert load_recipe(d, strict=True).env == {"FOO": "1"}


class TestSubstitution:
    """THE point of the field: ONE declaration, the correct absolute path in EACH mode."""

    def test_literal_value_is_mode_invariant(self, tmp_path):
        r = Recipe(name="superpowers", env={"SUPERPOWERS_DISABLE_TELEMETRY": "1"})
        for mode in ("container", "host"):
            assert resolve_recipe_env(r, mode=mode, project_path=tmp_path) == {
                "SUPERPOWERS_DISABLE_TELEMETRY": "1"
            }

    def test_persist_host_location_differs_per_mode(self, tmp_path, monkeypatch):
        """The trap, directly: the container path is the bind-mount target, the host path is the
        real persist dir. A flat string map could only ever get one of them right."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        r = Recipe(
            name="context-mode",
            env={"CONTEXT_MODE_DIR": "{persist:.context-mode}"},
            persist=PersistSpec(entries=[_entry(".context-mode", scope="workspace")]),
        )
        proj = tmp_path / "proj"
        proj.mkdir()

        ctr = resolve_recipe_env(r, mode="container", project_path=proj)
        host = resolve_recipe_env(r, mode="host", project_path=proj)

        assert ctr == {"CONTEXT_MODE_DIR": f"{paths.CONTAINER_HOME}/.context-mode"}
        assert host == {
            "CONTEXT_MODE_DIR": str(
                paths.persist_workspace_dir("context-mode", proj, ".context-mode")
            )
        }
        assert ctr != host
        # The container value is exactly where _persist_mounts bind-mounts the host dir.
        assert ctr["CONTEXT_MODE_DIR"].startswith(str(paths.CONTAINER_HOME))
        # ...and the host value is a REAL directory path, not the pod's $HOME.
        assert not host["CONTEXT_MODE_DIR"].startswith(str(paths.CONTAINER_HOME))

    def test_persist_scope_project_uses_project_keyed_dir(self, tmp_path, monkeypatch):
        """scope: project keys on the git-common-dir, so the host value must follow that — not the
        workspace hash. Getting this wrong points bd at a second, empty database."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        r = Recipe(
            name="beads-stealth",
            env={"BEADS_DIR": "{persist:.beads}"},
            persist=PersistSpec(entries=[_entry(".beads", scope="project")]),
        )
        proj = tmp_path / "proj"
        proj.mkdir()
        assert resolve_recipe_env(r, mode="host", project_path=proj) == {
            "BEADS_DIR": str(paths.persist_project_dir("beads-stealth", proj, ".beads"))
        }

    def test_persist_in_repo_is_identical_in_both_modes(self, tmp_path):
        """in_repo lives inside the workspace, which is mounted path-preserving — so both modes
        agree, and the template must NOT rewrite it to a $HOME-relative container path."""
        r = Recipe(
            name="beads-team",
            env={"BEADS_DIR": "{persist:.beads}"},
            persist=PersistSpec(entries=[_entry(".beads", scope="project", location="in_repo")]),
        )
        proj = tmp_path / "proj"
        proj.mkdir()
        expected = {"BEADS_DIR": str(paths.persist_in_repo_dir(proj, ".beads"))}
        assert resolve_recipe_env(r, mode="container", project_path=proj) == expected
        assert resolve_recipe_env(r, mode="host", project_path=proj) == expected

    def test_project_dir_and_host_home(self, tmp_path):
        r = Recipe(name="x", env={"P": "{project_dir}/sub", "H": "{host_home}"})
        out = resolve_recipe_env(r, mode="container", project_path=tmp_path)
        assert out == {"P": f"{tmp_path}/sub", "H": str(Path.home())}

    def test_placeholder_embedded_in_a_longer_value(self, tmp_path):
        r = Recipe(
            name="x",
            env={"SOCK": "{persist:.beads}/run/mysql.sock"},
            persist=PersistSpec(entries=[_entry(".beads")]),
        )
        assert resolve_recipe_env(r, mode="container", project_path=tmp_path)["SOCK"] == (
            f"{paths.CONTAINER_HOME}/.beads/run/mysql.sock"
        )


class TestBuildTimeResolution:
    """`project_path=None` is build time. A var is baked only if its value is knowable then."""

    def test_project_independent_vars_are_resolved(self):
        r = Recipe(
            name="beads-stealth",
            env={"BEADS_DIR": "{persist:.beads}", "LIT": "1"},
            persist=PersistSpec(entries=[_entry(".beads", scope="project")]),
        )
        assert resolve_recipe_env(r, mode="container", project_path=None) == {
            "BEADS_DIR": f"{paths.CONTAINER_HOME}/.beads",
            "LIT": "1",
        }

    def test_project_dependent_vars_are_omitted_not_half_substituted(self):
        """Omitted, never emitted with an empty placeholder — a half-substituted `ENV D=/run` baked
        into the image would be worse than absent, since the launch-time `-e` still has to win."""
        r = Recipe(
            name="x",
            env={"P": "{project_dir}", "R": "{persist:.d}", "LIT": "1"},
            persist=PersistSpec(entries=[_entry(".d", location="in_repo")]),
        )
        assert resolve_recipe_env(r, mode="container", project_path=None) == {"LIT": "1"}


class TestLauncherDelivery:
    def test_recipe_env_merges_stack_recipes_later_wins(self, tmp_path):
        """Later recipes win, matching the Dockerfile layering this replaces (a later ENV for the
        same name overrides an earlier one)."""
        a = Recipe(name="a", env={"SHARED": "from-a", "ONLY_A": "1"})
        b = Recipe(name="b", env={"SHARED": "from-b"})
        assert launcher._recipe_env([a, b], tmp_path, mode="host") == {
            "SHARED": "from-b",
            "ONLY_A": "1",
        }

    def test_container_launch_passes_e_args(self, tmp_path, monkeypatch):
        """The container consumer: real container env via `podman run -e`, not `podman exec -e` —
        so hooks and later execs see the same values (the _container_setup_env precedent)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        r = Recipe(
            name="beads-stealth",
            env={"BEADS_DIR": "{persist:.beads}"},
            persist=PersistSpec(entries=[_entry(".beads", scope="project")]),
        )
        env = launcher._recipe_env([r], tmp_path, mode="container")
        args = [arg for var, val in env.items() for arg in ("-e", f"{var}={val}")]
        assert args == ["-e", f"BEADS_DIR={paths.CONTAINER_HOME}/.beads"]

    def test_recipe_env_cannot_clobber_the_folder_env_contract_in_either_mode(self, tmp_path):
        """Precedence must be IDENTICAL host vs container, and the harnessed-owned contract must win.

        Regression guard for a defect introduced by merging harnessed-0tk.7 and harnessed-8px.2:
        each was self-consistent alone, but together they inverted precedence between modes. Container
        applies `-e` left-to-right (LAST wins) and had recipe_env last; host applies os.environ.update
        in sequence and had the contract last. A recipe declaring PROJECT_DIR would therefore win in a
        pod and lose on the host — silent host/container drift, the exact class of bug this epic exists
        to remove. Assert the ORDER, not just the values.
        """
        source = inspect.getsource(launcher.launch)
        pos = {name: source.index(f"*{name},") for name in ("recipe_env", "socket_env", "setup_env")}
        assert pos["recipe_env"] < pos["socket_env"], (
            "recipe env: must be passed BEFORE the folder-env contract so the contract wins"
        )
        assert pos["recipe_env"] < pos["setup_env"]

        # And the host side agrees: _recipe_env is applied first, harnessed_env overwrites it.
        host = inspect.getsource(launcher._launch_host)
        assert host.index("_recipe_env(") < host.index("harnessed_env(")


class TestHostLaunchDelivery:
    """THE row that was broken: the agent process itself. On host there is no image and no
    `podman run -e`, so the launcher must put the values in its OWN environment before exec —
    the same reasoning by which _launch_host already mutates os.environ for PATH."""

    def test_env_reaches_the_exec_d_agent(self, monkeypatch, tmp_path):
        from typer.testing import CliRunner

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        # Sentinels, not delenv: setenv registers an undo so the launch's os.environ mutation is
        # rolled back after this test — and asserting they are GONE below also proves a recipe
        # declaration wins over an inherited value, mirroring `podman run -e` in container mode.
        monkeypatch.setenv("BEADS_DIR", "/inherited/wrong")
        monkeypatch.setenv("SUPERPOWERS_DISABLE_TELEMETRY", "inherited")

        r = Recipe(
            name="beads-stealth",
            env={"BEADS_DIR": "{persist:.beads}", "SUPERPOWERS_DISABLE_TELEMETRY": "1"},
            persist=PersistSpec(entries=[_entry(".beads", scope="project")]),
        )
        # A real Stack, not None: _launch_host reads stk.permissions to resolve settings.json.
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes",
            lambda root, stack: (Stack(name="hostspike"), [r]),
        )

        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(env)
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = CliRunner().invoke(
            launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"]
        )
        assert result.exit_code == 0, result.output

        assert captured["SUPERPOWERS_DISABLE_TELEMETRY"] == "1"
        assert captured["BEADS_DIR"] == str(
            paths.persist_project_dir("beads-stealth", tmp_path.resolve(), ".beads")
        )
        # The bug this replaces: the pod's $HOME handed to a host process.
        assert not captured["BEADS_DIR"].startswith(str(paths.CONTAINER_HOME))


class TestDockerfileEmission:
    def _write(self, tmp_path, recipes) -> str:
        prof = tmp_path / "prof"
        prof.mkdir()
        return emit.write_derived_dockerfile(
            prof, "s", "claude", recipes, with_scan=False
        ).read_text()

    def test_env_becomes_image_env(self, tmp_path):
        r = Recipe(name="superpowers", env={"SUPERPOWERS_DISABLE_TELEMETRY": "1"}, root=tmp_path)
        assert 'ENV SUPERPOWERS_DISABLE_TELEMETRY="1"' in self._write(tmp_path, [r])

    def test_emitted_for_a_recipe_with_no_dockerfile(self, tmp_path):
        """`env:` is a standalone deliverable — it must not be skipped along with the missing
        Dockerfile layer."""
        r = Recipe(name="bare", env={"FOO": "bar"}, root=tmp_path / "nope")
        assert 'ENV FOO="bar"' in self._write(tmp_path, [r])

    def test_env_precedes_the_recipe_body_so_a_run_sees_it(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "Dockerfile").write_text("RUN echo build-step\n")
        out = self._write(tmp_path, [Recipe(name="r", env={"FOO": "bar"}, root=d)])
        assert out.index('ENV FOO="bar"') < out.index("RUN echo build-step")

    def test_project_dependent_var_is_not_baked(self, tmp_path):
        r = Recipe(name="r", env={"P": "{project_dir}", "LIT": "1"}, root=tmp_path)
        out = self._write(tmp_path, [r])
        assert 'ENV LIT="1"' in out
        assert "ENV P=" not in out

    def test_value_is_quoted_and_dollar_escaped(self, tmp_path):
        """A `$` in a value must not expand against the build's ARGs — env values are literals."""
        r = Recipe(name="r", env={"V": "a b $HOME"}, root=tmp_path)
        assert 'ENV V="a b \\$HOME"' in self._write(tmp_path, [r])


class TestShippedRecipesUseTheField:
    """The three recipes that proved the design — each `ENV` line is now one `env:` declaration."""

    @pytest.mark.parametrize(
        "ref,var,expected_ctr",
        [
            ("superpowers", "SUPERPOWERS_DISABLE_TELEMETRY", "1"),
            ("context-mode", "CONTEXT_MODE_DIR", f"{paths.CONTAINER_HOME}/.context-mode"),
            ("beads/stealth", "BEADS_DIR", f"{paths.CONTAINER_HOME}/.beads"),
        ],
    )
    def test_declares_env_and_no_longer_hardcodes_it_in_the_dockerfile(
        self, ref, var, expected_ctr, tmp_path
    ):
        recipe = load_recipe(paths.find_in_catalog("recipes", ref), strict=True)
        assert var in recipe.env
        # Container mode reproduces exactly what the retired Dockerfile ENV said.
        assert resolve_recipe_env(recipe, mode="container", project_path=tmp_path)[var] == expected_ctr
        dockerfile = recipe.root / "Dockerfile"
        body = dockerfile.read_text() if dockerfile.is_file() else ""
        assert not any(ln.startswith(f"ENV {var}") for ln in body.splitlines())

    @pytest.mark.parametrize("ref,var", [("context-mode", "CONTEXT_MODE_DIR"), ("beads/stealth", "BEADS_DIR")])
    def test_path_valued_ones_leave_the_pod_home_behind_on_host(self, ref, var, tmp_path, monkeypatch):
        """The regression this whole field exists to prevent: a host launch must never be handed
        /home/harnessed/... , which does not exist there."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        recipe = load_recipe(paths.find_in_catalog("recipes", ref))
        value = resolve_recipe_env(recipe, mode="host", project_path=tmp_path)[var]
        assert not value.startswith(str(paths.CONTAINER_HOME))
        assert Path(value).is_absolute()
