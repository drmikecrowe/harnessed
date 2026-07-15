"""Tests for host-native `provision:` — the recipe field + the `launch --host` provisioner that puts
a recipe's stdio-MCP tool on PATH (uv-tool backend) so hatago can spawn it container-free.

Parsing is pure. The real install is gated on `uv` being on PATH and uses a tiny package (pycowsay)
so it stays fast.
"""

import shutil
from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.schema import SchemaError, load_recipe

CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class TestProvisionSchema:
    def test_serena_declares_uv_tool_provision(self):
        r = load_recipe(CATALOG / "recipes" / "serena", strict=True)
        assert len(r.provision) == 1
        p = r.provision[0]
        assert (p.via, p.package, p.version, p.python, p.command) == (
            "uv-tool", "serena-agent", "1.5.3", "3.13", "serena")

    def test_repowise_declares_provision(self):
        r = load_recipe(CATALOG / "recipes" / "repowise", strict=True)
        assert r.provision[0].command == "repowise"

    def test_recipe_without_provision_is_empty(self):
        r = load_recipe(CATALOG / "recipes" / "greet", strict=True)
        assert r.provision == []

    def test_unknown_backend_rejected(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: bad\nprovision:\n  - via: brew\n    package: x\n    version: '1'\n    command: x\n"
        )
        with pytest.raises(SchemaError):
            load_recipe(d, strict=True)

    def test_floating_version_rejected(self, tmp_path):
        d = tmp_path / "float"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: float\nprovision:\n  - via: uv-tool\n    package: x\n    version: latest\n    command: x\n"
        )
        with pytest.raises(SchemaError):
            load_recipe(d, strict=True)


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv on PATH (host provisioner)")
class TestProvisionInstall:
    def test_provisions_tool_into_stack_bin_and_is_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        bins = launcher._host_provision("hostprov")
        assert bins, "expected a stack bin dir"
        bin_dir = Path(bins[0])
        assert bin_dir == paths.xdg_data_home() / "harnessed" / "tools" / "hostprov" / "bin"
        assert (bin_dir / "pycowsay").exists(), "pycowsay not installed onto the stack bin dir"

        # Second call: already present → no reinstall, same bin dir returned.
        assert launcher._host_provision("hostprov") == bins

    def test_no_provision_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        assert launcher._host_provision("hostspike") == []  # greet: no provision
