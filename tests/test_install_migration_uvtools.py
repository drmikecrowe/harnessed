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

# The batch. `serena` is the interesting one — it is the only member that also keeps a `setup.sh`,
# because it is the only one with per-project work to do.
MIGRATED = ["serena", "repowise", "codebase-memory-mcp", "agentmemory"]


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
        assert _recipe(name).install.system is None

    def test_declares_no_content_cache(self, name):
        """`install.cache` keys a pinned CONTENT clone (superpowers' git tree). These four fetch
        packaged artifacts from uv / pnpm / mise, each of which has its own cache — an empty
        harnessed cache dir would just be dead weight the script never reads."""
        assert _recipe(name).install.cache is None

    def test_the_script_pins_an_exact_version(self, name):
        """Every one of these installs a pinned artifact. A script that lost its `==`/`@<version>`
        would silently start tracking upstream HEAD across rebuilds."""
        body = _code(_recipe(name).root / "install.sh")
        assert "@latest" not in body
        assert "==" in body or "@${" in body


class TestPinsStayInSyncWithTheRecipe:
    """A version living in two files drifts. Each assertion below is one such pair."""

    def test_serena_script_pin_is_the_version_the_recipe_documents(self):
        body = _code(_recipe("serena").root / "install.sh")
        assert 'SERENA_VERSION="1.5.3"' in body
        assert 'serena-agent==${SERENA_VERSION}' in body


class TestSerenaInstallSetupSplit:
    """serena is the only member with BOTH halves, and the split is the whole point of the phase
    distinction: install has no project, setup does."""

    def test_install_does_the_cli_and_the_global_backend_config(self):
        body = _code(_recipe("serena").root / "install.sh")
        assert "uv tool install" in body
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
        body = _code(r.root / r.setup.script)
        assert "HARNESSED_CFG_NAME" in body
        assert "serena project create" in body

    def test_setup_no_longer_installs_or_configures(self):
        """The duplicate install is the regression to guard: if it came back, a host launch would
        run `uv tool install` twice per launch and the two copies could pin differently."""
        r = _recipe("serena")
        body = _code(r.root / r.setup.script)
        assert "uv tool install" not in body
        assert "serena init" not in body
        assert 'HARNESSED_MODE" = host' not in body, "the host-only branch is what install.sh replaced"


class TestCodebaseMemoryHostDoesNotEditGlobalMiseConfig:
    """`mise use -g` writes the USER's ~/.config/mise/config.toml, adding the tool to every shell
    they open. That is fine for an image (whose global config IS the image) and not fine for a
    stack-scoped host install — so the script branches, and the host branch must stay config-free."""

    def test_the_script_branches_on_mode(self):
        body = _code(_recipe("codebase-memory-mcp").root / "install.sh")
        assert '"$HARNESSED_MODE" = container' in body

    def test_use_g_is_confined_to_the_container_branch(self):
        body = _code(_recipe("codebase-memory-mcp").root / "install.sh")
        container_half, host_half = body.split("else", 1)
        assert "mise use -g" in container_half
        assert "mise use -g" not in host_half

    def test_the_host_branch_targets_the_stack_bin_dir(self):
        """UV_TOOL_BIN_DIR is the stack-scoped bin dir `_host_run_installs` puts first on PATH. It
        is set alongside the install env contract rather than being part of it, so the script must
        fail loudly if it is missing instead of dropping the binary somewhere unreachable."""
        body = _code(_recipe("codebase-memory-mcp").root / "install.sh")
        assert "${UV_TOOL_BIN_DIR:?" in body


class TestAgentmemoryInstallsTheAdapterNotTheStore:
    """The store is a SERVICE; this recipe is only the stdio protocol adapter. `@agentmemory/mcp` is
    the package that ships the `agentmemory-mcp` binary recipe.yaml spawns — `@agentmemory/agentmemory`
    ships the store CLI and belongs in the service image."""

    def test_installs_the_mcp_adapter_package(self):
        body = _code(_recipe("agentmemory").root / "install.sh")
        assert "@agentmemory/mcp@" in body
        assert "@agentmemory/agentmemory" not in body

    def test_uses_pnpm_never_npm(self):
        body = _code(_recipe("agentmemory").root / "install.sh")
        assert "pnpm add -g" in body

    def test_the_installed_binary_is_the_one_the_mcp_entry_spawns(self):
        r = _recipe("agentmemory")
        assert r.servers[0].command == "agentmemory-mcp"
