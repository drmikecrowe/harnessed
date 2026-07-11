"""Parse + validate recipe.yaml / stack.yaml into typed objects.

EMIT-ONLY assembler component: this module only reads files and builds in-memory
objects. It never invokes podman/docker and never writes anything.

Parsing is tolerant of unknown fields (design D-14): only the fields the tracer
bullet exercises are required; everything else is preserved on `.raw` and parsed
forward so future recipes can add `plugins`, `deps`, `hooks`, etc. without a schema
change here.

This module is also the test oracle for the per-stack capability test (plan 02-03),
which imports `load_stack_with_recipes` + `expected_capabilities` to derive what the
running instance must expose. Keep the parse API clean and reusable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from . import paths

_yaml = YAML(typ="safe", pure=True)


def _resolve_dir(root: Path | None, kind: str, name: str) -> Path:
    """Resolve catalog/<kind>/<name>.

    `root` given → search only that single root (root/<kind>/<name>) — explicit, used by tests with
    fixture trees. `root` None → resolve across the catalog roots (user overlay first), the
    production path.
    """
    if root is None:
        return paths.find_in_catalog(kind, name)
    return Path(root) / kind / name

# Harness → config directory name (Claude Code canonical, design §8). One harness per stack.
# All harnesses consume the SAME committed Claude-canonical profile (.claude/) — single source of
# truth (plan 04-03 / HRN-01..HRN-04). They differ only in HOW they read it + reach hatago:
#   - claude   — native (.mcp.json + skills/commands/agents).
#   - omp      — Claude hooks/skills via the pre-installed claude-hooks-bridge.
#   - opencode — reads .claude/skills/**/SKILL.md + ~/.claude/CLAUDE.md natively; MCP via the
#                image-baked ~/.config/opencode config (it ignores .mcp.json).
#   - antigravity (agy) — MCP via the image-baked ~/.gemini/config/mcp_config.json (serverUrl →
#                hatago); Claude skills/commands are NOT natively consumed. Google's harness —
#                supersedes the standalone gemini-cli harness (removed).
#   - codex    — MCP via the image-baked ~/.codex/config.toml ([mcp_servers.hatago] url → hatago,
#                native streamable-HTTP); reads AGENTS.md but NOT Claude skills/commands.
# No separate profile dir, no re-authoring for any harness.
HARNESS_CONFIG_DIR = {
    "claude": ".claude",
    "omp": ".claude",
    "opencode": ".claude",
    "antigravity": ".claude",
    "codex": ".claude",
}


class SchemaError(Exception):
    """A recipe/stack manifest is missing a required field or is malformed."""


class RecipeLintError(SchemaError):
    """A recipe uses raw npm/npx instead of the pnpm equivalent (BLD-03 supply-chain lint)."""


class PinValidationError(SchemaError):
    """A recipe Dockerfile contains a floating ref (--branch main/master, :latest, @latest)."""


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = _yaml.load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: expected a YAML mapping at the top level")
    return data


@dataclass
class McpServer:
    """One MCP server declared by a recipe (design §11 MCP layer).

    `transport` is explicit (RESEARCH Pitfall B). A `stdio` server (with `command`)
    is run by hatago as a child (stdio→HTTP) and must be baked into the hatago image;
    a network-native server (`url`, transport http/sse) is proxied by hatago by URL.
    """

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    transport: str = "stdio"
    url: str | None = None
    service: str | None = None
    url_env: str | None = None
    env: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def is_stdio_child(self) -> bool:
        """A stdio server hatago must bake + spawn (vs a network-native URL proxy)."""
        return self.transport == "stdio" and self.command is not None


@dataclass
class FileExt:
    """A standalone file-extension dir shipped by a recipe (skills/ or commands/)."""

    path: str  # relative to the recipe dir

    @property
    def name(self) -> str:
        # Harness-native target name = the leaf dir name (e.g. skills/time-helper → time-helper).
        return Path(self.path).name


@dataclass
class Expect:
    """What a recipe tells the capability test to probe after building (design point 3).

    A recipe that delivers capabilities via its Dockerfile (which the assembler cannot see by
    parsing skills:/commands:/mcp:) declares them here so the oracle knows what to look for and of
    which KIND. Each kind is checked in the right place in the running container:
    skills → ~/.claude/skills/<name>, commands → ~/.claude/commands/<name>,
    plugins → ~/.claude/plugins/<name>, mcp → connected through the hatago hub.
    """

    skills: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)


def _parse_expect(raw_expect) -> Expect:
    """Parse the `expect:` block (a mapping of kind → [names]). Absent → an empty Expect."""
    if not raw_expect:
        return Expect()
    if not isinstance(raw_expect, dict):
        raise SchemaError(
            "recipe 'expect' must be a mapping of kind → names "
            "(e.g. expect: {skills: [gstack-skill], commands: [gstack-cmd]})"
        )
    return Expect(
        skills=list(raw_expect.get("skills") or []),
        commands=list(raw_expect.get("commands") or []),
        plugins=list(raw_expect.get("plugins") or []),
        mcp=list(raw_expect.get("mcp") or []),
    )


# Per-component charset for persist entry names. Each slash-separated component must match
# this (no '..', no empty component). '.' is allowed as a leading char (e.g. '.beads') but not
# alone (rejected explicitly during validation). Valid across all scopes.
_PERSIST_NAME_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# A stack `ssh_keys` entry is a single private-key basename under ~/.ssh (e.g. `id_ed25519`). Same
# one-path-component charset as persist names so a stack can never name `../foo` or an absolute path
# and escape ~/.ssh; '.'/'..' pass the charset but are navigation, rejected explicitly at parse.
_SSH_KEY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# A stack `hatago.repo` is `github:<owner>/<repo>` and `hatago.ref` is a branch/tag/SHA — both are
# interpolated into a generated Dockerfile `RUN` line (emit.write_derived_dockerfile), so the
# charset is restricted to what a git ref / GitHub path segment can legally contain — no shell
# metacharacters, no quotes, no whitespace.
_HATAGO_REPO_RE = re.compile(r"^github:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_HATAGO_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

_PERSIST_VALID_SCOPES = {"workspace", "project", "global"}
_PERSIST_RESERVED_SCOPES = {"repo"}
_PERSIST_VALID_LOCATIONS = {"host", "in_repo"}
_PERSIST_RESERVED_LOCATIONS = {"external"}
_PERSIST_VALID_VCS = {"tracked", "ignored"}


@dataclass
class PersistEntry:
    """One recipe persist entry — a single (scope, location, name/path, vcs) combination.

    Axes:
      scope    — what identity key is used (workspace|project|global).
      location — where the bytes live (host|in_repo; omitted for scope: global).
      name     — $HOME-relative path the tool writes to inside the container (scope: workspace|project).
      path     — real host path to bind-mount as-is (scope: global only).
      vcs      — git tracking intent (tracked|ignored; required for location: in_repo only).
    """

    scope: str
    location: str | None
    name: str | None
    path: str | None
    vcs: str | None


@dataclass
class PersistSpec:
    """All persist entries declared by a recipe.

    Scope is ALWAYS explicit — never inferred from the name shape. Three scopes:
      workspace — keyed by the resolved current launch path (per-worktree/per-branch).
      project   — keyed by git-common-dir (shared across all worktrees of one checkout;
                  falls back to workspace scope with a warning when not in a git repo).
      global    — a real, allowlisted host dir shared with host-native tool runs (T4b).

    Two locations (not applicable to scope: global):
      host    — harnessed owns a dir under $XDG_DATA_HOME/harnessed/persist/ and mounts it rw.
      in_repo — the folder lives inside the already-mounted project workspace (no extra mount).
    """

    entries: list[PersistEntry] = field(default_factory=list)


def _validate_persist_name(name: str, location: str, entry_idx: int) -> None:
    """Validate a persist entry name: no absolute paths, no '..', correct nesting for scope."""
    if not name or not isinstance(name, str):
        raise SchemaError(f"persist entry [{entry_idx}]: 'name' must be a non-empty string")
    if name.startswith("/"):
        raise SchemaError(
            f"persist entry [{entry_idx}]: 'name' must not be an absolute path: {name!r}"
        )
    if name.startswith("~"):
        raise SchemaError(
            f"persist entry [{entry_idx}]: 'name' must not start with '~': {name!r} — "
            "use 'path' with scope: global for real host paths"
        )
    parts = name.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise SchemaError(
                f"persist entry [{entry_idx}]: 'name' {name!r} contains invalid component "
                f"{part!r} — no empty segments, '.', or '..' allowed"
            )
        if not _PERSIST_NAME_COMPONENT_RE.match(part):
            raise SchemaError(
                f"persist entry [{entry_idx}]: 'name' component {part!r} (in {name!r}) "
                "must match [A-Za-z0-9._-]"
            )
    if location == "host" and "/" in name:
        raise SchemaError(
            f"persist entry [{entry_idx}]: 'name' {name!r} for location: host must be a single "
            "path component with no slashes — it maps directly to $HOME/<name> inside the "
            "container (e.g. '.beads', not '.beads/sub')"
        )


def _parse_persist(raw_persist) -> PersistSpec:
    """Parse the `persist:` block: a list of {scope, location, name/path, vcs} entries."""
    if not raw_persist:
        return PersistSpec()

    # Detect old format (dict with project/global keys) and give a clear migration hint.
    if isinstance(raw_persist, dict):
        if set(raw_persist) & {"project", "global"}:
            raise SchemaError(
                "recipe 'persist' format has changed: it is now a list of entries, each with "
                "explicit 'scope', 'location', and 'name'/'path' fields.\n"
                "Old format (no longer valid):\n"
                "  persist: {project: [.foo], global: [~/.bar]}\n"
                "New format:\n"
                "  persist:\n"
                "    - name: .foo\n"
                "      scope: workspace\n"
                "      location: host\n"
                "    - path: ~/.bar\n"
                "      scope: global\n"
                "See docs/guides/recipe-authoring.md for the full persist schema."
            )
        raise SchemaError(
            "recipe 'persist' must be a list of entries, not a mapping. "
            "See docs/guides/recipe-authoring.md for the persist schema."
        )

    if not isinstance(raw_persist, list):
        raise SchemaError(
            "recipe 'persist' must be a list of entries — "
            "see docs/guides/recipe-authoring.md for the persist schema."
        )

    entries: list[PersistEntry] = []
    for i, raw in enumerate(raw_persist):
        if not isinstance(raw, dict):
            raise SchemaError(
                f"persist entry [{i}] must be a mapping, got {type(raw).__name__!r}"
            )

        scope = raw.get("scope")
        if scope is None:
            raise SchemaError(
                f"persist entry [{i}]: missing required field 'scope' "
                "(workspace | project | global)"
            )
        if scope in _PERSIST_RESERVED_SCOPES:
            raise SchemaError(
                f"persist entry [{i}]: scope: {scope!r} is reserved for a future release "
                "and not yet implemented"
            )
        if scope not in _PERSIST_VALID_SCOPES:
            raise SchemaError(
                f"persist entry [{i}]: unknown scope {scope!r} — "
                f"valid values: {', '.join(sorted(_PERSIST_VALID_SCOPES))}"
            )

        location = raw.get("location")
        name = raw.get("name")
        path = raw.get("path")
        vcs = raw.get("vcs")

        unknown = sorted(set(raw) - {"scope", "location", "name", "path", "vcs"})
        if unknown:
            raise SchemaError(
                f"persist entry [{i}]: unknown field(s) {unknown} — "
                "valid fields: scope, location, name, path, vcs"
            )

        if scope == "global":
            if location is not None:
                raise SchemaError(
                    f"persist entry [{i}]: 'location' is not valid for scope: global "
                    "(global entries bind-mount the real host path as-is)"
                )
            if vcs is not None:
                raise SchemaError(
                    f"persist entry [{i}]: 'vcs' is not valid for scope: global"
                )
            if name is not None:
                raise SchemaError(
                    f"persist entry [{i}]: use 'path' (not 'name') for scope: global — "
                    "a real host path is required (e.g. path: ~/.gbrain)"
                )
            if not path or not isinstance(path, str) or not path.strip():
                raise SchemaError(
                    f"persist entry [{i}]: scope: global requires a non-empty 'path' field "
                    "(e.g. path: ~/.gbrain)"
                )
            entries.append(PersistEntry(scope=scope, location=None, name=None, path=path, vcs=None))

        else:
            # workspace or project
            if path is not None:
                raise SchemaError(
                    f"persist entry [{i}]: use 'name' (not 'path') for scope: {scope!r} — "
                    "'path' is only for scope: global"
                )
            if location is None:
                raise SchemaError(
                    f"persist entry [{i}]: scope: {scope!r} requires an explicit 'location' "
                    "field (host | in_repo)"
                )
            if location in _PERSIST_RESERVED_LOCATIONS:
                raise SchemaError(
                    f"persist entry [{i}]: location: {location!r} is reserved for a future "
                    "release and not yet implemented"
                )
            if location not in _PERSIST_VALID_LOCATIONS:
                raise SchemaError(
                    f"persist entry [{i}]: unknown location {location!r} — "
                    f"valid values: {', '.join(sorted(_PERSIST_VALID_LOCATIONS))}"
                )
            if name is None:
                raise SchemaError(
                    f"persist entry [{i}]: scope: {scope!r} requires a 'name' field "
                    "(a $HOME-relative path, e.g. .beads)"
                )
            _validate_persist_name(name, location, i)

            if location == "in_repo":
                if vcs is None:
                    raise SchemaError(
                        f"persist entry [{i}]: location: in_repo requires a 'vcs' field "
                        "(tracked | ignored)"
                    )
                if vcs not in _PERSIST_VALID_VCS:
                    raise SchemaError(
                        f"persist entry [{i}]: unknown vcs {vcs!r} — "
                        "valid values: tracked, ignored"
                    )
            else:
                if vcs is not None:
                    raise SchemaError(
                        f"persist entry [{i}]: 'vcs' is only valid for location: in_repo "
                        f"(got location: {location!r})"
                    )

            entries.append(
                PersistEntry(scope=scope, location=location, name=name, path=None, vcs=vcs)
            )

    return PersistSpec(entries=entries)


@dataclass
class InitSpec:
    """One-time init spec for a recipe: a shell command sourced in the attach shell (Model A).

    `run` is executed inline in the SAME shell process that then starts the harness, so any env it
    exports (e.g. beads' BEADS_DIR) flows straight into the agent — no profile.d, no transient
    container. Because init now runs on EVERY attach (re-attach, second terminal), `run` must
    self-gate cheaply and be idempotent: the old declarative host-side `marker:` is gone, and
    self-gating in the command is the convention that replaces it. A non-zero `run` aborts the
    attach with a clear error — the harness never starts on a half-initialized tool.
    """

    run: str


def _parse_init(raw_init) -> "InitSpec | None":
    """Parse the `init:` block: just the `run` command (Model A — no host-side marker)."""
    if not raw_init:
        return None
    if not isinstance(raw_init, dict):
        raise SchemaError("recipe 'init' must be a mapping with a 'run' field")

    run = raw_init.get("run")
    if not run or not isinstance(run, str) or not run.strip():
        raise SchemaError("recipe 'init': 'run' is required and must be a non-empty string")

    unknown = sorted(set(raw_init) - {"run"})
    if unknown:
        raise SchemaError(
            f"recipe 'init': unknown field(s) {unknown} — the only valid field is 'run'. "
            "The host-side 'marker' was removed (Model A): init runs in the attach shell on every "
            "launch, so the run command must self-gate (e.g. `bd list >/dev/null 2>&1 || bd init`)."
        )

    return InitSpec(run=run.strip())


@dataclass
class HookCommand:
    """One command hook entry under a single event (recipe.yaml `hooks:` — GAP 2).

    Maps directly to Claude Code's own settings.json hook shape: `matcher` is optional (ignored
    by events that don't support tool-matching, e.g. Stop/UserPromptSubmit; used to filter by
    tool name for PreToolUse/PostToolUse, or by source for SessionStart: "startup"|"resume"|"clear").
    `command` is a shell command string, run by Claude Code's OWN hook runner inside the instance —
    it must already exist in the image (baked by the recipe's Dockerfile). No launcher-side
    execution wiring is needed; this is NOT the host-side `init:`/old startup-hooks mechanism.
    """

    command: str
    matcher: str | None = None


# Claude Code's documented hook event names (code.claude.com/docs/en/hooks). Validated so a typo
# (e.g. `SessionStarts`) fails at parse time instead of silently installing a dead hook.
_VALID_HOOK_EVENTS = frozenset({
    "SessionStart", "Setup", "SessionEnd",
    "UserPromptSubmit", "UserPromptExpansion", "Stop", "StopFailure",
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "PermissionRequest", "PermissionDenied",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "TeammateIdle",
    "ConfigChange", "CwdChanged", "FileChanged", "InstructionsLoaded",
    "WorktreeCreate", "WorktreeRemove",
    "PreCompact", "PostCompact", "MessageDisplay", "Notification",
    "Elicitation", "ElicitationResult",
})


def _parse_hooks(raw_hooks) -> dict[str, list[HookCommand]]:
    """Parse the `hooks:` block: {EventName: [{command, matcher?}, ...]} (GAP 2).

    Declarative — a recipe states exactly what belongs in settings.json's `hooks` object; the
    assembler (emit.py) renders it into Claude Code's native shape. Distinct from `init:` (which
    runs a command host-side, once, before the agent ever attaches): these commands run INSIDE
    Claude Code's own hook runner, every time the event fires, so a recipe needing "only once
    per project" behavior must gate that itself (e.g. check-and-touch a marker file in its script).
    """
    if not raw_hooks:
        return {}
    if not isinstance(raw_hooks, dict):
        raise SchemaError(
            "recipe 'hooks' must be a mapping of {EventName: [{command, matcher?}, ...]}"
        )

    parsed: dict[str, list[HookCommand]] = {}
    for event, entries in raw_hooks.items():
        if event not in _VALID_HOOK_EVENTS:
            raise SchemaError(
                f"recipe 'hooks': unknown event {event!r} — "
                f"valid events: {', '.join(sorted(_VALID_HOOK_EVENTS))}"
            )
        if not isinstance(entries, list) or not entries:
            raise SchemaError(f"recipe 'hooks.{event}' must be a non-empty list of hook entries")
        commands: list[HookCommand] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise SchemaError(f"recipe 'hooks.{event}' entries must be mappings, got {entry!r}")
            command = entry.get("command")
            if not command or not isinstance(command, str) or not command.strip():
                raise SchemaError(
                    f"recipe 'hooks.{event}' entry missing required non-empty 'command': {entry!r}"
                )
            matcher = entry.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                raise SchemaError(f"recipe 'hooks.{event}' entry 'matcher' must be a string: {entry!r}")
            unknown = sorted(set(entry) - {"command", "matcher"})
            if unknown:
                raise SchemaError(
                    f"recipe 'hooks.{event}' entry: unknown field(s) {unknown} — "
                    "valid fields: command, matcher"
                )
            commands.append(HookCommand(command=command.strip(), matcher=matcher))
        parsed[event] = commands
    return parsed


@dataclass
class SetupSpec:
    """Harness-agnostic manual-setup note (recipe.yaml `setup:`) — a short summary + upstream
    reference URL. USER-FACING: shown host-side by the launcher at attach time
    (launcher._prompt_setup_notices), NEVER baked into any agent identity/rules file. Deliberately
    not per-harness — one plain-English note, not a bespoke command.

    `condition` (optional): a shell command that exits 0 when the manual step is STILL needed
    (e.g. `! bd list`). Evaluated HOST-side in the project directory on every launch; exit 0 shows
    the notice, non-zero (satisfied) suppresses it. A recipe with no `condition` shows once per
    project until the user dismisses it (see paths.setup_dismissed_flag) — the dismiss flag gates
    only unconditional notices; conditional ones always follow their condition."""

    summary: str
    reference: str
    condition: str | None = None


def _parse_setup(raw_setup) -> "SetupSpec | None":
    """Parse the optional `setup:` object — omitted entirely when a recipe is self-contained."""
    if not raw_setup:
        return None
    if not isinstance(raw_setup, dict):
        raise SchemaError("recipe 'setup' must be an object with 'summary' and 'reference'")
    summary = raw_setup.get("summary")
    reference = raw_setup.get("reference")
    condition = raw_setup.get("condition")
    if not isinstance(summary, str) or not summary.strip():
        raise SchemaError("recipe 'setup.summary' must be a non-empty string")
    if not isinstance(reference, str) or not reference.strip():
        raise SchemaError("recipe 'setup.reference' must be a non-empty string")
    if condition is not None and (not isinstance(condition, str) or not condition.strip()):
        raise SchemaError("recipe 'setup.condition', if set, must be a non-empty string")
    unknown = sorted(set(raw_setup) - {"summary", "reference", "condition"})
    if unknown:
        raise SchemaError(
            f"recipe 'setup': unknown field(s) {unknown} — valid fields: summary, reference, condition"
        )
    return SetupSpec(
        summary=summary.strip(),
        reference=reference.strip(),
        condition=condition.strip() if condition else None,
    )


def _parse_conflicts(raw_conflicts) -> list[str]:
    """Parse the optional `conflicts:` list — recipe names this recipe must never be combined with."""
    if not raw_conflicts:
        return []
    if not isinstance(raw_conflicts, list):
        raise SchemaError("recipe 'conflicts' must be a list of recipe names")
    conflicts: list[str] = []
    for entry in raw_conflicts:
        if not isinstance(entry, str) or not entry.strip():
            raise SchemaError(f"recipe 'conflicts' entries must be non-empty strings, got {entry!r}")
        conflicts.append(entry.strip())
    return conflicts


@dataclass
class Recipe:
    name: str
    description: str = ""
    servers: list[McpServer] = field(default_factory=list)
    skills: list[FileExt] = field(default_factory=list)
    commands: list[FileExt] = field(default_factory=list)
    rules: list[FileExt] = field(default_factory=list)
    expect: Expect = field(default_factory=Expect)
    persist: PersistSpec = field(default_factory=PersistSpec)
    init: "InitSpec | None" = None
    # GAP 2: declarative Claude Code hooks, merged into settings.json by emit.py. {EventName: [...]}.
    hooks: dict[str, list[HookCommand]] = field(default_factory=dict)
    # Other recipe names this recipe must never be combined with in the same stack (e.g. two
    # recipes that both claim to be the agent's sole cross-session memory store). Checked
    # symmetrically across a stack's whole recipe list (see _check_recipe_conflicts) — declaring
    # it on either side is enough.
    conflicts: list[str] = field(default_factory=list)
    setup: "SetupSpec | None" = None
    root: Path = field(default_factory=Path)  # the recipe dir (for resolving relative paths)
    raw: dict = field(default_factory=dict)


# Authored `permissions:` values a stack.yaml may set — kept in sync with
# emit._PERMISSION_DEFAULT_MODE, the table that maps each to a Claude `permissions.defaultMode`.
_STACK_PERMISSIONS_MODES = frozenset({"prompt", "auto", "yolo"})


@dataclass
class Stack:
    name: str
    harness: str = "claude"
    recipes: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    permissions: str | None = None
    # Stack-level identity text emitted into the profile's `.claude/CLAUDE.md` at assemble time —
    # "what is this assembled agent". Distinct from recipe-level `rules:` (per-recipe RULE.md files
    # fanned into `.claude/rules/`). Claude-only for now (CLAUDE.md is Claude's memory file).
    instructions: str | None = None
    # Opt-in (default OFF): forward the SECRET-BEARING slice of the host's git push surface — the gh
    # oauth token (~/.config/gh/hosts.yml) and opt-in private SSH keys — plus ssh config/known_hosts/
    # pubkeys and non-secret gnupg files. OFF by default so a reusable token/private key is never
    # mounted unless the stack asks. NOTE: the SSH signing/auth agent socket (1Password/gpg) + ro git
    # identity config are forwarded automatically whenever the host agent is live, INDEPENDENT of this
    # flag (see _ssh_agent_auto_forward_args) — the agent gates each use behind a host approval/touch
    # and exposes no key material, so "1Password available → wired up" is the default.
    forward_git_credentials: bool = False
    # Private SSH key basenames (under ~/.ssh) the user opts into mounting read-only into the
    # container, for hosts WITHOUT an SSH agent (1Password/gpg). Public keys + config + known_hosts
    # are forwarded by default; private keys are NOT, unless named here. Validated to a single path
    # component (no `/`, no `..`) so a stack can never escape ~/.ssh — see _SSH_KEY_NAME_RE. SECURITY:
    # honored ONLY from the user-overlay catalog, never a shared repo-catalog stack (see the launcher)
    # — the key owner, not a third-party stack author, must consent to mounting a private key.
    ssh_keys: list[str] = field(default_factory=list)
    # Per-stack override for the hatago MCP hub install (default: the base image's pinned npm
    # release — catalog/base/Dockerfile.harnessed-base). {repo: "github:<owner>/<repo>", ref:
    # "<branch|tag|sha>"} — installed via pnpm's git-spec `github:<owner>/<repo>#<ref>` (NOT mise's
    # `github:` backend: that resolves GitHub Release assets, and an override is typically an
    # unreleased branch of what is otherwise an npm package). None → no override layer emitted.
    hatago: dict | None = None
    state: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def harness_config_dir(self) -> str:
        if self.harness not in HARNESS_CONFIG_DIR:
            raise SchemaError(
                f"stack '{self.name}': unsupported harness '{self.harness}' "
                f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
            )
        return HARNESS_CONFIG_DIR[self.harness]


@dataclass
class ServiceDef:
    """A shared service sidecar definition (design §3/§9, plan 04-01 SVC-01).

    A service is its OWN image/container/volume on a host-published port
    (reachable via `host.containers.internal:<port>`; or by DNS name over the `HARNESSED_NET`
    bridge on bridge-capable hosts), with a lifecycle independent of any instance. A recipe
    references it via `mcp.servers[].service`; the assembler resolves the service name →
    a hatago URL-proxy entry pointing at `http://host.containers.internal:<port>/mcp`
    (the `HARNESSED_NET` opt-in bridge form is `http://<name>:<port>/mcp`; plan 04-01 Task 4).
    """

    name: str
    image: str
    port: int
    volume: str = ""
    healthcheck: str = ""
    raw: dict = field(default_factory=dict)


_VALID_TRANSPORTS = frozenset({"stdio", "http", "sse"})


def _parse_servers(raw_mcp: dict) -> list[McpServer]:
    servers: list[McpServer] = []
    for entry in (raw_mcp or {}).get("servers", []) or []:
        if "name" not in entry:
            raise SchemaError(f"mcp server entry missing 'name': {entry!r}")
        transport = entry.get("transport", "stdio")
        if transport not in _VALID_TRANSPORTS:
            raise SchemaError(
                f"mcp server '{entry['name']}': invalid transport '{transport}' "
                f"(supported: {', '.join(sorted(_VALID_TRANSPORTS))}). "
                "Use 'http' for Streamable-HTTP servers (SSE is deprecated)."
            )
        if entry.get("service") and entry.get("command"):
            raise SchemaError(
                f"mcp server '{entry['name']}': 'service' and 'command' are mutually exclusive — "
                "a service-referenced server is a network proxy, not a child process."
            )
        servers.append(
            McpServer(
                name=entry["name"],
                command=entry.get("command"),
                args=list(entry.get("args", []) or []),
                transport=transport,
                url=entry.get("url"),
                service=entry.get("service"),
                url_env=entry.get("url_env"),
                env=dict(entry.get("env", {}) or {}),
                headers=dict(entry.get("headers", {}) or {}),
                raw=dict(entry),
            )
        )
    return servers


def _parse_fileext(raw_list) -> list[FileExt]:
    out: list[FileExt] = []
    for entry in raw_list or []:
        if isinstance(entry, str):
            out.append(FileExt(path=entry))
        elif isinstance(entry, dict) and "path" in entry:
            out.append(FileExt(path=entry["path"]))
        else:
            raise SchemaError(f"skill/command entry must be a path or {{path: ...}}: {entry!r}")
    return out


# Recipe fields the parser knows: the typed YAML keys PLUS the D-14 forward fields that
# `_recipe_raw_strings` reads off `.raw` (scripts/deps/plugins). `--strict` rejects anything
# else as a likely typo (e.g. `skkills:`). This is a known-field ALLOWLIST, not strict-everything:
# the D-14 forward fields stay legal so a recipe can still carry plugins/deps/scripts without a
# schema change here. A genuinely NEW forward field is added to this set (or built with --no-strict).
# `hooks` is now TYPED (GAP 2, `_parse_hooks`) — it stays in this set as a typed key, not a forward
# one; `_recipe_raw_strings` still scans its raw string values too (harmless double-duty, catches a
# stray floating ref inside a hook `command` string).
KNOWN_RECIPE_FIELDS = frozenset({
    "name", "description", "mcp", "skills", "commands", "rules", "expect", "persist", "init",  # typed
    "conflicts", "hooks", "setup",  # typed
    "plugins", "deps", "scripts",  # D-14 forward fields (see _recipe_raw_strings)
})


def _levenshtein(a: str, b: str) -> int:
    """Edit distance — only called on the rare strict-reject path to suggest the intended field."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _suggest_field(unknown: str) -> str | None:
    """The closest known field within edit distance 2 (so `skkills` → `skills`), else None."""
    best = min(KNOWN_RECIPE_FIELDS, key=lambda k: _levenshtein(unknown, k))
    return best if _levenshtein(unknown, best) <= 2 else None


def _validate_recipe_fields(raw: dict, manifest: Path) -> None:
    """Strict mode: reject unknown top-level recipe fields (catches typos like `skkills:`)."""
    unknown = sorted(set(raw) - KNOWN_RECIPE_FIELDS)
    if not unknown:
        return
    described = [
        f"{f!r}" + (f" (did you mean {s!r}?)" if (s := _suggest_field(f)) else "")
        for f in unknown
    ]
    raise SchemaError(
        f"{manifest}: unknown recipe field(s) in --strict mode: {', '.join(described)}. "
        f"Known fields: {', '.join(sorted(KNOWN_RECIPE_FIELDS))}. "
        "Fix the typo, or build with --no-strict if this is an intentional forward field."
    )


def load_recipe(recipe_dir: Path, *, strict: bool = False) -> Recipe:
    recipe_dir = Path(recipe_dir)
    manifest = recipe_dir / "recipe.yaml"
    if not manifest.is_file():
        raise SchemaError(f"recipe manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    if "name" not in raw:
        raise SchemaError(f"{manifest}: required field 'name' is missing")
    if strict:
        _validate_recipe_fields(raw, manifest)
    return Recipe(
        name=raw["name"],
        description=raw.get("description", ""),
        servers=_parse_servers(raw.get("mcp", {}) or {}),
        skills=_parse_fileext(raw.get("skills")),
        commands=_parse_fileext(raw.get("commands")),
        rules=_parse_fileext(raw.get("rules")),
        expect=_parse_expect(raw.get("expect")),
        persist=_parse_persist(raw.get("persist")),
        init=_parse_init(raw.get("init")),
        hooks=_parse_hooks(raw.get("hooks")),
        conflicts=_parse_conflicts(raw.get("conflicts")),
        setup=_parse_setup(raw.get("setup")),
        root=recipe_dir,
        raw=raw,
    )


def load_stack(stack_dir: Path) -> Stack:
    stack_dir = Path(stack_dir)
    manifest = stack_dir / "stack.yaml"
    if not manifest.is_file():
        raise SchemaError(f"stack manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    if "name" not in raw:
        raise SchemaError(f"{manifest}: required field 'name' is missing")
    harness = raw.get("harness", "claude")
    if harness not in HARNESS_CONFIG_DIR:
        raise SchemaError(
            f"{manifest}: unsupported harness '{harness}' "
            f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
    ssh_keys = _parse_ssh_keys(raw.get("ssh_keys"), manifest)
    hatago = _parse_hatago(raw.get("hatago"), manifest)
    permissions = raw.get("permissions")
    if permissions is not None and permissions not in _STACK_PERMISSIONS_MODES:
        raise SchemaError(
            f"{manifest}: unsupported permissions '{permissions}' "
            f"(supported: {', '.join(sorted(_STACK_PERMISSIONS_MODES))})"
        )
    return Stack(
        name=raw["name"],
        harness=harness,
        recipes=list(raw.get("recipes", []) or []),
        services=list(raw.get("services", []) or []),
        permissions=permissions,
        instructions=raw.get("instructions"),
        forward_git_credentials=bool(raw.get("forward_git_credentials", False)),
        ssh_keys=ssh_keys,
        hatago=hatago,
        state=dict(raw.get("state", {}) or {}),
        raw=raw,
    )


def _parse_hatago(raw_hatago, manifest: Path) -> dict | None:
    """Validate the stack `hatago:` override block — `{repo: "github:<owner>/<repo>", ref: "..."}`.

    Both values are later interpolated into a generated Dockerfile RUN line
    (emit.write_derived_dockerfile), so they're validated against a strict charset here rather than
    at emit time — a bad value must fail loudly at load, not produce a malformed/injectable RUN line.
    """
    if not raw_hatago:
        return None
    if not isinstance(raw_hatago, dict) or "repo" not in raw_hatago:
        raise SchemaError(
            f"{manifest}: 'hatago' must be a mapping with at least 'repo' "
            f"(e.g. hatago: {{repo: github:owner/repo, ref: some-branch}})"
        )
    repo = raw_hatago["repo"]
    if not isinstance(repo, str) or not _HATAGO_REPO_RE.match(repo):
        raise SchemaError(
            f"{manifest}: hatago.repo {repo!r} must look like 'github:<owner>/<repo>'"
        )
    ref = raw_hatago.get("ref")
    if ref is not None and (not isinstance(ref, str) or not _HATAGO_REF_RE.match(ref)):
        raise SchemaError(
            f"{manifest}: hatago.ref {ref!r} must be a valid git ref (branch/tag/SHA), "
            f"no shell metacharacters"
        )
    return {"repo": repo, "ref": ref}


def _parse_ssh_keys(raw_keys, manifest: Path) -> list[str]:
    """Validate the stack `ssh_keys:` list — private-key basenames under ~/.ssh, opt-in.

    Each entry must be a single path component (the `_SSH_KEY_NAME_RE` charset, never '.'/'..'), so a
    stack can only ever name a key that lives directly in ~/.ssh — it can't point at `../id_rsa`, an
    absolute path, or any host file outside ~/.ssh. A non-list or a bad entry fails loudly here rather
    than silently mounting nothing (these are credentials — a typo must not pass).
    """
    if not raw_keys:
        return []
    if not isinstance(raw_keys, list):
        raise SchemaError(
            f"{manifest}: 'ssh_keys' must be a list of private-key basenames under ~/.ssh "
            f"(e.g. ssh_keys: [id_ed25519]), got {type(raw_keys).__name__}"
        )
    keys: list[str] = []
    for entry in raw_keys:
        if not isinstance(entry, str) or entry in (".", "..") or not _SSH_KEY_NAME_RE.match(entry):
            raise SchemaError(
                f"{manifest}: ssh_keys entry {entry!r} is not a valid key name — use a bare "
                f"basename under ~/.ssh (letters, digits, '.', '_', '-'; no '/' or '..')"
            )
        keys.append(entry)
    return keys


def load_service(root: Path | None, name: str) -> ServiceDef:
    """Load services/<name>/service.yaml (mirrors load_recipe/load_stack).

    `root` given → single root; `root` None → resolve across catalog roots (user overlay first).
    Requires `name`, `image`, and `port`; defaults `volume` to `<name>-data`.
    """
    manifest = _resolve_dir(root, "services", name) / "service.yaml"
    if not manifest.is_file():
        raise SchemaError(f"service manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    for field_name in ("name", "image", "port"):
        if field_name not in raw:
            raise SchemaError(f"{manifest}: required field '{field_name}' is missing")
    port = int(raw["port"])
    if not (1 <= port <= 65535):
        raise SchemaError(f"{manifest}: 'port' must be 1–65535, got {port}")
    return ServiceDef(
        name=raw["name"],
        image=raw["image"],
        port=port,
        volume=raw.get("volume") or f"{name}-data",
        healthcheck=raw.get("healthcheck", ""),
        raw=raw,
    )


def load_stack_with_recipes(
    root: Path | None, stack_name: str, *, strict: bool = False
) -> tuple[Stack, list[Recipe]]:
    """Load a stack and every recipe it references.

    `root` given → resolve stacks/ and recipes/ under that single root (fixtures/tests). `root`
    None → resolve each across the catalog roots (user overlay first), so a stack in the user
    catalog can compose recipes shipped in the repo catalog. Reusable by the capability test.

    `strict` → validate each recipe's top-level fields against `KNOWN_RECIPE_FIELDS` (the
    authoring guardrail; `harnessed build`/`test` pass it, `--no-strict` opts out).
    """
    stack = load_stack(_resolve_dir(root, "stacks", stack_name))
    recipes = [load_recipe(_resolve_dir(root, "recipes", name), strict=strict) for name in stack.recipes]
    _check_recipe_conflicts(stack.name, recipes)
    return stack, recipes


def _check_recipe_conflicts(stack_name: str, recipes: list[Recipe]) -> None:
    """Fail loudly if two recipes in the same stack declare themselves incompatible.

    Checked symmetrically: a recipe only needs to list the other side in its own `conflicts:` —
    both recipes don't have to agree.
    """
    names = {r.name for r in recipes}
    for r in recipes:
        for other in r.conflicts:
            if other != r.name and other in names:
                raise SchemaError(
                    f"stack {stack_name!r} combines recipes {r.name!r} and {other!r}, which "
                    f"declare themselves incompatible (conflicts:) — remove one from the stack's "
                    f"recipes list."
                )


@dataclass
class Agent:
    """An AI harness definition (catalog/agents/<name>/agent.yaml) — NOT a recipe.

    Recipes compose ONTO an agent; the agent declares how its container image is built.
    """

    name: str
    harness: str
    image: str
    dockerfile: str = ""
    description: str = ""
    build_args: dict[str, str] = field(default_factory=dict)
    root: Path = field(default_factory=Path)
    raw: dict = field(default_factory=dict)


def load_agent(name: str, root: Path | None = None) -> Agent:
    """Load catalog/agents/<name>/agent.yaml (resolved across catalog roots when root is None)."""
    agent_dir = _resolve_dir(root, "agents", name)
    manifest = agent_dir / "agent.yaml"
    if not manifest.is_file():
        raise SchemaError(f"agent manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    for field_name in ("harness", "image"):
        if field_name not in raw:
            raise SchemaError(f"{manifest}: required field '{field_name}' is missing")
    raw_args = raw.get("build_args") or {}
    if not isinstance(raw_args, dict):
        raise SchemaError(f"{manifest}: 'build_args' must be a mapping of NAME: value")
    # podman --build-arg takes NAME=value strings; stringify scalars (e.g. an unquoted version).
    build_args = {str(k): str(v) for k, v in raw_args.items()}
    return Agent(
        name=name,
        harness=raw["harness"],
        image=raw["image"],
        dockerfile=raw.get("dockerfile", ""),
        description=raw.get("description", ""),
        build_args=build_args,
        root=agent_dir,
        raw=raw,
    )


# --- BLD-03: raw npm/npx recipe lint (RESEARCH Pattern 3 / Code §7) -----------------------------
# Word-boundaried COMMAND tokens only — a package named like `npmlog` must NOT match (Pitfall 4).
_RAW_NPM_RE = re.compile(r"\bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b")
# --- Model A: init.run is SOURCED — a bash `exit` kills the attach shell (main-liw) -----------------
# Matches a real `exit` *command* token (bounded by shell separators/whitespace), never a substring
# like `exit_code` or `foo_exit`. `exit` on its own line, `; exit`, `|| exit`, `(exit)`, etc. all hit.
_INIT_EXIT_RE = re.compile(r"(^|[;&|(){}\s])exit(\s|$|[;&|)])")
# --- ASM-02: floating Dockerfile ref gate (T-08-01) -----------------------------------------------
# Detects --branch main/master/HEAD, :latest Docker image tags, and @latest npm refs.
# `:latest` in URL path segments uses `/latest/` (no colon), so `:latest\b` matches only Docker
# image tags (e.g. `node:latest`) without false-positives on URL paths.
_FLOATING_REF_RE = re.compile(
    r'--branch\s+(main|master|HEAD)\b'
    r'|:latest\b'
    r'|@latest\b',
    re.IGNORECASE,
)
# Offending token → the pnpm equivalent the author must use (BLD-03 "points at the pnpm equivalent").
_NPM_TO_PNPM = {
    "npx": "pnpm dlx",
    "npm install": "pnpm install",
    "npm i": "pnpm install",
    "npm ci": "pnpm ci",
    "npm run": "pnpm run",
    "npm exec": "pnpm exec",
}


def _recipe_raw_strings(raw: dict) -> list[str]:
    """String values carried on recipe.raw's forward fields (D-14): scripts/deps/plugins/hooks."""
    out: list[str] = []
    for key in ("scripts", "deps", "plugins", "hooks"):
        node = raw.get(key)
        if isinstance(node, dict):
            out.extend(v for v in node.values() if isinstance(v, str))
        elif isinstance(node, list):
            for entry in node:
                if isinstance(entry, str):
                    out.append(entry)
                elif isinstance(entry, dict):
                    out.extend(v for v in entry.values() if isinstance(v, str))
    return out


def _vendored_package_json_scripts(recipe_root: Path) -> list[str]:
    """Script command strings from any vendored plugin package.json under the recipe dir."""
    scripts: list[str] = []
    for pkg_path in recipe_root.rglob("package.json"):
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for value in (data.get("scripts") or {}).values():
            if isinstance(value, str):
                scripts.append(value)
    return scripts


def validate_no_raw_npm(recipe: Recipe) -> None:
    """Reject recipes that reach for raw npm/npx; name the pnpm equivalent (BLD-03, fail-fast).

    Detection is word-boundaried COMMAND tokens, never loose substrings, so a package named like
    `npmlog` is NOT flagged. Called from assemble() before any file is emitted (the same fail-fast
    gate position as the server-name collision check).
    """
    # 1. Explicit MCP server command of npm/npx → fail with the pnpm dlx form (the most direct hit).
    for server in recipe.servers:
        if server.command in ("npm", "npx"):
            raise RecipeLintError(
                f"recipe '{recipe.name}': MCP server '{server.name}' uses raw '{server.command}'. "
                "Use the pnpm equivalent 'pnpm dlx' "
                "(e.g. command: pnpm, args: [dlx, <pkg>])."
            )

    # 2. Word-boundaried npm/npx anywhere in command+args, recipe scripts/deps, or vendored
    #    package.json scripts.
    haystack: list[str] = []
    for server in recipe.servers:
        haystack.append(server.command or "")
        haystack.extend(server.args)
    haystack.extend(_recipe_raw_strings(recipe.raw))
    haystack.extend(_vendored_package_json_scripts(recipe.root))
    match = _RAW_NPM_RE.search(" ".join(haystack))
    if match:
        token = match.group(0)
        equiv = _NPM_TO_PNPM.get(token, "pnpm")
        raise RecipeLintError(
            f"recipe '{recipe.name}': raw npm/npx token '{token}' detected in a command/script. "
            f"Replace it with the pnpm equivalent '{equiv}'."
        )


def validate_pin(recipe_name: str, dockerfile_body: str) -> None:
    """Raises PinValidationError if the Dockerfile body contains a floating ref (ASM-02).

    Checks for --branch main/master/HEAD, :latest (not in URL paths), and @latest.
    Called from assemble() before any file is emitted (T-08-01 mitigation).
    Comment lines (# ...) are excluded so a comment that explains the :latest convention
    does not self-trigger the gate.
    """
    stripped = "\n".join(
        line for line in dockerfile_body.splitlines() if not line.lstrip().startswith("#")
    )
    match = _FLOATING_REF_RE.search(stripped)
    if match:
        raise PinValidationError(
            f"recipe '{recipe_name}': Dockerfile contains a floating ref '{match.group(0).strip()}'. "
            "Pin to a tag (e.g. v1.2.3) or SHA (e.g. @sha256:...) instead of floating branches or :latest."
        )


def validate_init_no_exit(recipe: Recipe) -> None:
    """Reject a recipe whose `init.run` contains a bash `exit` (Model A, main-liw).

    Under Model A the launcher SOURCES `init.run` into the attach shell that then execs the harness,
    so a bash `exit` terminates that shell — killing the session before the harness starts, silently.
    Authors from standalone-script habits reach for `exit 0`/`exit 1`; this fail-fast lint steers them
    to `return` (or a self-gating `… || { …; false; }`) instead. Called from assemble() alongside the
    other build-time recipe lints, before any file is emitted.
    """
    if recipe.init is None:
        return
    if _INIT_EXIT_RE.search(recipe.init.run):
        raise RecipeLintError(
            f"recipe '{recipe.name}': 'init.run' contains a bash 'exit' — init is SOURCED into the "
            "attach shell (Model A), so 'exit' would kill the session before the harness starts. "
            "Use 'return' or a self-gating '|| { …; false; }' instead."
        )


@dataclass
class Capabilities:
    """What a stack's running instance is expected to expose — the test oracle (§18)."""

    mcp_servers: list[str]
    skills: list[str]
    commands: list[str]
    plugins: list[str] = field(default_factory=list)


def expected_capabilities(stack: Stack, recipes: list[Recipe]) -> Capabilities:
    """Derive the declared capabilities from the manifest + each recipe's `expect:` block.

    Two sources, unioned: (1) what the assembler can SEE — `mcp.servers`, and the standalone
    `skills:`/`commands:` dirs it fans into the profile; (2) what a recipe DECLARES via `expect:`
    for capabilities it delivers through its Dockerfile (which the assembler cannot infer).
    """
    mcp: list[str] = []
    skills: list[str] = []
    commands: list[str] = []
    plugins: list[str] = []
    for recipe in recipes:
        mcp.extend(s.name for s in recipe.servers)
        skills.extend(s.name for s in recipe.skills)
        commands.extend(c.name for c in recipe.commands)
        mcp.extend(recipe.expect.mcp)
        skills.extend(recipe.expect.skills)
        commands.extend(recipe.expect.commands)
        plugins.extend(recipe.expect.plugins)
    # De-dup while preserving order (a recipe may both ship and declare the same name).
    dedup = lambda xs: list(dict.fromkeys(xs))
    return Capabilities(
        mcp_servers=dedup(mcp), skills=dedup(skills),
        commands=dedup(commands), plugins=dedup(plugins),
    )
