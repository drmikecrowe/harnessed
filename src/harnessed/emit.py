"""Write the assembled artifacts into the mounted build dir (EMIT ONLY).

Pure file emission — no podman/docker, no daemon. Everything is written under
`profiles/<stack>/` inside the build dir:

  profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/   the fanned tree
  profiles/<stack>/.claude/.mcp.json                               single hatago endpoint
  profiles/<stack>/hatago.config.json                              hatago child-server config

The profile is regenerated from scratch on every run so the committed tree is a pure
function of the recipes/stack (reproducible build).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from copy import deepcopy
from pathlib import Path

# Matches exactly `ARG HARNESS` (with optional trailing whitespace) — the build-stage scope
# anchor emitted by the assembler. Must NOT strip ARGs like ARG HARNESS_PROXY_URL (WR-04).
_ARG_HARNESS_RE = re.compile(r'^ARG\s+HARNESS\s*$', re.IGNORECASE)

from . import paths
from .schema import McpServer, Recipe, Stack

# hatago's single Streamable-HTTP endpoint (design D-04; default port 3535, `HATAGO_PORT`
# overridable). Single source: `paths.hatago_endpoint()`. The harness `.mcp.json` points ONLY
# here — never at a stdio server directly.
HATAGO_ENDPOINT = paths.hatago_endpoint()
HATAGO_MCP_KEY = "hatago"

def reset_profile(profile_dir: Path) -> None:
    """Wipe and recreate the profile dir so emission is fully reproducible."""
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_mcp_json(profile_dir: Path) -> Path:
    """Emit the harness `.mcp.json` — exactly ONE entry pointing at the hatago endpoint.

    `type: http` is REQUIRED — Claude Code only treats an entry as a Streamable-HTTP server
    when the type is set; without it the server is not loaded. The launcher passes this file
    via `claude --mcp-config <file> --strict-mcp-config`, so hatago is the ONLY MCP server the
    isolated harness sees (no host/project/account-synced servers leak in).
    """
    out = profile_dir / ".mcp.json"
    _write_json(out, {"mcpServers": {HATAGO_MCP_KEY: {"type": "http", "url": HATAGO_ENDPOINT}}})
    return out


def write_claude_md(profile_dir: Path, instructions: str | None) -> Path | None:
    """Emit the stack's `instructions:` into the profile's `.claude/CLAUDE.md` — stack-level
    identity ("what is this assembled agent").

    This is the base/identity content of CLAUDE.md; any managed block a recipe appends later
    (e.g. a beads block) sits below it. No-op (returns None) when the stack sets no `instructions:`.
    Claude-only — the caller guards on the harness; CLAUDE.md is Claude's memory file.
    """
    if not instructions:
        return None
    out = profile_dir / ".claude" / "CLAUDE.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = instructions if instructions.endswith("\n") else instructions + "\n"
    out.write_text(text, encoding="utf-8")
    return out


def opencode_agent_name(stack_name: str) -> str:
    """Derive a stable opencode custom-agent name from the stack name (bd main-rlw).

    The SAME name keys the `agent.<name>` entry in opencode.json, names the persona prompt file,
    and forms the `opencode --agent <name>` attach command — all three must agree, so this is the
    single source. Sanitized to opencode's identifier charset (lowercase alnum + dash); falls back
    to 'persona' when the stack name has no usable characters.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", stack_name.lower()).strip("-")
    return slug or "persona"


def write_opencode_persona(
    profile_dir: Path, instructions: str | None, agent_name: str
) -> Path | None:
    """Emit the stack's `instructions:` identity as an opencode persona prompt file (bd main-rlw).

    Written to `<profile>/opencode/prompts/<agent_name>.md`; the launcher mounts the `opencode/`
    dir over `~/.config/opencode/prompts/` so opencode.json's `{file:./prompts/<agent_name>.md}`
    reference resolves. No-op (returns None) when the stack sets no `instructions:` — opencode's
    identity analog of `write_claude_md` (opencode reads a custom-agent prompt, not CLAUDE.md, for
    a per-stack persona).
    """
    if not instructions:
        return None
    out = profile_dir / "opencode" / "prompts" / f"{agent_name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = instructions if instructions.endswith("\n") else instructions + "\n"
    out.write_text(text, encoding="utf-8")
    return out


def merge_opencode_config(
    baked: dict, agent_name: str, persona_rel: str, rules_glob: str
) -> dict:
    """Merge harnessed's stack identity into the image-baked opencode.json (bd main-rlw).

    Mirrors `merge_settings`: the baked config is authoritative (it carries the `mcp.hatago` block
    the base image wired) and is carried through VERBATIM; harnessed only ADDS two things:
      - `agent.<agent_name>` = {"prompt": "{file:<persona_rel>}"} — the custom persona agent,
        invoked via `opencode --agent <agent_name>`. Agent permissions inherit the global config.
      - `rules_glob` appended to the top-level `instructions[]` array (opencode's native rules-file
        glob), so the profile's `.claude/rules/*.md` load into the agent's context for free.
    The baked `mcp.hatago` block is preserved untouched. Idempotent: an already-present glob is not
    duplicated; the agent entry is (re)written to the current persona reference.
    """
    result = deepcopy(baked)
    result.setdefault("agent", {})[agent_name] = {"prompt": f"{{file:{persona_rel}}}"}
    instructions = result.get("instructions")
    if not isinstance(instructions, list):
        instructions = []
        result["instructions"] = instructions
    if rules_glob not in instructions:
        instructions.append(rules_glob)
    return result


def write_antigravity_identity(profile_dir: Path, instructions: str | None) -> Path | None:
    """Emit the stack's `instructions:` as antigravity's native identity — a context `.md` under
    `.gemini/` plus a fresh `settings.json` whose `context.fileName` points at it (bd main-72j).

    Antigravity (agy) is gemini-cli-derived: it reads a top-level memory/context file, and the file
    it loads is declared by `context.fileName` in `~/.gemini/settings.json` — the same shared config
    tree as the already-baked `~/.gemini/config/mcp_config.json`. agy does NOT read Claude's
    `.claude/CLAUDE.md`, so the identity is baked here in agy's own shape instead.

    The profile's `.gemini/` mirrors the container's `~/.gemini/` (= CONTAINER_HOME/.gemini), so
    `context.fileName` is written as the ABSOLUTE in-container path of the identity file — unambiguous
    regardless of the agent's cwd (mirroring the fully-qualified `serverUrl` in the baked mcp_config).

    Unlike claude's `settings.json` FLOOR (a floor merged with the image-baked file post-build),
    antigravity's settings.json is never host-mounted or merged, so this writes it FRESH. No-op
    (returns None) when the stack sets no `instructions:`. Returns the identity `.md` path.
    """
    if not instructions:
        return None
    gemini_dir = profile_dir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    identity = gemini_dir / "GEMINI.md"
    text = instructions if instructions.endswith("\n") else instructions + "\n"
    identity.write_text(text, encoding="utf-8")
    container_identity = paths.CONTAINER_HOME / ".gemini" / "GEMINI.md"
    _write_json(gemini_dir / "settings.json", {"context": {"fileName": str(container_identity)}})
    return identity


# codex's `project_doc_max_bytes` default (32 KiB): AGENTS.md above this is silently truncated by
# codex itself. Identity + inlined rules SHARE this one file, so we keep the emitted doc under the
# cap and truncate ourselves (with a visible marker) rather than let codex cut mid-rule.
CODEX_AGENTS_MAX_BYTES = 32 * 1024

_CODEX_TRUNC_MARKER = (
    "\n\n<!-- harnessed: truncated — exceeded codex project_doc_max_bytes (32 KiB) -->\n"
)


def _stderr_warn(msg: str) -> None:
    print(f"harnessed: {msg}", file=sys.stderr)


def _rule_label(rule_path: Path, profile_dir: Path) -> str:
    """Human-readable delimiter for a rule body — its path relative to `.claude/rules/`."""
    rules_root = profile_dir / ".claude" / "rules"
    try:
        return str(rule_path.relative_to(rules_root))
    except ValueError:
        return rule_path.name


def write_codex_agents_md(
    profile_dir: Path,
    instructions: str | None,
    rules: list[Path] | None = None,
    *,
    warn=None,
) -> Path | None:
    """Emit the codex harness's top-level memory doc `.codex/AGENTS.md` = the stack's `instructions:`
    identity followed by every recipe rule `.md` body, concatenated with per-rule headers.

    Codex has no directory-rules primitive (unlike Claude's `.claude/rules/`), so the rules Claude
    reads as separate files must be inlined into the ONE doc codex reads (AGENTS.md). Identity comes
    first; each rule follows under a `## Rule: <name>` header (`<name>` is the rule's path relative
    to `.claude/rules/`).

    Identity + rules share this file and codex caps AGENTS.md at `project_doc_max_bytes` (32 KiB by
    default), silently dropping the tail beyond that. We truncate to fit under the cap ourselves and
    append a visible marker + WARN, rather than letting codex cut mid-rule. No-op (returns None) when
    there is neither identity nor any non-empty rule.

    Additive counterpart to codex's `model_instructions_file` (which REPLACES built-in instructions
    entirely) — AGENTS.md is the default, additive target; the replace-everything file stays an
    explicit opt-in escape hatch.
    """
    _warn = warn or _stderr_warn

    parts: list[str] = []
    if instructions:
        parts.append(instructions.strip())
    for rule_path in rules or []:
        body = rule_path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        parts.append(f"## Rule: {_rule_label(rule_path, profile_dir)}\n\n{body}")

    if not parts:
        return None

    text = "\n\n".join(parts) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > CODEX_AGENTS_MAX_BYTES:
        budget = CODEX_AGENTS_MAX_BYTES - len(_CODEX_TRUNC_MARKER.encode("utf-8"))
        # errors="ignore" drops a partial multibyte char at the cut, so the re-encoded head is ≤ budget
        # and head+marker stays ≤ CODEX_AGENTS_MAX_BYTES.
        text = encoded[:budget].decode("utf-8", errors="ignore") + _CODEX_TRUNC_MARKER
        _warn(
            f".codex/AGENTS.md exceeded codex's {CODEX_AGENTS_MAX_BYTES}-byte "
            "project_doc_max_bytes cap; truncated identity+rules to fit"
        )

    out = profile_dir / ".codex" / "AGENTS.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


# omp (Oh My Pi) shared-agent identity/rules delivery (bd main-w8k).
#
# omp reads two plain-markdown files from its agent dir: APPEND_SYSTEM.md (appended to the system
# prompt) and RULES.md (rules). The omp harness runs the pre-installed omp-claude-hooks-bridge, a
# PURE hook-execution bridge with no content-injection path (its session_start handler only posts a
# UI notification — it never reads additionalContext), so a per-profile identity mount like the
# other harnesses use is impossible without an upstream bridge change. Instead we deliver identity +
# rules by writing GUARDED, IDEMPOTENT, delimiter-marked per-stack blocks into the SHARED host
# ~/.omp/agent/{APPEND_SYSTEM.md,RULES.md} — the same dir the launcher bind-mounts rw into every omp
# pod (_omp_agent_mount), so no new delivery path is invented. TRADE-OFF (accepted, documented): the
# blocks are shared across ALL omp usage (host + every container), NOT profile-scoped. Real
# per-profile bridge injection is a separate future upstream contribution.
_OMP_APPEND_SYSTEM_FILE = "APPEND_SYSTEM.md"
_OMP_RULES_FILE = "RULES.md"


def _default_omp_agent_dir() -> Path:
    """Host omp agent dir (~/.omp/agent) — the dir the launcher bind-mounts rw into every omp pod."""
    return Path.home() / ".omp" / "agent"


def _managed_block(stack_name: str, body: str) -> str:
    """A delimiter-marked managed block for `stack_name` wrapping `body` (bd main-w8k)."""
    return (
        f"<!-- BEGIN harnessed:{stack_name} -->\n"
        f"{body.strip(chr(10))}\n"
        f"<!-- END harnessed:{stack_name} -->\n"
    )


def _managed_block_re(stack_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"<!-- BEGIN harnessed:{re.escape(stack_name)} -->.*?"
        rf"<!-- END harnessed:{re.escape(stack_name)} -->\n?",
        re.DOTALL,
    )


def upsert_managed_block(text: str, stack_name: str, body: str) -> str:
    """Insert or REPLACE this stack's delimiter-marked block in `text` (bd main-w8k).

    Idempotent: a re-run replaces the existing `<!-- BEGIN harnessed:<stack> -->…<!-- END … -->`
    block in place (no duplication); a first run appends it after any existing content (separated by
    a blank line). Other stacks' blocks and any surrounding content are left untouched.
    """
    block = _managed_block(stack_name, body)
    pattern = _managed_block_re(stack_name)
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text)
    if text and not text.endswith("\n"):
        text += "\n"
    if text:
        text += "\n"
    return text + block


def _upsert_block_file(path: Path, stack_name: str, body: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.write_text(upsert_managed_block(existing, stack_name, body), encoding="utf-8")


def _remove_block_file(path: Path, stack_name: str) -> None:
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    updated = _managed_block_re(stack_name).sub("", existing)
    if updated != existing:
        path.write_text(updated, encoding="utf-8")


def write_omp_identity(
    profile_dir: Path,
    stack_name: str,
    instructions: str | None,
    rules: list[Path] | None = None,
    *,
    agent_dir: Path | None = None,
) -> list[Path]:
    """Deliver the omp stack's identity + rules as delimiter-marked blocks in ~/.omp/agent (bd main-w8k).

    Identity (`instructions:`) → a `harnessed:<stack>` block in APPEND_SYSTEM.md; the recipe rules
    (the fanned `.claude/rules/*.md`, concatenated under `## Rule: <label>` headers, mirroring codex)
    → the same-keyed block in RULES.md. Both writes are idempotent per stack — a re-run REPLACES the
    stack's block rather than duplicating it (see `upsert_managed_block`). When the stack switches a
    source off, its now-stale block is removed from that file.

    No-op (returns `[]`, and does NOT create the agent dir) when the stack has neither identity nor
    any non-empty rule. `agent_dir` defaults to the shared host `~/.omp/agent` (test seam).
    """
    agent_dir = agent_dir or _default_omp_agent_dir()

    rule_parts: list[str] = []
    for rule_path in rules or []:
        body = rule_path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        rule_parts.append(f"## Rule: {_rule_label(rule_path, profile_dir)}\n\n{body}")
    rules_body = "\n\n".join(rule_parts)

    identity = instructions.strip() if instructions else ""
    if not identity and not rules_body:
        return []

    agent_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    append_system = agent_dir / _OMP_APPEND_SYSTEM_FILE
    if identity:
        _upsert_block_file(append_system, stack_name, identity)
        written.append(append_system)
    else:
        _remove_block_file(append_system, stack_name)

    rules_file = agent_dir / _OMP_RULES_FILE
    if rules_body:
        _upsert_block_file(rules_file, stack_name, rules_body)
        written.append(rules_file)
    else:
        _remove_block_file(rules_file, stack_name)

    return written


def _recipe_hooks_settings(recipes: list[Recipe]) -> dict:
    """Build the settings.json `hooks` block from each recipe's declared `hooks:` (GAP 2).

    Renders straight into Claude Code's native hooks shape: {EventName: [{matcher?, hooks:
    [{type: "command", command}]}]}. Each recipe-declared entry becomes its OWN group (in recipe
    order) rather than being merged by matcher across recipes — simpler, and matches how multiple
    plugins/installers each contribute independent groups for the same event in practice.
    """
    out: dict[str, list[dict]] = {}
    for recipe in recipes:
        for event, entries in recipe.hooks.items():
            group = out.setdefault(event, [])
            for entry in entries:
                block: dict = {"hooks": [{"type": "command", "command": entry.command}]}
                if entry.matcher is not None:
                    block["matcher"] = entry.matcher
                group.append(block)
    return out


# Stack `permissions:` → Claude Code settings.json `permissions.defaultMode` (bd main-c5g). Unset
# (or an unrecognized value) maps to the historical harnessed baseline `acceptEdits` so nothing
# regresses; the three authored modes map explicitly.
_PERMISSION_DEFAULT_MODE = {
    "prompt": "default",
    "auto": "acceptEdits",
    "yolo": "bypassPermissions",
}


def _permission_default_mode(permissions: str | None) -> str:
    """Map a stack's `permissions:` value to a Claude `permissions.defaultMode` (bd main-c5g).

    None (unset) → `acceptEdits`, preserving the prior always-auto-accept behaviour in a disposable
    container. prompt→default, auto→acceptEdits, yolo→bypassPermissions. An unrecognized value falls
    back to `acceptEdits` rather than emitting an invalid mode.
    """
    if permissions is None:
        return "acceptEdits"
    return _PERMISSION_DEFAULT_MODE.get(permissions, "acceptEdits")


def required_settings(
    servers: list[McpServer],
    recipes: list[Recipe] | None = None,
    permissions: str | None = None,
) -> dict:
    """harnessed's REQUIRED settings.json contribution — the *only* thing the harness must add on
    top of whatever a recipe/base installer baked.

    Contributions:
      - `permissions.defaultMode` — ALWAYS present, derived from the stack's `permissions:` via
        `_permission_default_mode` (default `acceptEdits` when unset). Every isolated container is
        disposable, so per-edit approval prompts add friction without protection; a stack may widen
        (`yolo`) or narrow (`prompt`) this. A recipe/base that baked its own defaultMode keeps it
        (this is a floor, not an override — see `merge_settings`).
      - the hatago hub permission grant, only when the stack actually has servers (no servers →
        hatago exposes nothing → no grant needed). The server-level wildcard `mcp__<hub>` allows
        every tool hatago exposes; the hub's child tool names are only known at runtime, so the
        hub-level grant is the static, assembler-knowable permission.
      - each recipe's declared `hooks:` (GAP 2), rendered by `_recipe_hooks_settings`.
    This is the single source of truth for "what the harness requires" — both the assemble-time
    floor (`write_settings_json`) and the post-build merge (`merge_settings`, via the launcher)
    use it.
    """
    out: dict = {}
    perms: dict = {"defaultMode": _permission_default_mode(permissions)}
    if servers:
        perms["allow"] = [f"mcp__{HATAGO_MCP_KEY}"]
    out["permissions"] = perms
    hooks = _recipe_hooks_settings(recipes or [])
    if hooks:
        out["hooks"] = hooks
    return out


def write_settings_json(
    profile_dir: Path,
    servers: list[McpServer],
    recipes: list[Recipe] | None = None,
    permissions: str | None = None,
) -> Path:
    """Emit the assemble-time `settings.json` FLOOR — pre-approve the hatago hub's MCP tools and
    declare any recipe-contributed hooks (GAP 2).

    Without the MCP grant, an interactive isolated session prompts for permission the first time
    it uses an MCP tool, so a skill that drives (e.g.) the time server appears to "fail".

    This runs at ASSEMBLE time, *before* the image exists, so it cannot yet include a recipe/base
    installer's own `settings.json` (extra hooks/permissions baked by a Dockerfile RUN step). The
    launcher replaces this floor post-build via `merge_settings()` once the image artifact exists;
    if no recipe/base baked a `settings.json`, this floor stands unchanged.
    """
    out = profile_dir / "settings.json"
    _write_json(out, required_settings(servers, recipes, permissions))
    return out


def read_baked_settings(text: str | None, *, warn=None) -> dict | None:
    """Parse an image-baked `settings.json`'s raw text into a dict for `merge_settings()`.

    Distinguishes the two "no usable baked file" cases the launcher must NOT conflate:
      - text is None         → the file was absent or `podman cp` failed. Return None silently;
                               the caller keeps the assemble-time floor unchanged.
      - text is malformed    → a recipe installer wrote broken JSON. Return None and WARN, rather
                               than crashing `harnessed build` over a recipe's bad file.
    A valid JSON object returns the parsed dict. A valid-but-non-object (list/number/string) is
    treated as malformed — `settings.json` must be a JSON object.
    """
    if text is None:
        return None
    _warn = warn or (lambda _m: None)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _warn("image settings.json is not valid JSON — keeping harnessed's default")
        return None
    if not isinstance(data, dict):
        _warn("image settings.json is not a JSON object — keeping harnessed's default")
        return None
    return data


def merge_settings(baked: dict | None, required: dict, *, warn=None) -> dict:
    """Resolve the FINAL settings.json = the image's installer-written file with harnessed's
    required contributions surgically re-applied. This is NOT a generic deep-merge.

        baked (authoritative, post-install)        required (harnessed's sole additions)
        ───────────────────────────────────        ─────────────────────────────────────
        { hooks, permissions, … }                  { permissions: { allow: [mcp__hatago] },
                                                      hooks: { SessionStart: [...] } }
                       └──────────────┬─────────────────────────┘
                                      ▼
        result = baked, then:
          • required.permissions.defaultMode → applied ONLY if baked has no defaultMode (floor, not
            override — a recipe/base that set its own mode keeps it).
          • for each grant in required.permissions.allow:
              - ensure grant ∈ permissions.allow   (union, dedup, order-preserving)
              - drop  grant ∈ permissions.deny     (REQUIRED WINS — hatago is the only MCP path; a
                                                     recipe that denies it would break every tool)
          • for each event in required.hooks: APPEND its entries onto baked.hooks[event] (union,
            never overwrite — a recipe/base installer may have already contributed its own groups
            for the same event, e.g. bd's own `bd setup claude` writing SessionStart separately).
        Every OTHER baked key is carried through VERBATIM. Only `permissions.allow` and `hooks[*]`
        are unioned — a generic nested merge would corrupt other array-valued keys such as
        `permissions.deny`.

    `baked is None` (no image file / cp failed) → return `required` unchanged (the floor stub).
    """
    if baked is None:
        return required
    _warn = warn or (lambda _m: None)
    result = deepcopy(baked)

    req_mode = required.get("permissions", {}).get("defaultMode")
    if req_mode is not None:
        # Floor, not override (unlike the hatago grant below): a settings.json that a recipe/base
        # explicitly baked with its own defaultMode keeps it; otherwise harnessed's baseline applies.
        result.setdefault("permissions", {}).setdefault("defaultMode", req_mode)

    grants = required.get("permissions", {}).get("allow", [])
    if grants:
        perms = result.setdefault("permissions", {})
        allow = perms.get("allow")
        if not isinstance(allow, list):
            allow = []
            perms["allow"] = allow
        deny = perms.get("deny")
        for grant in grants:
            if isinstance(deny, list) and grant in deny:
                deny[:] = [d for d in deny if d != grant]
                _warn(f"image settings.json denies {grant}; harnessed re-enables it "
                      "(required for the MCP hub)")
            if grant not in allow:
                allow.append(grant)

    required_hooks = required.get("hooks") or {}
    if required_hooks:
        hooks = result.setdefault("hooks", {})
        for event, entries in required_hooks.items():
            existing = hooks.get(event)
            if not isinstance(existing, list):
                existing = []
            hooks[event] = existing + list(entries)

    return result


def _hatago_entry(server: McpServer, project_path: str | Path | None = None) -> dict:
    """Map an MCP server to a hatago `mcpServers` entry (schema per hatago docs).

    When `url_env` is set, the URL is emitted as `${VAR_NAME}` so the profile file contains no
    secret value. The env var reaches the container at launch time (via --env-file) and hatago
    substitutes it at runtime. `url_env` takes precedence over `url` when both are set.

    `project_path` (bd main-u5d): when set, a stdio child's `cwd` is pinned to the mirrored
    container-side project path (`paths.container_project_path`). hatago otherwise spawns stdio
    children with cwd = the container home, so a child that resolves its target from cwd (serena
    `--project-from-cwd`, repowise's default) would index the wrong directory. Only known at LAUNCH
    (path mirroring makes it per-project), so the assemble-time committed config passes None.
    """
    if server.is_stdio_child:
        entry: dict = {"command": server.command, "args": list(server.args)}
        if server.env:
            entry["env"] = dict(server.env)
        if project_path is not None:
            entry["cwd"] = str(paths.container_project_path(project_path))
        return entry
    # Network-native server: hatago proxies it by URL (transport http/sse).
    # url_env → emit placeholder; resolved at runtime from the container's env (never on disk).
    url = f"${{{server.url_env}}}" if server.url_env else server.url
    entry = {"url": url, "type": server.transport}
    if server.headers:
        entry["headers"] = dict(server.headers)
    return entry


def write_hatago_config(
    profile_dir: Path, servers: list[McpServer], project_path: str | Path | None = None
) -> Path:
    """Emit hatago.config.json declaring each server as a hatago child/proxy.

    `project_path` (bd main-u5d) pins each stdio child's `cwd` to the mirrored project path — see
    `_hatago_entry`. The assemble-time (committed) config is project-agnostic and passes None; the
    launcher regenerates a per-instance config with the real project path at launch time.
    """
    out = profile_dir / "hatago.config.json"
    _write_json(
        out,
        {
            "version": 1,
            "logLevel": "info",
            "mcpServers": {s.name: _hatago_entry(s, project_path) for s in servers},
        },
    )
    return out


def write_derived_dockerfile(
    profile_dir: Path, stack: Stack, recipes: list[Recipe], *, with_scan: bool = True
) -> Path:
    """Emit profiles/<stack>/Dockerfile.harnessed-<stack> for host `podman build` (ASM-03).

    The output Dockerfile:
    - Declares ARG HARNESS=<stack.harness> before FROM (so the build arg flows from the host
      podman build invocation via --build-arg HARNESS=...).
    - Uses FROM harnessed-${HARNESS}:latest (the parameterised base).
    - Re-declares ARG HARNESS after FROM so RUN instructions in recipe layers can reference
      ${HARNESS} (per RESEARCH Pitfall 1: ARG is scoped to the build stage it is declared in).
    - Concatenates each recipe's Dockerfile body with FROM and ARG HARNESS lines stripped
      (per RESEARCH Pitfall 2: recipe Dockerfiles must not re-declare FROM or reset HARNESS).
    """
    lines: list[str] = [
        f"# Generated by harnessed assembler for stack '{stack.name}'",
        "# DO NOT EDIT — regenerated by `harnessed build " + stack.name + "`",
        f"ARG HARNESS={stack.harness}",
        f"FROM harnessed-${{HARNESS}}:latest",
        "ARG HARNESS",  # re-declare in post-FROM stage so RUN instructions see it
        "",
    ]
    for recipe in recipes:
        dockerfile = recipe.root / "Dockerfile"
        if not dockerfile.is_file():
            continue  # backward-compat: recipes without Dockerfiles contribute no layer
        body_lines = dockerfile.read_text(encoding="utf-8").splitlines()
        filtered = [
            ln for ln in body_lines
            if not ln.strip().upper().startswith("FROM ")
            and not _ARG_HARNESS_RE.match(ln.strip())
        ]
        lines.append(f"# --- recipe: {recipe.name} ---")
        lines.extend(filtered)
        lines.append("")

    if stack.hatago:
        # Override the base image's pinned hatago release (catalog/base/Dockerfile.harnessed-base)
        # with a stack-specified repo/ref.
        #
        # NEITHER of the two existing install conventions applies here:
        #  - mise's `github:` backend (used by rtk/beads/dolt) resolves GitHub *Release* assets —
        #    there is no release for an unmerged feature branch.
        #  - A plain `pnpm add -g github:<owner>/<repo>#<ref>` git-spec install fails outright:
        #    hatago-mcp-hub is a pnpm workspace monorepo whose ROOT package.json has no `name`
        #    field (ERR_PNPM_MISSING_PACKAGE_NAME) — the publishable package lives at
        #    packages/mcp-hub, and its build (tsdown) needs its workspace:* sibling packages
        #    resolved, which a bare git-spec install can't do.
        # So: shallow-clone the ref, install ONLY the target package + its workspace:* deps (`pnpm
        # install --filter <pkg>...` — excludes the repo's examples/apps workspace members), build
        # the target package, then pnpm-link that built directory in globally.
        #
        # pnpm v11 (pinned in the base image) denies dependency postinstall/build scripts by
        # default (ERR_PNPM_IGNORED_BUILDS) unless explicitly reviewed via pnpm-workspace.yaml's
        # `allowBuilds` map — and it evaluates this against the WHOLE workspace lockfile, not just
        # the --filter-ed subset. tsdown (the target package's build tool) needs esbuild's
        # postinstall to fetch its platform binary, so approve it. sharp/workerd belong to the
        # repo's examples/apps members (unrelated to what we're building) — decline them explicitly
        # rather than leave them "unreviewed" (which errors) or loosen the strict-builds gate.
        owner_repo = stack.hatago["repo"].removeprefix("github:")
        ref = stack.hatago.get("ref")
        branch_flag = f' --branch "{ref}"' if ref else ""
        allow_builds = "allowBuilds:\\n  esbuild: true\\n  sharp: false\\n  workerd: false\\n"
        lines += [
            f"# --- stack override: hatago MCP hub ({stack.name} stack.yaml `hatago:`) ---",
            "RUN git clone --depth 1" + branch_flag + f' "https://github.com/{owner_repo}.git" /tmp/hatago-src \\',
            "    && cd /tmp/hatago-src \\",
            f"    && printf '{allow_builds}' >> pnpm-workspace.yaml \\",
            # NOT --no-frozen-lockfile: the clone ships its own pnpm-lock.yaml for this exact
            # commit, already in sync with its package.json files. Forcing a re-resolve let pnpm
            # pick different transitive tsdown/rolldown/esbuild versions per package than upstream
            # tested with — surfaced as a rolldown "Invalid input options" warning and a missing
            # generated .d.ts that broke a sibling package's `tsc` build.
            '    && pnpm install --filter "@himorishige/hatago-mcp-hub..." \\',
            # The trailing `...` here (unlike the install filter's own `...`, kept for clarity) is
            # load-bearing: mcp-hub's devDependencies are its workspace:* siblings (hatago-core,
            # -hub, -runtime, -server, -transport), each with its OWN `build` script producing the
            # dist/ that mcp-hub's tsdown build resolves them against. Building mcp-hub alone left
            # those imports unresolved (rollup silently treats them as external) — a CLI that
            # crashes at runtime since the siblings are devDependencies, never installed downstream.
            '    && pnpm --filter "@himorishige/hatago-mcp-hub..." run build \\',
            "    && pnpm add -g file:/tmp/hatago-src/packages/mcp-hub \\",
            "    && cd / && rm -rf /tmp/hatago-src",
            "",
        ]

    if with_scan:
        # Final layer: in-image supply-chain scan (BLD-02), ADVISORY — it reports a severity summary
        # and writes a report but never fails the build (harnessed installs third-party tooling whose
        # dep trees always carry open advisories; a hard gate would block every build). Scans what the
        # build installed (mise globals + recipe trees under ~/.claude). SNYK_TOKEN arrives as a build
        # secret (never a build-arg → never baked); required=false so a tokenless build still proceeds
        # (snyk warn-skips). Disabled entirely by `harnessed build --no-security-scans`.
        lines += [
            "# --- supply-chain scan (BLD-02) ---",
            "RUN --mount=type=secret,id=snyk_token,required=false,mode=0444 harnessed-scan",
            "",
        ]

    out = profile_dir / f"Dockerfile.harnessed-{stack.name}"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


