"""Tests for schema validators (C1 — security-critical code)."""

import pytest
from pathlib import Path

from harnessed.schema import (
    McpServer,
    Recipe,
    RecipeLintError,
    PinValidationError,
    validate_no_raw_npm,
    validate_pin,
    load_stack,
    load_service,
    SchemaError,
)


def _make_recipe(name: str = "test", servers: list | None = None) -> Recipe:
    return Recipe(
        name=name,
        servers=servers or [],
        root=Path("/tmp/fake-recipe"),
    )


class TestValidateNoRawNpm:
    def test_clean_recipe_passes(self):
        r = _make_recipe()
        validate_no_raw_npm(r)  # must not raise

    def test_npm_command_raises(self):
        r = _make_recipe(servers=[McpServer(name="s", command="npm", args=["install"])])
        with pytest.raises(RecipeLintError, match="pnpm"):
            validate_no_raw_npm(r)

    def test_npx_command_raises(self):
        r = _make_recipe(servers=[McpServer(name="s", command="npx", args=["some-pkg"])])
        with pytest.raises(RecipeLintError, match="pnpm dlx"):
            validate_no_raw_npm(r)

    def test_pnpm_command_passes(self):
        r = _make_recipe(servers=[McpServer(name="s", command="pnpm", args=["dlx", "hatago"])])
        validate_no_raw_npm(r)  # must not raise

    def test_npm_in_arg_raises(self):
        r = _make_recipe(servers=[McpServer(name="s", command="bash", args=["-c", "npm install foo"])])
        with pytest.raises(RecipeLintError):
            validate_no_raw_npm(r)

    def test_npmlog_package_name_does_not_raise(self):
        r = _make_recipe(servers=[McpServer(name="s", command="node", args=["npmlog-helper.js"])])
        validate_no_raw_npm(r)  # word-bounded — npmlog is NOT npm


class TestValidatePin:
    def test_clean_dockerfile_passes(self):
        validate_pin("r", "RUN pnpm dlx hatago@1.2.3")  # pinned → pass

    def test_latest_tag_raises(self):
        with pytest.raises(PinValidationError, match=":latest"):
            validate_pin("r", "FROM node:latest")

    def test_at_latest_raises(self):
        with pytest.raises(PinValidationError, match="@latest"):
            validate_pin("r", "RUN pnpm dlx foo@latest")

    def test_branch_main_raises(self):
        with pytest.raises(PinValidationError, match="main"):
            validate_pin("r", "RUN git clone --branch main https://example.com/repo")

    def test_branch_master_raises(self):
        with pytest.raises(PinValidationError, match="master"):
            validate_pin("r", "RUN git clone --branch master https://example.com/repo")

    def test_comment_line_does_not_trigger(self):
        # A :latest in a comment must not trigger the gate.
        validate_pin("r", "# use :latest for testing\nRUN pnpm dlx foo@1.0.0")

    def test_url_path_segment_does_not_trigger(self):
        # :latest inside a URL path is allowed (e.g. registry.io/img:path/latest/thing)
        validate_pin("r", "RUN curl https://example.com/releases/latest/download/bin")


class TestLoadStack:
    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(SchemaError, match="stack manifest not found"):
            load_stack(tmp_path / "nonexistent")

    def test_minimal_stack_loads(self, tmp_path):
        d = tmp_path / "my-stack"
        d.mkdir()
        (d / "stack.yaml").write_text("name: my-stack\nharness: claude\nrecipes: []\n")
        stk = load_stack(d)
        assert stk.name == "my-stack"
        assert stk.harness == "claude"

    def test_invalid_yaml_raises(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "stack.yaml").write_text("- not: a mapping")
        with pytest.raises(SchemaError, match="expected a YAML mapping"):
            load_stack(d)

    def test_missing_name_raises(self, tmp_path):
        d = tmp_path / "no-name"
        d.mkdir()
        (d / "stack.yaml").write_text("harness: claude\nrecipes: []\n")
        with pytest.raises(SchemaError, match="name"):
            load_stack(d)

    def test_invalid_harness_raises(self, tmp_path):
        d = tmp_path / "bad-harness"
        d.mkdir()
        (d / "stack.yaml").write_text("name: bad\nharness: vim\nrecipes: []\n")
        with pytest.raises(SchemaError, match="vim"):
            load_stack(d)

    def test_all_valid_harnesses_load(self, tmp_path):
        for harness in ("claude", "omp", "opencode", "gemini", "antigravity", "codex"):
            d = tmp_path / harness
            d.mkdir()
            (d / "stack.yaml").write_text(f"name: {harness}-stack\nharness: {harness}\nrecipes: []\n")
            stk = load_stack(d)
            assert stk.harness == harness


class TestParseServerTransportValidation:
    """_parse_servers rejects invalid transports (W2.2 schema gap C6)."""

    def _recipe_yaml(self, transport: str) -> str:
        return (
            "name: test\n"
            "mcp:\n"
            "  servers:\n"
            "    - name: srv\n"
            f"      transport: {transport}\n"
            "      command: pnpm\n"
        )

    def _make_recipe_file(self, tmp_path, transport: str):
        d = tmp_path / "recipe"
        d.mkdir(exist_ok=True)
        (d / "recipe.yaml").write_text(self._recipe_yaml(transport))
        return d

    def test_grpc_raises(self, tmp_path):
        from harnessed.schema import load_recipe
        d = self._make_recipe_file(tmp_path, "grpc")
        with pytest.raises(SchemaError, match="grpc"):
            load_recipe(d)

    def test_websocket_raises(self, tmp_path):
        from harnessed.schema import load_recipe
        d = self._make_recipe_file(tmp_path, "websocket")
        with pytest.raises(SchemaError, match="websocket"):
            load_recipe(d)

    def test_stdio_passes(self, tmp_path):
        from harnessed.schema import load_recipe
        d = self._make_recipe_file(tmp_path, "stdio")
        r = load_recipe(d)
        assert r.servers[0].transport == "stdio"

    def test_http_passes(self, tmp_path):
        from harnessed.schema import load_recipe
        d = tmp_path / "recipe-http"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: test\nmcp:\n  servers:\n    - name: srv\n      transport: http\n      url: http://localhost:8080/mcp\n"
        )
        r = load_recipe(d)
        assert r.servers[0].transport == "http"

    def test_sse_passes(self, tmp_path):
        from harnessed.schema import load_recipe
        d = tmp_path / "recipe-sse"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: test\nmcp:\n  servers:\n    - name: srv\n      transport: sse\n      url: http://localhost:8080/sse\n"
        )
        r = load_recipe(d)
        assert r.servers[0].transport == "sse"


class TestParseServerServiceCommandExclusion:
    """service + command together is rejected (W2.2 schema gap C6)."""

    def test_service_and_command_raises(self, tmp_path):
        from harnessed.schema import load_recipe
        d = tmp_path / "recipe"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: test\nmcp:\n  servers:\n"
            "    - name: srv\n      service: hindsight\n      command: pnpm\n"
        )
        with pytest.raises(SchemaError, match="mutually exclusive"):
            load_recipe(d)

    def test_service_without_command_passes(self, tmp_path):
        from harnessed.schema import load_recipe
        d = tmp_path / "recipe"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: test\nmcp:\n  servers:\n"
            "    - name: srv\n      service: hindsight\n      transport: http\n"
        )
        r = load_recipe(d)
        assert r.servers[0].service == "hindsight"

    def test_command_without_service_passes(self, tmp_path):
        from harnessed.schema import load_recipe
        d = tmp_path / "recipe"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: test\nmcp:\n  servers:\n"
            "    - name: srv\n      command: pnpm\n      args: [dlx, '@time/server']\n"
        )
        r = load_recipe(d)
        assert r.servers[0].command == "pnpm"


class TestLoadServicePortRange:
    """load_service validates port 1–65535 (W2.2 schema gap C6)."""

    def _make_service(self, tmp_path, port) -> Path:
        svc_dir = tmp_path / "services" / "mySvc"
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(
            f"name: mySvc\nimage: ghcr.io/org/mysvc:1.0.0\nport: {port}\n"
        )
        return tmp_path

    def test_port_zero_raises(self, tmp_path):
        root = self._make_service(tmp_path, 0)
        with pytest.raises(SchemaError, match="port"):
            load_service(root, "mySvc")

    def test_port_65536_raises(self, tmp_path):
        root = self._make_service(tmp_path, 65536)
        with pytest.raises(SchemaError, match="port"):
            load_service(root, "mySvc")

    def test_port_1_passes(self, tmp_path):
        root = self._make_service(tmp_path, 1)
        svc = load_service(root, "mySvc")
        assert svc.port == 1

    def test_port_65535_passes(self, tmp_path):
        root = self._make_service(tmp_path, 65535)
        svc = load_service(root, "mySvc")
        assert svc.port == 65535

    def test_port_3535_passes(self, tmp_path):
        root = self._make_service(tmp_path, 3535)
        svc = load_service(root, "mySvc")
        assert svc.port == 3535
