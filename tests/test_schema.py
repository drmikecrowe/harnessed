"""Tests for schema validators (C1 — security-critical code)."""

import pytest
from pathlib import Path

from harnessed.schema import (
    HookCommand,
    InitSpec,
    McpServer,
    PersistEntry,
    PersistSpec,
    Recipe,
    RecipeLintError,
    PinValidationError,
    validate_init_no_exit,
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


class TestValidateInitNoExit:
    """Model A: init.run is SOURCED into the attach shell, so a bash `exit` kills the session."""

    def _recipe_with_init(self, run: str) -> Recipe:
        r = _make_recipe()
        r.init = InitSpec(run=run)
        return r

    def test_exit_1_is_rejected_with_guidance(self):
        r = self._recipe_with_init("bd list >/dev/null 2>&1 || exit 1")
        with pytest.raises(RecipeLintError, match="SOURCED"):
            validate_init_no_exit(r)

    def test_bare_exit_is_rejected(self):
        r = self._recipe_with_init("foo\nexit\nbar")
        with pytest.raises(RecipeLintError, match="return"):
            validate_init_no_exit(r)

    def test_exit_code_var_is_accepted(self):
        # `exit_code` is a variable name, not the `exit` command.
        r = self._recipe_with_init("run-thing; exit_code=$?; echo $exit_code")
        validate_init_no_exit(r)  # must not raise

    def test_foo_exit_substring_is_accepted(self):
        r = self._recipe_with_init("call foo_exit && echo done")
        validate_init_no_exit(r)  # word-bounded — foo_exit is NOT exit

    def test_return_is_accepted(self):
        r = self._recipe_with_init("bd list >/dev/null 2>&1 || return 1")
        validate_init_no_exit(r)  # must not raise

    def test_no_init_is_accepted(self):
        validate_init_no_exit(_make_recipe())  # init is None → must not raise


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

    def test_ssh_keys_default_empty(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\n")
        assert load_stack(d).ssh_keys == []

    def test_ssh_keys_valid_list_parsed(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nssh_keys: [id_ed25519, id_work]\n")
        assert load_stack(d).ssh_keys == ["id_ed25519", "id_work"]

    def test_ssh_keys_traversal_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nssh_keys: ['../id_rsa']\n")
        with pytest.raises(SchemaError, match="ssh_keys"):
            load_stack(d)

    def test_ssh_keys_absolute_path_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nssh_keys: ['/etc/shadow']\n")
        with pytest.raises(SchemaError, match="ssh_keys"):
            load_stack(d)

    def test_ssh_keys_non_list_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nssh_keys: id_ed25519\n")
        with pytest.raises(SchemaError, match="ssh_keys"):
            load_stack(d)

    def test_forward_git_credentials_defaults_false(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\n")
        assert load_stack(d).forward_git_credentials is False

    def test_forward_git_credentials_parsed_true(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nforward_git_credentials: true\n")
        assert load_stack(d).forward_git_credentials is True

    def test_hatago_default_none(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\n")
        assert load_stack(d).hatago is None

    def test_hatago_repo_and_ref_parsed(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text(
            "name: s\nharness: claude\n"
            "hatago:\n  repo: github:drmikecrowe/hatago-mcp-hub\n  ref: feat/per-server-tool-filtering\n"
        )
        assert load_stack(d).hatago == {
            "repo": "github:drmikecrowe/hatago-mcp-hub",
            "ref": "feat/per-server-tool-filtering",
        }

    def test_hatago_ref_optional(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nhatago:\n  repo: github:owner/repo\n")
        assert load_stack(d).hatago == {"repo": "github:owner/repo", "ref": None}

    def test_hatago_missing_repo_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nhatago:\n  ref: main\n")
        with pytest.raises(SchemaError, match="hatago"):
            load_stack(d)

    def test_hatago_repo_bad_shape_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text("name: s\nharness: claude\nhatago:\n  repo: not-a-github-spec\n")
        with pytest.raises(SchemaError, match="hatago.repo"):
            load_stack(d)

    def test_hatago_ref_injection_rejected(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "stack.yaml").write_text(
            'name: s\nharness: claude\nhatago:\n  repo: github:owner/repo\n  ref: "main\\" && rm -rf /"\n'
        )
        with pytest.raises(SchemaError, match="hatago.ref"):
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
        for harness in ("claude", "omp", "opencode", "antigravity", "codex"):
            d = tmp_path / harness
            d.mkdir()
            (d / "stack.yaml").write_text(f"name: {harness}-stack\nharness: {harness}\nrecipes: []\n")
            stk = load_stack(d)
            assert stk.harness == harness

    def test_invalid_permissions_raises(self, tmp_path):
        d = tmp_path / "bad-permissions"
        d.mkdir()
        (d / "stack.yaml").write_text("name: bad\nrecipes: []\npermissions: ask\n")
        with pytest.raises(SchemaError, match="ask"):
            load_stack(d)

    def test_all_valid_permissions_load(self, tmp_path):
        for permissions in ("prompt", "auto", "yolo"):
            d = tmp_path / permissions
            d.mkdir()
            (d / "stack.yaml").write_text(
                f"name: {permissions}-stack\nrecipes: []\npermissions: {permissions}\n"
            )
            stk = load_stack(d)
            assert stk.permissions == permissions


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


class TestRecipeEgressAndTools:
    """Recipe-declared `egress:` hosts + pinned `tools:` (conditional service exposure)."""

    def _recipe(self, tmp_path, body: str):
        d = tmp_path / "recipe"
        d.mkdir(exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return d

    def test_egress_and_tools_parse(self, tmp_path):
        from harnessed.schema import load_recipe
        r = load_recipe(self._recipe(
            tmp_path, "name: pulumi\negress: [api.pulumi.com, get.pulumi.com]\ntools: [pulumi@3.140.0]\n"
        ))
        assert r.egress == ["api.pulumi.com", "get.pulumi.com"]
        assert r.tools == ["pulumi@3.140.0"]

    def test_absent_defaults_empty(self, tmp_path):
        from harnessed.schema import load_recipe
        r = load_recipe(self._recipe(tmp_path, "name: bare\n"))
        assert r.egress == [] and r.tools == []

    def test_egress_rejects_url(self, tmp_path):
        from harnessed.schema import load_recipe
        with pytest.raises(SchemaError, match="bare hostname"):
            load_recipe(self._recipe(tmp_path, "name: x\negress: ['https://api.pulumi.com/x']\n"))

    def test_tools_rejects_latest(self, tmp_path):
        from harnessed.schema import load_recipe
        with pytest.raises(SchemaError, match="pinned"):
            load_recipe(self._recipe(tmp_path, "name: x\ntools: [pulumi@latest]\n"))

    def test_tools_rejects_bare_name(self, tmp_path):
        from harnessed.schema import load_recipe
        with pytest.raises(SchemaError, match="pinned"):
            load_recipe(self._recipe(tmp_path, "name: x\ntools: [pulumi]\n"))


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
    """T4a — persist: list-of-entries format, both axes (scope + location), all combinations."""

    def _load(self, tmp_path, body: str) -> Recipe:
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return load_recipe(d)

    def _yaml_entry(self, **kw) -> str:
        lines = ["persist:"]
        lines.append("  - " + "\n    ".join(f"{k}: {v}" for k, v in kw.items()))
        return "name: r\n" + "\n".join(lines) + "\n"

    # --- Empty / absent ---

    def test_absent_persist_is_empty(self, tmp_path):
        r = self._load(tmp_path, "name: r\n")
        assert r.persist == PersistSpec()
        assert r.persist.entries == []

    # --- Old format migration hint ---

    def test_old_dict_project_format_gives_migration_hint(self, tmp_path):
        with pytest.raises(SchemaError, match="format has changed"):
            self._load(tmp_path, "name: r\npersist:\n  project: [.foo]\n")

    def test_old_dict_global_format_gives_migration_hint(self, tmp_path):
        with pytest.raises(SchemaError, match="format has changed"):
            self._load(tmp_path, "name: r\npersist:\n  global: [~/.gbrain]\n")

    def test_bare_non_list_rejected(self, tmp_path):
        with pytest.raises(SchemaError):
            self._load(tmp_path, "name: r\npersist: not-a-list\n")

    # --- scope validation ---

    def test_missing_scope_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="missing required field 'scope'"):
            self._load(tmp_path, "name: r\npersist:\n  - name: .foo\n    location: host\n")

    def test_unknown_scope_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown scope"):
            self._load(tmp_path, self._yaml_entry(scope="shared", name=".foo", location="host"))

    def test_reserved_scope_repo_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="reserved for a future release"):
            self._load(tmp_path, self._yaml_entry(scope="repo", name=".foo", location="host"))

    # --- scope: workspace + location: host ---

    def test_workspace_host_entry_parsed(self, tmp_path):
        r = self._load(tmp_path, self._yaml_entry(scope="workspace", name=".ctx", location="host"))
        assert len(r.persist.entries) == 1
        e = r.persist.entries[0]
        assert e.scope == "workspace" and e.location == "host" and e.name == ".ctx"
        assert e.path is None and e.vcs is None

    @pytest.mark.parametrize("ok", [".context-mode", "cache", "my_data", "a.b-c", "...idx"])
    def test_workspace_host_valid_names_accepted(self, tmp_path, ok):
        r = self._load(tmp_path, self._yaml_entry(scope="workspace", name=ok, location="host"))
        assert r.persist.entries[0].name == ok

    @pytest.mark.parametrize("bad", ["../escape", "~/.ssh", "/etc/passwd", "..", "."])
    def test_workspace_host_invalid_names_rejected(self, tmp_path, bad):
        with pytest.raises(SchemaError):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=bad, location="host"))

    def test_workspace_host_slash_in_name_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="single path component"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name="a/b", location="host"))

    def test_workspace_host_missing_name_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="requires a 'name' field"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: workspace\n    location: host\n")

    def test_workspace_host_missing_location_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="requires an explicit 'location'"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: workspace\n    name: .foo\n")

    def test_workspace_vcs_on_host_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="'vcs' is only valid for location: in_repo"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=".foo", location="host", vcs="ignored"))

    # --- scope: project + location: host ---

    def test_project_host_entry_parsed(self, tmp_path):
        r = self._load(tmp_path, self._yaml_entry(scope="project", name=".beads", location="host"))
        e = r.persist.entries[0]
        assert e.scope == "project" and e.location == "host" and e.name == ".beads"

    # --- location: in_repo + vcs ---

    def test_workspace_in_repo_tracked_parsed(self, tmp_path):
        r = self._load(tmp_path, self._yaml_entry(scope="workspace", name="notes.md", location="in_repo", vcs="tracked"))
        e = r.persist.entries[0]
        assert e.scope == "workspace" and e.location == "in_repo" and e.vcs == "tracked"

    def test_workspace_in_repo_ignored_parsed(self, tmp_path):
        r = self._load(tmp_path, self._yaml_entry(scope="workspace", name=".scratch", location="in_repo", vcs="ignored"))
        e = r.persist.entries[0]
        assert e.vcs == "ignored"

    def test_in_repo_missing_vcs_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="requires a 'vcs' field"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=".foo", location="in_repo"))

    def test_in_repo_unknown_vcs_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown vcs"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=".foo", location="in_repo", vcs="symlink"))

    def test_in_repo_allows_nested_paths(self, tmp_path):
        r = self._load(tmp_path, self._yaml_entry(scope="workspace", name="data/notes.md", location="in_repo", vcs="tracked"))
        assert r.persist.entries[0].name == "data/notes.md"

    # --- reserved location: external ---

    def test_reserved_location_external_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="reserved for a future release"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=".foo", location="external"))

    # --- scope: global ---

    def test_global_entry_parsed(self, tmp_path):
        r = self._load(tmp_path, "name: r\npersist:\n  - scope: global\n    path: ~/.gbrain\n")
        e = r.persist.entries[0]
        assert e.scope == "global" and e.path == "~/.gbrain"
        assert e.name is None and e.location is None and e.vcs is None

    def test_global_with_location_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="'location' is not valid for scope: global"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: global\n    path: ~/.gbrain\n    location: host\n")

    def test_global_with_name_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="use 'path'"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: global\n    name: .gbrain\n")

    def test_global_empty_path_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="non-empty 'path'"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: global\n    path: ''\n")

    def test_global_path_used_not_name(self, tmp_path):
        with pytest.raises(SchemaError, match="use 'path'"):
            self._load(tmp_path, "name: r\npersist:\n  - scope: global\n    name: .gbrain\n")

    # --- unknown fields rejected ---

    def test_unknown_field_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown field"):
            self._load(tmp_path, self._yaml_entry(scope="workspace", name=".foo", location="host", typo="x"))

    # --- multiple entries ---

    def test_multiple_entries_parsed(self, tmp_path):
        body = (
            "name: r\npersist:\n"
            "  - name: .beads\n    scope: project\n    location: host\n"
            "  - name: notes.md\n    scope: workspace\n    location: in_repo\n    vcs: ignored\n"
            "  - scope: global\n    path: ~/.gbrain\n"
        )
        r = self._load(tmp_path, body)
        assert len(r.persist.entries) == 3
        assert r.persist.entries[0].scope == "project"
        assert r.persist.entries[1].vcs == "ignored"
        assert r.persist.entries[2].scope == "global"


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
            "expect:\n  skills: [x]\n"
            "persist:\n  - name: .x\n    scope: workspace\n    location: host\n"
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

    def test_strict_allows_init_field(self, tmp_path):
        body = (
            "name: r\n"
            "init:\n"
            "  run: bd list >/dev/null 2>&1 || bd init --quiet --stealth\n"
        )
        r = self._load(tmp_path, body, strict=True)
        assert r.name == "r"


class TestInitParse:
    """init: field parsing (Model A) — just the `run` command; no host-side marker."""

    def _load(self, tmp_path, body: str) -> Recipe:
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return load_recipe(d)

    # --- Absent / None ---

    def test_absent_init_is_none(self, tmp_path):
        r = self._load(tmp_path, "name: r\n")
        assert r.init is None

    # --- Valid cases ---

    def test_run_only_valid(self, tmp_path):
        r = self._load(tmp_path, "name: r\ninit:\n  run: bd list || bd init\n")
        assert r.init is not None
        assert r.init.run == "bd list || bd init"

    def test_run_is_stripped(self, tmp_path):
        r = self._load(tmp_path, "name: r\ninit:\n  run: '  ctx init  '\n")
        assert r.init.run == "ctx init"

    # --- run validation ---

    def test_missing_run_rejected(self, tmp_path):
        # A non-empty init: mapping with no `run` key must fail (the run check runs first).
        with pytest.raises(SchemaError, match="'run' is required"):
            self._load(tmp_path, "name: r\ninit:\n  other: x\n")

    def test_empty_run_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="'run' is required"):
            self._load(tmp_path, "name: r\ninit:\n  run: ''\n")

    # --- unknown field (the old marker is now rejected) ---

    def test_marker_field_now_rejected(self, tmp_path):
        body = (
            "name: r\ninit:\n  run: bd init\n"
            "  marker:\n    scope: project\n    location: host\n    name: .beads\n"
        )
        with pytest.raises(SchemaError, match="unknown field"):
            self._load(tmp_path, body)

    def test_unknown_field_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown field"):
            self._load(tmp_path, "name: r\ninit:\n  run: cmd\n  bogus: 1\n")

    # --- init not a mapping ---

    def test_init_not_a_mapping_rejected(self, tmp_path):
        with pytest.raises(SchemaError):
            self._load(tmp_path, "name: r\ninit: not-a-dict\n")


class TestHooksParse:
    """hooks: field parsing (GAP 2) — event validation, command/matcher entries."""

    def _load(self, tmp_path, body: str) -> Recipe:
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        return load_recipe(d)

    def test_absent_hooks_is_empty_dict(self, tmp_path):
        r = self._load(tmp_path, "name: r\n")
        assert r.hooks == {}

    def test_empty_list_hooks_is_empty_dict(self, tmp_path):
        # Matches the existing D-14 forward-field test (`hooks: []`) — falsy raw value short-circuits.
        r = self._load(tmp_path, "name: r\nhooks: []\n")
        assert r.hooks == {}

    def test_session_start_without_matcher(self, tmp_path):
        body = (
            "name: r\nhooks:\n  SessionStart:\n"
            "    - command: /usr/local/bin/caveman-remind\n"
        )
        r = self._load(tmp_path, body)
        assert r.hooks["SessionStart"] == [HookCommand(command="/usr/local/bin/caveman-remind", matcher=None)]

    def test_pre_tool_use_with_matcher(self, tmp_path):
        body = (
            "name: r\nhooks:\n  PreToolUse:\n"
            "    - matcher: Bash\n      command: some-hook\n"
        )
        r = self._load(tmp_path, body)
        assert r.hooks["PreToolUse"] == [HookCommand(command="some-hook", matcher="Bash")]

    def test_multiple_entries_same_event(self, tmp_path):
        body = (
            "name: r\nhooks:\n  PreToolUse:\n"
            "    - matcher: Bash\n      command: hook-a\n"
            "    - matcher: Read\n      command: hook-b\n"
        )
        r = self._load(tmp_path, body)
        assert len(r.hooks["PreToolUse"]) == 2

    def test_multiple_events(self, tmp_path):
        body = (
            "name: r\nhooks:\n"
            "  SessionStart:\n    - command: hook-a\n"
            "  Stop:\n    - command: hook-b\n"
        )
        r = self._load(tmp_path, body)
        assert set(r.hooks) == {"SessionStart", "Stop"}

    def test_unknown_event_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStarts:\n    - command: hook-a\n"
        with pytest.raises(SchemaError, match="unknown event 'SessionStarts'"):
            self._load(tmp_path, body)

    def test_hooks_not_a_mapping_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="must be a mapping"):
            self._load(tmp_path, "name: r\nhooks: not-a-dict\n")

    def test_event_not_a_list_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart: not-a-list\n"
        with pytest.raises(SchemaError, match="must be a non-empty list"):
            self._load(tmp_path, body)

    def test_empty_event_list_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart: []\n"
        with pytest.raises(SchemaError, match="must be a non-empty list"):
            self._load(tmp_path, body)

    def test_entry_missing_command_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - matcher: startup\n"
        with pytest.raises(SchemaError, match="missing required non-empty 'command'"):
            self._load(tmp_path, body)

    def test_entry_empty_command_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - command: ''\n"
        with pytest.raises(SchemaError, match="missing required non-empty 'command'"):
            self._load(tmp_path, body)

    def test_entry_not_a_mapping_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - just-a-string\n"
        with pytest.raises(SchemaError, match="entries must be mappings"):
            self._load(tmp_path, body)

    def test_entry_matcher_not_a_string_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - command: hook-a\n      matcher: 5\n"
        with pytest.raises(SchemaError, match="'matcher' must be a string"):
            self._load(tmp_path, body)

    def test_entry_unknown_field_rejected(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - command: hook-a\n      extra: bad\n"
        with pytest.raises(SchemaError, match="unknown field"):
            self._load(tmp_path, body)

    def test_strict_allows_typed_hooks_field(self, tmp_path):
        body = "name: r\nhooks:\n  SessionStart:\n    - command: hook-a\n"
        d = tmp_path / "rcp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text(body)
        r = load_recipe(d, strict=True)
        assert r.name == "r"


class TestRecipeConflicts:
    def test_parse_defaults_to_empty(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\n")
        assert load_recipe(d).conflicts == []

    def test_parse_conflicts_list(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nconflicts: [other]\n")
        assert load_recipe(d).conflicts == ["other"]

    def test_non_list_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nconflicts: other\n")
        with pytest.raises(SchemaError, match="must be a list"):
            load_recipe(d)

    def test_empty_string_entry_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nconflicts: ['']\n")
        with pytest.raises(SchemaError, match="non-empty strings"):
            load_recipe(d)

    def _write_recipe(self, root: Path, name: str, conflicts: list[str] | None = None) -> None:
        d = root / "recipes" / name
        d.mkdir(parents=True)
        conflicts_line = f"conflicts: {conflicts}\n" if conflicts else ""
        (d / "recipe.yaml").write_text(f"name: {name}\n{conflicts_line}")

    def _write_stack(self, root: Path, name: str, recipes: list[str]) -> None:
        d = root / "stacks" / name
        d.mkdir(parents=True)
        (d / "stack.yaml").write_text(f"name: {name}\nharness: claude\nrecipes: {recipes}\n")

    def test_no_conflict_loads_cleanly(self, tmp_path):
        from harnessed.schema import load_stack_with_recipes

        self._write_recipe(tmp_path, "a")
        self._write_recipe(tmp_path, "b")
        self._write_stack(tmp_path, "s", ["a", "b"])
        _, recipes = load_stack_with_recipes(tmp_path, "s")
        assert [r.name for r in recipes] == ["a", "b"]

    def test_declared_conflict_raises(self, tmp_path):
        from harnessed.schema import load_stack_with_recipes

        self._write_recipe(tmp_path, "a", conflicts=["b"])
        self._write_recipe(tmp_path, "b")
        self._write_stack(tmp_path, "s", ["a", "b"])
        with pytest.raises(SchemaError, match="incompatible"):
            load_stack_with_recipes(tmp_path, "s")

    def test_conflict_is_symmetric_regardless_of_which_side_declares_it(self, tmp_path):
        from harnessed.schema import load_stack_with_recipes

        self._write_recipe(tmp_path, "a")
        self._write_recipe(tmp_path, "b", conflicts=["a"])
        self._write_stack(tmp_path, "s", ["a", "b"])
        with pytest.raises(SchemaError, match="incompatible"):
            load_stack_with_recipes(tmp_path, "s")

    def test_conflict_with_recipe_absent_from_stack_is_fine(self, tmp_path):
        from harnessed.schema import load_stack_with_recipes

        self._write_recipe(tmp_path, "a", conflicts=["not-in-this-stack"])
        self._write_stack(tmp_path, "s", ["a"])
        _, recipes = load_stack_with_recipes(tmp_path, "s")
        assert [r.name for r in recipes] == ["a"]
