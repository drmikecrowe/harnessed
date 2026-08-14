"""Batch B of the `install:` migration — the TOOL-installing recipes (bd harnessed-8px.5).

Where batch A moved *content* (superpowers' skills) out of a Dockerfile RUN, these four moved a
*binary*: serena, repowise, codebase-memory-mcp, agentmemory. The failure they fix is the same shape
as harnessed-8px.1 — a Dockerfile RUN never executes on `launch --host`, so the tool the recipe's
`mcp.servers[].command` names was simply not on PATH, and the stdio child resolved to nothing with
no error. Two of them (serena, repowise) papered over that with a second, separate host-only
mechanism (`setup.sh`'s mode branch / `provision:`), which is how serena ended up installing its CLI
on the host but never running `serena init -b LSP` there.

What is asserted here is the INVARIANT set, not the command text: every migrated recipe declares
`install.script`, ships that file, has no Dockerfile left, passes the install lint, and — for the
ones whose script carries a version pin — keeps that pin in sync with the version the recipe still
declares elsewhere.

Deliberately a separate module from `tests/test_install_script.py`: that file tests the MECHANISM,
this one tests its CONSUMERS.
"""

from pathlib import Path

import pytest

from harnessed.schema import load_recipe, validate_install_script

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# The batch. bd harnessed-1t4.3 then split it in two: a recipe whose ONLY deliverable was the binary
# now declares it in `tools:` and has no script left at all, while one with a configuration or
# content half keeps `install.script` for that half.
#
# codebase-memory-mcp moved MIGRATED -> TOOLS_ONLY in Phase 2 of #329: its script was a hand-rolled
# `mise use -g` / `mise install` and nothing else, so it had no configuration half to keep. serena
# is the last member with both halves. See tests/test_cbm_migration.py.
MIGRATED = ["serena"]
TOOLS_ONLY = ["repowise", "agentmemory", "codebase-memory-mcp"]


def _recipe(name):
    return load_recipe(CATALOG / "recipes" / name, strict=True)


def _code(path: Path) -> str:
    """The script's executable lines only.

    These scripts are heavily commented, and the comments name the very things the assertions below
    look for ("NOT `@agentmemory/agentmemory`", "no `@latest`", "`serena init -b LSP` moved to
    install.sh"). Matching raw text would make every such comment a false positive or a false
    negative, so strip whole-line comments and the shebang before asserting.
    """
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


@pytest.mark.parametrize("name", MIGRATED)
class TestEveryMigratedRecipe:
    def test_declares_install_and_ships_the_script(self, name):
        r = _recipe(name)
        assert r.install is not None, f"{name} still has no `install:` block"
        assert r.install.script == "install.sh"
        assert (r.root / "install.sh").is_file()

    def test_has_no_dockerfile_left(self, name):
        """The Dockerfile RUN IS the container-only-ness. Leaving one behind would mean the install
        happens twice in a build and still only once overall."""
        r = _recipe(name)
        assert not (r.root / "Dockerfile").exists()

    def test_passes_the_install_lint(self, name):
        """Moving a RUN body into a .sh moves it out of `validate_pin`'s sight; this lint is what
        keeps raw npm/npx and floating refs rejected on the other side of the move."""
        validate_install_script(_recipe(name))

    def test_declares_no_root_component(self, name):
        """None of these needs root: uv/pnpm/mise all install under the invoking user. A stray
        `system:` here would print a scary skip warning on every host launch for no reason."""
        install = _recipe(name).install
        assert install is not None, f"{name}: expected install block"
        assert install.system is None

    def test_declares_no_content_cache(self, name):
        """`install.cache` keys a pinned CONTENT clone (a git tree). The migrated recipes fetch a
        PACKAGED artifact instead — serena via `pipx:serena-agent`, which mise resolves through uv —
        and uv caches wheels itself, so an empty harnessed cache dir would be dead weight the script
        never reads. Same reasoning the recipe states at its own `tools:` block."""
        install = _recipe(name).install
        assert install is not None, f"{name}: expected install block"
        assert install.cache is None

    def test_the_script_pins_an_exact_version(self, name):
        """Every pinned artifact a script still fetches keeps its `==`/`@<version>`; a script that
        lost it would silently start tracking upstream HEAD across rebuilds."""
        body = _code(_recipe(name).root / "install.sh")
        assert "@latest" not in body


@pytest.mark.parametrize("name", TOOLS_ONLY)
class TestBinaryOnlyRecipesAreFullyDeclarative:
    """bd harnessed-1t4.3: when the binary was the whole recipe, the script has nothing left to do."""

    def test_declares_the_binary_in_tools(self, name):
        assert _recipe(name).tools, f"{name} must declare its binary in tools:"

    def test_every_tool_spec_is_pinned(self, name):
        for spec in _recipe(name).tools:
            assert "@latest" not in spec and "@" in spec.rsplit(":", 1)[-1], spec

    def test_has_no_install_script_left(self, name):
        r = _recipe(name)
        assert r.install is None or r.install.script is None
        assert not (r.root / "install.sh").exists()

    def test_has_no_dockerfile_left(self, name):
        assert not (_recipe(name).root / "Dockerfile").exists()


class TestPinsStayInSyncWithTheRecipe:
    """A version living in two files drifts. Each assertion below is one such pair."""

    def test_serena_pins_its_version_in_exactly_one_place(self):
        # Was: assert the script literal and the `tools:` pin AGREE. The literal was never
        # referenced by the script — it only documented the version — so AC-1 deleted it. A single
        # source cannot drift, which is a stronger guarantee than two that match today.
        r = _recipe("serena")
        assert "SERENA_VERSION" not in _code(r.root / "install.sh")
        assert "pipx:serena-agent@1.6.1" in r.tools


class TestSerenaInstallSetupSplit:
    """serena is the only member with BOTH halves, and the split is the whole point of the phase
    distinction: install has no project, setup does."""

    def test_tools_does_the_cli_and_install_does_the_global_backend_config(self):
        # bd harnessed-1t4.3 drew the line here: `tools:` owns WHAT BINARY, install.sh owns
        # CONFIGURATION. `serena init -b LSP` is the configuration half and stays.
        r = _recipe("serena")
        body = _code(r.root / "install.sh")
        assert "pipx:serena-agent@1.6.1" in r.tools
        assert "uv tool install" not in body
        assert "serena init -b LSP" in body

    def test_install_never_touches_project_state(self):
        """`serena project create` needs HARNESSED_PROJECT_DIR / HARNESSED_CFG_NAME, neither of
        which is in the install env contract — a build has no project mounted. Reaching for them
        here would expand to empty in a build and 'work' only on the host: exactly the
        mode-asymmetric failure this epic exists to remove."""
        body = _code(_recipe("serena").root / "install.sh")
        assert "serena project create" not in body
        assert "HARNESSED_PROJECT_DIR" not in body
        assert "HARNESSED_CFG_NAME" not in body

    def test_setup_keeps_only_the_project_name_convergence(self):
        r = _recipe("serena")
        assert r.setup is not None and r.setup.script is not None, "serena: expected setup.script"
        body = _code(r.root / r.setup.script)
        assert "HARNESSED_CFG_NAME" in body
        assert "serena project create" in body

    def test_setup_no_longer_installs_or_configures(self):
        """The duplicate install is the regression to guard: if it came back, a host launch would
        run `uv tool install` twice per launch and the two copies could pin differently."""
        r = _recipe("serena")
        assert r.setup is not None and r.setup.script is not None, "serena: expected setup.script"
        body = _code(r.root / r.setup.script)
        assert "uv tool install" not in body
        assert "serena init" not in body
        assert 'HARNESSED_MODE" = host' not in body, "the host-only branch is what install.sh replaced"


# `TestCodebaseMemoryHostDoesNotEditGlobalMiseConfig` lived here: three tests reading the script's
# text to prove `mise use -g` stayed out of its host branch and that the host branch linked the
# binary into the stack bin dir. The script is gone (Phase 2 of #329) and so are they — but the
# PROPERTY they asserted is not, it moved to where it is now enforced for every recipe rather than
# spelled out in one:
#   * stack-scoped, never the user's global mise config
#       -> tests/test_tools_field_parity.py::…::test_the_install_is_stack_scoped_not_the_users_global_mise
#   * the installed binary is resolvable by the agent
#       -> tests/test_tools_field_parity.py::…::test_the_tool_bin_dir_is_on_the_launch_path
# Deleting a test whose subject no longer exists is correct; deleting it without naming its
# successor is how a guarantee quietly stops being tested.


class TestAgentmemoryInstallsTheAdapterNotTheStore:
    """The store is a SERVICE; this recipe is only the stdio protocol adapter. `@agentmemory/mcp` is
    the package that ships the `agentmemory-mcp` binary recipe.yaml spawns — `@agentmemory/agentmemory`
    ships the store CLI and belongs in the service image."""

    def test_declares_the_mcp_adapter_package(self):
        tools = _recipe("agentmemory").tools
        assert any(t.startswith("npm:@agentmemory/mcp@") for t in tools), tools
        assert not any("agentmemory/agentmemory" in t for t in tools)

    def test_the_npm_backend_routes_through_the_managed_pnpm_policy(self):
        # mise's `npm:` backend is configured with npm.package_manager=pnpm in the base image, so a
        # declarative install is still governed by the pnpm supply-chain config — no raw npm.
        assert all(t.startswith("npm:") for t in _recipe("agentmemory").tools)

    def test_the_installed_binary_is_the_one_the_mcp_entry_spawns(self):
        r = _recipe("agentmemory")
        assert r.servers[0].command == "agentmemory-mcp"
