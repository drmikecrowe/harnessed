"""Tests for emit.py — profile artifact emission (C1)."""

import json
from pathlib import Path

from harnessed.emit import (
    HATAGO_ENDPOINT,
    HATAGO_MCP_KEY,
    merge_opencode_config,
    merge_settings,
    opencode_agent_name,
    read_baked_settings,
    required_settings,
    write_antigravity_identity,
    write_claude_md,
    write_codex_agents_md,
    CODEX_AGENTS_MAX_BYTES,
    write_mcp_json,
    write_omp_identity,
    write_opencode_persona,
    write_settings_json,
    write_hatago_config,
    write_derived_dockerfile,
)
from harnessed.paths import container_project_path
from harnessed.schema import HookCommand, McpServer, Recipe, Stack

_GRANT = f"mcp__{HATAGO_MCP_KEY}"
# Every container defaults to auto-accept-edits; the grant rides alongside it when a stack has servers.
_MODE = {"defaultMode": "acceptEdits"}
_REQUIRED = {"permissions": {**_MODE, "allow": [_GRANT]}}


def _hook_recipe(name: str, hooks: dict) -> Recipe:
    return Recipe(name=name, hooks=hooks)


class TestWriteDerivedDockerfile:
    def _stack(self):
        return Stack(name="claude_time", harness="claude", recipes=["time"], services=[])

    def test_appends_supply_chain_scan_run_by_default(self, tmp_path):
        out = write_derived_dockerfile(tmp_path, self._stack(), [])
        body = out.read_text()
        assert "FROM harnessed-${HARNESS}:latest" in body
        # The final supply-chain layer (BLD-02) runs even when no recipe ships a Dockerfile.
        assert "harnessed-scan" in body
        assert "--mount=type=secret,id=snyk_token" in body

    def test_no_scan_when_disabled(self, tmp_path):
        out = write_derived_dockerfile(tmp_path, self._stack(), [], with_scan=False)
        assert "harnessed-scan" not in out.read_text()


class TestWriteClaudeMd:
    def test_emits_instructions_into_claude_md(self, tmp_path):
        out = write_claude_md(tmp_path, "You are the release-bot for repo X.")
        assert out == tmp_path / ".claude" / "CLAUDE.md"
        assert out.read_text() == "You are the release-bot for repo X.\n"

    def test_preserves_trailing_newline(self, tmp_path):
        out = write_claude_md(tmp_path, "identity text\n")
        assert out.read_text() == "identity text\n"

    def test_noop_when_instructions_unset(self, tmp_path):
        assert write_claude_md(tmp_path, None) is None
        assert not (tmp_path / ".claude" / "CLAUDE.md").exists()


class TestOpencodeAgentName:
    def test_sanitizes_stack_name(self):
        assert opencode_agent_name("opencode_Release Bot") == "opencode-release-bot"

    def test_falls_back_when_no_usable_chars(self):
        assert opencode_agent_name("___") == "persona"


class TestWriteOpencodePersona:
    def test_writes_prompt_file_under_opencode_prompts(self, tmp_path):
        out = write_opencode_persona(tmp_path, "You are release-bot.", "rel")
        assert out == tmp_path / "opencode" / "prompts" / "rel.md"
        assert out.read_text() == "You are release-bot.\n"

    def test_noop_when_instructions_unset(self, tmp_path):
        assert write_opencode_persona(tmp_path, None, "rel") is None
        assert not (tmp_path / "opencode").exists()


class TestMergeOpencodeConfig:
    # The image-baked config the launcher reads back: hatago MCP block that must survive the merge.
    def _baked(self):
        return {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {"hatago": {"type": "remote", "url": "http://localhost:3535/mcp",
                               "enabled": True}},
        }

    def test_adds_agent_and_rules_glob_preserving_hatago(self):
        merged = merge_opencode_config(
            self._baked(), "rel", "./prompts/rel.md", "/home/harnessed/.claude/rules/*.md"
        )
        # Custom persona agent points at the persona prompt file.
        assert merged["agent"]["rel"] == {"prompt": "{file:./prompts/rel.md}"}
        # Rules-file glob appended to the native instructions[] array.
        assert merged["instructions"] == ["/home/harnessed/.claude/rules/*.md"]
        # The baked hatago MCP block survives verbatim.
        assert merged["mcp"]["hatago"]["url"] == "http://localhost:3535/mcp"

    def test_does_not_mutate_input(self):
        baked = self._baked()
        merge_opencode_config(baked, "rel", "./prompts/rel.md", "/g/*.md")
        assert "agent" not in baked and "instructions" not in baked

    def test_appends_glob_to_existing_instructions_without_dupe(self):
        baked = {**self._baked(), "instructions": ["AGENTS.md"]}
        merged = merge_opencode_config(baked, "rel", "./prompts/rel.md", "/g/*.md")
        assert merged["instructions"] == ["AGENTS.md", "/g/*.md"]
        # Idempotent — re-adding the same glob does not duplicate it.
        again = merge_opencode_config(merged, "rel", "./prompts/rel.md", "/g/*.md")
        assert again["instructions"] == ["AGENTS.md", "/g/*.md"]


class TestWriteAntigravityIdentity:
    def test_emits_identity_md_and_settings_context_filename(self, tmp_path):
        from harnessed.paths import CONTAINER_HOME

        out = write_antigravity_identity(tmp_path, "You are the release-bot for repo X.")
        # Identity text lands in the profile's .gemini/GEMINI.md (agy's native memory tree).
        assert out == tmp_path / ".gemini" / "GEMINI.md"
        assert out.read_text() == "You are the release-bot for repo X.\n"
        # A fresh settings.json points context.fileName at the ABSOLUTE in-container identity path.
        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        assert settings == {
            "context": {"fileName": str(CONTAINER_HOME / ".gemini" / "GEMINI.md")}
        }

    def test_preserves_trailing_newline(self, tmp_path):
        out = write_antigravity_identity(tmp_path, "identity text\n")
        assert out.read_text() == "identity text\n"

    def test_noop_when_instructions_unset(self, tmp_path):
        assert write_antigravity_identity(tmp_path, None) is None
        assert not (tmp_path / ".gemini").exists()


class TestWriteCodexAgentsMd:
    def _rule(self, profile_dir: Path, name: str, body: str) -> Path:
        p = profile_dir / ".claude" / "rules" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_emits_identity_then_rules_under_cap(self, tmp_path):
        r1 = self._rule(tmp_path, "coding-principles/RULE.md", "Keep changes surgical.")
        r2 = self._rule(tmp_path, "signed-commits/RULE.md", "All commits must be signed.")
        out = write_codex_agents_md(tmp_path, "You are the codex release-bot.", [r1, r2])

        assert out == tmp_path / ".codex" / "AGENTS.md"
        text = out.read_text()
        # identity comes first, then each rule under its header
        i_identity = text.index("codex release-bot")
        i_r1 = text.index("Keep changes surgical.")
        i_r2 = text.index("All commits must be signed.")
        assert i_identity < i_r1 < i_r2
        assert "## Rule: coding-principles/RULE.md" in text
        assert "## Rule: signed-commits/RULE.md" in text
        assert len(text.encode("utf-8")) <= CODEX_AGENTS_MAX_BYTES

    def test_noop_when_no_identity_and_no_rules(self, tmp_path):
        assert write_codex_agents_md(tmp_path, None, []) is None
        assert not (tmp_path / ".codex" / "AGENTS.md").exists()

    def test_identity_only_when_no_rules(self, tmp_path):
        out = write_codex_agents_md(tmp_path, "identity only", [])
        assert out.read_text() == "identity only\n"

    def test_rules_only_when_no_identity(self, tmp_path):
        r1 = self._rule(tmp_path, "a/RULE.md", "rule body a")
        out = write_codex_agents_md(tmp_path, None, [r1])
        text = out.read_text()
        assert "## Rule: a/RULE.md" in text
        assert "rule body a" in text

    def test_truncates_with_warning_over_cap(self, tmp_path):
        warnings: list[str] = []
        big = self._rule(tmp_path, "big/RULE.md", "x" * (CODEX_AGENTS_MAX_BYTES + 5000))
        out = write_codex_agents_md(tmp_path, "identity", [big], warn=warnings.append)
        data = out.read_bytes()
        assert len(data) <= CODEX_AGENTS_MAX_BYTES
        assert b"truncated" in data
        assert warnings and "truncated" in warnings[0]


class TestWriteOmpIdentity:
    def _rule(self, profile_dir: Path, name: str, body: str) -> Path:
        p = profile_dir / ".claude" / "rules" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_writes_delimiter_blocks_for_identity_and_rules(self, tmp_path):
        agent = tmp_path / "agent"
        r1 = self._rule(tmp_path, "coding-principles/RULE.md", "Keep changes surgical.")
        r2 = self._rule(tmp_path, "signed-commits/RULE.md", "All commits must be signed.")

        written = write_omp_identity(
            tmp_path, "release-bot", "You are the omp release-bot.", [r1, r2], agent_dir=agent
        )

        append_system = agent / "APPEND_SYSTEM.md"
        rules_file = agent / "RULES.md"
        assert written == [append_system, rules_file]

        sys_text = append_system.read_text()
        assert "<!-- BEGIN harnessed:release-bot -->" in sys_text
        assert "<!-- END harnessed:release-bot -->" in sys_text
        assert "You are the omp release-bot." in sys_text

        rules_text = rules_file.read_text()
        assert "<!-- BEGIN harnessed:release-bot -->" in rules_text
        assert "## Rule: coding-principles/RULE.md" in rules_text
        assert "Keep changes surgical." in rules_text
        assert "## Rule: signed-commits/RULE.md" in rules_text
        assert "All commits must be signed." in rules_text

    def test_second_run_replaces_block_not_duplicated(self, tmp_path):
        agent = tmp_path / "agent"
        r1 = self._rule(tmp_path, "a/RULE.md", "first rule body")
        write_omp_identity(tmp_path, "s1", "identity v1", [r1], agent_dir=agent)

        # Re-run with changed content for the SAME stack.
        r1.write_text("second rule body", encoding="utf-8")
        write_omp_identity(tmp_path, "s1", "identity v2", [r1], agent_dir=agent)

        sys_text = (agent / "APPEND_SYSTEM.md").read_text()
        assert sys_text.count("<!-- BEGIN harnessed:s1 -->") == 1
        assert "identity v2" in sys_text
        assert "identity v1" not in sys_text

        rules_text = (agent / "RULES.md").read_text()
        assert rules_text.count("<!-- BEGIN harnessed:s1 -->") == 1
        assert "second rule body" in rules_text
        assert "first rule body" not in rules_text

    def test_preserves_other_stacks_block(self, tmp_path):
        agent = tmp_path / "agent"
        write_omp_identity(tmp_path, "alpha", "alpha identity", [], agent_dir=agent)
        write_omp_identity(tmp_path, "beta", "beta identity", [], agent_dir=agent)

        sys_text = (agent / "APPEND_SYSTEM.md").read_text()
        assert "<!-- BEGIN harnessed:alpha -->" in sys_text
        assert "<!-- BEGIN harnessed:beta -->" in sys_text
        assert "alpha identity" in sys_text
        assert "beta identity" in sys_text

    def test_noop_when_no_identity_and_no_rules(self, tmp_path):
        agent = tmp_path / "agent"
        assert write_omp_identity(tmp_path, "s1", None, [], agent_dir=agent) == []
        assert not agent.exists()

    def test_empty_rules_are_skipped(self, tmp_path):
        agent = tmp_path / "agent"
        blank = self._rule(tmp_path, "blank/RULE.md", "   \n")
        assert write_omp_identity(tmp_path, "s1", None, [blank], agent_dir=agent) == []
        assert not agent.exists()

    def test_switching_source_off_removes_stale_block(self, tmp_path):
        agent = tmp_path / "agent"
        r1 = self._rule(tmp_path, "a/RULE.md", "rule body")
        write_omp_identity(tmp_path, "s1", "identity text", [r1], agent_dir=agent)

        # Re-run with rules dropped: RULES.md block for s1 goes away; identity stays.
        written = write_omp_identity(tmp_path, "s1", "identity text", [], agent_dir=agent)
        assert written == [agent / "APPEND_SYSTEM.md"]
        assert "<!-- BEGIN harnessed:s1 -->" not in (agent / "RULES.md").read_text()
        assert "<!-- BEGIN harnessed:s1 -->" in (agent / "APPEND_SYSTEM.md").read_text()


class TestWriteMcpJson:
    def test_creates_mcp_json_at_profile_root(self, tmp_path):
        out = write_mcp_json(tmp_path)
        assert out == tmp_path / ".mcp.json"
        assert out.is_file()

    def test_content_has_single_hatago_entry(self, tmp_path):
        write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        servers = data["mcpServers"]
        assert HATAGO_MCP_KEY in servers
        assert len(servers) == 1

    def test_entry_has_http_type(self, tmp_path):
        write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        entry = data["mcpServers"][HATAGO_MCP_KEY]
        assert entry["type"] == "http"
        assert entry["url"] == HATAGO_ENDPOINT

    def test_output_is_at_root_not_claude_subdir(self, tmp_path):
        out = write_mcp_json(tmp_path)
        # Must be profile_dir/.mcp.json, NOT profile_dir/.claude/.mcp.json
        assert ".claude" not in str(out)


class TestWriteSettingsJson:
    def test_no_servers_writes_defaultmode_floor(self, tmp_path):
        # Even a serverless/hookless stack gets the auto-accept-edits default in its floor.
        out = write_settings_json(tmp_path, [])
        data = json.loads(out.read_text())
        assert data == {"permissions": {"defaultMode": "acceptEdits"}}

    def test_with_servers_pre_approves_hatago(self, tmp_path):
        servers = [McpServer(name="time", command="pnpm")]
        out = write_settings_json(tmp_path, servers)
        data = json.loads(out.read_text())
        assert f"mcp__{HATAGO_MCP_KEY}" in data["permissions"]["allow"]

    def test_recipe_hooks_included_with_no_servers(self, tmp_path):
        # A hooks-only recipe (no MCP servers) must still get its hooks into the floor stub.
        recipe = _hook_recipe("caveman", {"SessionStart": [HookCommand(command="caveman-remind")]})
        out = write_settings_json(tmp_path, [], [recipe])
        data = json.loads(out.read_text())
        assert data == {
            "permissions": {"defaultMode": "acceptEdits"},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "caveman-remind"}]}]},
        }


class TestWriteHatagoConfig:
    def test_stdio_server_gets_command_entry(self, tmp_path):
        servers = [McpServer(name="time", command="pnpm", args=["dlx", "@time/server"])]
        write_hatago_config(tmp_path, servers)
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        entry = data["mcpServers"]["time"]
        assert entry["command"] == "pnpm"
        assert entry["args"] == ["dlx", "@time/server"]

    def test_stdio_entry_has_no_cwd_without_project_path(self, tmp_path):
        # The committed (assemble-time) config is project-agnostic — no cwd baked (bd main-u5d).
        servers = [McpServer(name="serena", command="serena", args=["start-mcp-server"])]
        write_hatago_config(tmp_path, servers)
        entry = json.loads((tmp_path / "hatago.config.json").read_text())["mcpServers"]["serena"]
        assert "cwd" not in entry

    def test_stdio_entry_gets_project_cwd(self, tmp_path):
        # bd main-u5d: a stdio child's cwd is pinned to the mirrored container-side project path so
        # serena --project-from-cwd / repowise's default resolve the project, not the container home.
        servers = [McpServer(name="serena", command="serena", args=["start-mcp-server"])]
        project = "/home/dev/myproject"
        write_hatago_config(tmp_path, servers, project)
        entry = json.loads((tmp_path / "hatago.config.json").read_text())["mcpServers"]["serena"]
        assert entry["cwd"] == str(container_project_path(project))
        assert entry["cwd"] == "/home/dev/myproject"

    def test_http_entry_unaffected_by_project_path(self, tmp_path):
        # cwd is a stdio-only concern — a URL-proxied server never gets one.
        servers = [McpServer(name="remote", transport="http", url="http://localhost:8080/mcp")]
        write_hatago_config(tmp_path, servers, "/home/dev/myproject")
        entry = json.loads((tmp_path / "hatago.config.json").read_text())["mcpServers"]["remote"]
        assert "cwd" not in entry

    def test_http_server_gets_url_entry(self, tmp_path):
        servers = [McpServer(name="remote", transport="http", url="http://localhost:8080/mcp")]
        write_hatago_config(tmp_path, servers)
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        entry = data["mcpServers"]["remote"]
        assert entry["url"] == "http://localhost:8080/mcp"
        assert entry["type"] == "http"

    def test_version_is_1(self, tmp_path):
        write_hatago_config(tmp_path, [])
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        assert data["version"] == 1


class TestRequiredSettings:
    """harnessed's sole settings contribution — the single source of truth shared by the
    assemble-time floor and the post-build merge."""

    def test_grant_when_servers(self):
        assert required_settings([McpServer(name="time", command="pnpm")]) == _REQUIRED

    def test_defaultmode_only_when_no_servers(self):
        assert required_settings([]) == {"permissions": {"defaultMode": "acceptEdits"}}

    def test_defaultmode_only_when_recipes_have_no_hooks(self):
        assert required_settings([], [_hook_recipe("r", {})]) == {
            "permissions": {"defaultMode": "acceptEdits"}
        }

    def test_hooks_rendered_into_native_claude_shape(self):
        recipe = _hook_recipe("caveman", {
            "SessionStart": [HookCommand(command="caveman-remind", matcher=None)],
        })
        assert required_settings([], [recipe]) == {
            "permissions": {"defaultMode": "acceptEdits"},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "caveman-remind"}]}]},
        }

    def test_matcher_included_when_present(self):
        recipe = _hook_recipe("r", {"PreToolUse": [HookCommand(command="hook-a", matcher="Bash")]})
        result = required_settings([], [recipe])
        assert result["hooks"]["PreToolUse"] == [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "hook-a"}]}
        ]

    def test_multiple_recipes_same_event_each_get_own_group(self):
        recipes = [
            _hook_recipe("a", {"SessionStart": [HookCommand(command="hook-a")]}),
            _hook_recipe("b", {"SessionStart": [HookCommand(command="hook-b")]}),
        ]
        result = required_settings([], recipes)
        assert result["hooks"]["SessionStart"] == [
            {"hooks": [{"type": "command", "command": "hook-a"}]},
            {"hooks": [{"type": "command", "command": "hook-b"}]},
        ]

    def test_combines_grant_and_hooks(self):
        recipe = _hook_recipe("caveman", {"SessionStart": [HookCommand(command="caveman-remind")]})
        result = required_settings([McpServer(name="time", command="pnpm")], [recipe])
        assert result["permissions"]["allow"] == [_GRANT]
        assert "SessionStart" in result["hooks"]

    def test_defaultmode_always_acceptedits(self):
        # Present regardless of servers/hooks — every container defaults to auto-accept-edits.
        assert required_settings([])["permissions"]["defaultMode"] == "acceptEdits"
        assert required_settings([McpServer(name="time", command="pnpm")])["permissions"]["defaultMode"] == "acceptEdits"


class TestStackPermissionMode:
    """bd main-c5g: the stack's `permissions:` value drives permissions.defaultMode, and survives
    the post-build merge as a floor."""

    def test_unset_permissions_keeps_prior_acceptedits(self):
        # Regression floor: no `permissions:` on the stack → the historical auto-accept default.
        assert required_settings([], permissions=None)["permissions"]["defaultMode"] == "acceptEdits"

    def test_prompt_maps_to_default(self):
        assert required_settings([], permissions="prompt")["permissions"]["defaultMode"] == "default"

    def test_auto_maps_to_acceptedits(self):
        assert required_settings([], permissions="auto")["permissions"]["defaultMode"] == "acceptEdits"

    def test_yolo_maps_to_bypass(self):
        assert required_settings([], permissions="yolo")["permissions"]["defaultMode"] == "bypassPermissions"

    def test_unknown_value_falls_back_to_acceptedits(self):
        # An unrecognized mode never emits an invalid defaultMode — it degrades to the baseline.
        assert required_settings([], permissions="wat")["permissions"]["defaultMode"] == "acceptEdits"

    def test_write_settings_json_emits_stack_mode(self, tmp_path):
        out = write_settings_json(tmp_path, [], None, "yolo")
        data = json.loads(out.read_text())
        assert data["permissions"]["defaultMode"] == "bypassPermissions"

    def test_yolo_mode_survives_merge_against_recipe_baked_settings(self):
        # A recipe baked its own settings.json (hooks + an allow grant) but NO defaultMode — the
        # stack's yolo floor must land in the final merged file.
        required = write_settings_json_dict(permissions="yolo")
        baked = {"permissions": {"allow": ["mcp__other"]}, "hooks": {"PreToolUse": [{"matcher": "Bash"}]}}
        merged = merge_settings(baked, required)
        assert merged["permissions"]["defaultMode"] == "bypassPermissions"
        # baked content is still carried through verbatim
        assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}

    def test_recipe_baked_defaultmode_still_wins_over_stack(self):
        # Floor, not override: a recipe that explicitly baked a mode keeps it even under yolo.
        required = write_settings_json_dict(permissions="yolo")
        baked = {"permissions": {"defaultMode": "plan"}}
        assert merge_settings(baked, required)["permissions"]["defaultMode"] == "plan"


def write_settings_json_dict(**kwargs):
    """The required-settings dict for a stack with the given `permissions:` (test helper)."""
    return required_settings([], None, kwargs.get("permissions"))


class TestReadBakedSettings:
    def test_none_text_returns_none_silently(self):
        warns: list[str] = []
        assert read_baked_settings(None, warn=warns.append) is None
        assert warns == []  # absent file / cp failure is not a warning

    def test_valid_object_parses(self):
        assert read_baked_settings('{"hooks": {"PreToolUse": []}}') == {"hooks": {"PreToolUse": []}}

    def test_malformed_json_returns_none_and_warns(self):
        warns: list[str] = []
        assert read_baked_settings("{not json", warn=warns.append) is None
        assert len(warns) == 1  # a recipe wrote broken JSON — warn, do not crash

    def test_non_object_json_treated_as_malformed(self):
        warns: list[str] = []
        assert read_baked_settings("[1, 2, 3]", warn=warns.append) is None
        assert len(warns) == 1


class TestMergeSettings:
    """The surgical settings.json patch — baked file is authoritative; harnessed only unions its
    required grant into permissions.allow (and wins over a conflicting deny)."""

    def test_baked_none_returns_required_floor(self):
        # No image file / cp failed → the assemble-time floor stub stands.
        assert merge_settings(None, _REQUIRED) == _REQUIRED
        assert merge_settings(None, {}) == {}

    def test_empty_baked_gets_grant_only(self):
        assert merge_settings({}, _REQUIRED) == _REQUIRED

    def test_baked_hooks_preserved_and_grant_added(self):
        # REGRESSION proof: the bug was that baked hooks were silently dropped at runtime.
        baked = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_existing_allow_is_unioned(self):
        baked = {"permissions": {"allow": ["mcp__other"]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["permissions"]["allow"] == ["mcp__other", _GRANT]

    def test_grant_already_present_is_not_duplicated(self):
        baked = {"permissions": {"allow": [_GRANT]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_deny_conflict_required_wins_and_warns(self):
        warns: list[str] = []
        baked = {"permissions": {"deny": [_GRANT, "mcp__keep"]}}
        merged = merge_settings(baked, _REQUIRED, warn=warns.append)
        assert _GRANT in merged["permissions"]["allow"]
        assert merged["permissions"]["deny"] == ["mcp__keep"]  # only the conflicting grant stripped
        assert len(warns) == 1

    def test_defaultmode_injected_when_baked_lacks_it(self):
        # Floor: a baked file with no defaultMode gets harnessed's acceptEdits default.
        merged = merge_settings({"permissions": {"allow": ["mcp__x"]}}, _REQUIRED)
        assert merged["permissions"]["defaultMode"] == "acceptEdits"

    def test_baked_defaultmode_wins_over_floor(self):
        # A recipe/base that explicitly baked its own mode keeps it (floor, not override).
        baked = {"permissions": {"defaultMode": "plan"}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["permissions"]["defaultMode"] == "plan"

    def test_no_grant_when_required_empty_baked_untouched(self):
        # Serverless stack (required == {}): the baked file is returned verbatim, no grant injected.
        baked = {"hooks": {"PreToolUse": []}, "permissions": {"allow": ["mcp__x"]}}
        assert merge_settings(baked, {}) == baked

    def test_other_keys_carried_through_verbatim(self):
        baked = {"model": "opus", "env": {"FOO": "bar"}, "permissions": {"deny": ["mcp__x"]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["model"] == "opus"
        assert merged["env"] == {"FOO": "bar"}
        assert merged["permissions"]["deny"] == ["mcp__x"]  # untouched (not the grant)
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_does_not_mutate_input(self):
        baked = {"permissions": {"allow": ["mcp__other"]}}
        merge_settings(baked, _REQUIRED)
        assert baked == {"permissions": {"allow": ["mcp__other"]}}  # deepcopy — caller's dict safe

    # --- GAP 2: hooks union ---

    def test_required_hooks_appended_to_new_event(self):
        required = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "remind"}]}]}}
        merged = merge_settings({}, required)
        assert merged == required

    def test_required_hooks_appended_alongside_baked_same_event(self):
        baked = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "base-hook"}]}]}}
        required = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "recipe-hook"}]}]}}
        merged = merge_settings(baked, required)
        assert merged["hooks"]["SessionStart"] == [
            {"matcher": "startup", "hooks": [{"type": "command", "command": "base-hook"}]},
            {"hooks": [{"type": "command", "command": "recipe-hook"}]},
        ]

    def test_required_hooks_for_different_event_added_separately(self):
        baked = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}
        required = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "remind"}]}]}}
        merged = merge_settings(baked, required)
        assert merged["hooks"]["PreToolUse"] == [{"matcher": "Bash"}]
        assert merged["hooks"]["SessionStart"] == [{"hooks": [{"type": "command", "command": "remind"}]}]

    def test_no_required_hooks_leaves_baked_hooks_untouched(self):
        baked = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}

    def test_hooks_and_permissions_merge_together(self):
        baked = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}, "permissions": {"allow": ["mcp__other"]}}
        required = {
            "permissions": {"allow": [_GRANT]},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "remind"}]}]},
        }
        merged = merge_settings(baked, required)
        assert merged["permissions"]["allow"] == ["mcp__other", _GRANT]
        assert merged["hooks"]["PreToolUse"] == [{"matcher": "Bash"}]
        assert merged["hooks"]["SessionStart"] == [{"hooks": [{"type": "command", "command": "remind"}]}]
