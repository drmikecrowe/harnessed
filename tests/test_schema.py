"""Tests for schema validators (C1 — security-critical code)."""

import pytest
from pathlib import Path

from harnessed.schema import (
    McpServer,
    PersistSpec,
    Recipe,
    RecipeLintError,
    PinValidationError,
    validate_no_raw_npm,
    validate_pin,
    load_recipe,
    load_stack,
    load_service,
    load_agent,
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


class TestLoadAgent:
    def _write(self, tmp_path, name, body):
        d = tmp_path / "agents" / name
        d.mkdir(parents=True)
        (d / "agent.yaml").write_text(body)

    def test_build_args_parsed_and_stringified(self, tmp_path):
        # Unquoted 16.1.2 is a YAML string (two dots); the loader must stringify scalars for --build-arg.
        self._write(tmp_path, "omp", "harness: omp\nimage: harnessed-omp\nbuild_args:\n  OMP_VERSION: 16.1.2\n")
        agent = load_agent("omp", root=tmp_path)
        assert agent.build_args == {"OMP_VERSION": "16.1.2"}

    def test_no_build_args_defaults_empty(self, tmp_path):
        self._write(tmp_path, "claude", "harness: claude\nimage: harnessed-claude\n")
        assert load_agent("claude", root=tmp_path).build_args == {}

    def test_build_args_non_mapping_raises(self, tmp_path):
        self._write(tmp_path, "omp", "harness: omp\nimage: harnessed-omp\nbuild_args: [OMP_VERSION]\n")
        with pytest.raises(SchemaError, match="build_args"):
            load_agent("omp", root=tmp_path)

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


class TestPersistParse:
    """T4a — persist: declaration shape, explicit scope keys, project-name validation."""

    def _load(self, tmp_path, body: str) -> Recipe:
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return load_recipe(d)

    def test_absent_persist_is_empty(self, tmp_path):
        r = self._load(tmp_path, "name: r\n")
        assert r.persist == PersistSpec()
        assert r.persist.project == [] and r.persist.global_dirs == []

    def test_project_and_global_parsed(self, tmp_path):
        r = self._load(tmp_path, "name: r\npersist:\n  project: [.context-mode]\n  global: [~/.gbrain]\n")
        assert r.persist.project == [".context-mode"]
        assert r.persist.global_dirs == ["~/.gbrain"]

    def test_bare_list_rejected(self, tmp_path):
        # Scope must be a named key, never inferred from the string shape.
        with pytest.raises(SchemaError, match="explicit scope keys"):
            self._load(tmp_path, "name: r\npersist: [context]\n")

    def test_unknown_scope_key_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown scope key"):
            self._load(tmp_path, "name: r\npersist:\n  shared: [x]\n")

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "~/.ssh", "/etc/passwd", "..", "."])
    def test_traversal_project_names_rejected(self, tmp_path, bad):
        with pytest.raises(SchemaError, match="not a valid name"):
            self._load(tmp_path, f"name: r\npersist:\n  project: ['{bad}']\n")

    @pytest.mark.parametrize("ok", [".context-mode", "cache", "my_data", "a.b-c", "...idx"])
    def test_valid_project_names_accepted(self, tmp_path, ok):
        r = self._load(tmp_path, f"name: r\npersist:\n  project: ['{ok}']\n")
        assert r.persist.project == [ok]

    def test_empty_global_entry_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="non-empty host path"):
            self._load(tmp_path, "name: r\npersist:\n  global: ['']\n")


class TestStrictRecipeFields:
    """T1 — `--strict` known-field allowlist: catch typos, preserve D-14 forward fields."""

    def _load(self, tmp_path, body: str, *, strict: bool) -> Recipe:
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return load_recipe(d, strict=strict)

    def test_non_strict_ignores_unknown_field(self, tmp_path):
        # Default (D-14 tolerant): an unknown field is preserved on .raw, never rejected.
        r = self._load(tmp_path, "name: r\nskkills: [oops]\n", strict=False)
        assert r.name == "r"
        assert r.raw["skkills"] == ["oops"]

    def test_strict_rejects_unknown_field_with_suggestion(self, tmp_path):
        with pytest.raises(SchemaError, match=r"skkills.*did you mean 'skills'"):
            self._load(tmp_path, "name: r\nskkills: [oops]\n", strict=True)

    def test_strict_allows_all_typed_fields(self, tmp_path):
        body = (
            "name: r\ndescription: d\nmcp:\n  servers: []\n"
            "skills: [skills/x]\ncommands: [commands/y]\n"
            "expect:\n  skills: [x]\npersist:\n  project: [.x]\n"
        )
        r = self._load(tmp_path, body, strict=True)
        assert r.name == "r"

    @pytest.mark.parametrize("forward", ["plugins", "hooks", "deps", "scripts"])
    def test_strict_allows_d14_forward_fields(self, tmp_path, forward):
        # The whole point of the allowlist: forward fields stay legal under --strict.
        r = self._load(tmp_path, f"name: r\n{forward}: []\n", strict=True)
        assert r.name == "r"

    def test_strict_error_names_the_unknown_and_lists_known(self, tmp_path):
        with pytest.raises(SchemaError) as exc:
            self._load(tmp_path, "name: r\ntotally_made_up: 1\n", strict=True)
        msg = str(exc.value)
        assert "totally_made_up" in msg and "Known fields" in msg and "--no-strict" in msg
