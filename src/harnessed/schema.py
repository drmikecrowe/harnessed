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

def _resolve_dir(root: Path | None, kind: str, name: str) -> Path:
    """Resolve catalog/<kind>/<name>.

    `root` given → search only that single root (root/<kind>/<name>) — explicit, used by tests with
    fixture trees. `root` None → resolve across the catalog roots (user overlay first), the
    production path.

    `name` may be a variety ref (`beads/stealth`) — see paths.catalog_relpath.
    """
    if root is None:
        return paths.find_in_catalog(kind, name)
    return Path(root) / kind / paths.catalog_relpath(name)

# Harness → config directory name (Claude Code canonical, design §8). The harness is a run-time
# positional (`harnessed <stack> <harness>`), not a stack field; a stack may not be named after one.
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
    # A ruamel YAML instance carries scanner/parser/constructor state across load() calls and is not
    # thread-safe. `harnessed build -j` assembles stacks on several threads, all loading recipes at
    # once; a shared instance interleaves and yields nonsense (marks from one file reported against
    # another, or a half-built mapping that "loads" with fields missing). One instance per load.
    yaml = YAML(typ="safe", pure=True)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh)
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


def _parse_hooks(raw_hooks) -> tuple[dict[str, list[HookCommand]], list[str]]:
    """Parse the `hooks:` block: {EventName: [{command, matcher?}, ...]} (GAP 2).

    Declarative — a recipe states exactly what belongs in settings.json's `hooks` object; the
    assembler (emit.py) renders it into Claude Code's native shape. Distinct from `init:` (which
    runs a command host-side, once, before the agent ever attaches): these commands run INSIDE
    Claude Code's own hook runner, every time the event fires, so a recipe needing "only once
    per project" behavior must gate that itself (e.g. check-and-touch a marker file in its script).

    `skip_harnesses:` (bd main-4fx) is the one non-event key: a list of harnesses on which THIS
    recipe's hooks are not emitted. Returned alongside the events. For when a recipe's capability
    is delivered NATIVELY on a harness and replaying the same hooks there would double-fire — see
    context-mode + omp, where the recipe installs upstream's own omp plugin (session_start /
    tool_call / tool_result / session_before_compact) and the same hook bodies replayed through
    omp-claude-hooks-bridge would write the session DB twice. Deliberately narrow: it drops only
    the declaring recipe's entries, only on the listed harnesses. Recipes stay harness-independent
    everywhere else — harness-specific BUILD steps still branch on ${HARNESS} in the Dockerfile;
    hooks are not a build step, so they cannot use that escape hatch.
    """
    if not raw_hooks:
        return {}, []
    if not isinstance(raw_hooks, dict):
        raise SchemaError(
            "recipe 'hooks' must be a mapping of {EventName: [{command, matcher?}, ...]}"
        )

    skip = _parse_hooks_skip_harnesses(raw_hooks.get("skip_harnesses"))

    parsed: dict[str, list[HookCommand]] = {}
    for event, entries in raw_hooks.items():
        if event == "skip_harnesses":
            continue
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
    return parsed, skip


def _parse_hooks_skip_harnesses(raw) -> list[str]:
    """Parse `hooks.skip_harnesses:` — harnesses on which this recipe's hooks are NOT emitted.

    Validated against HARNESS_CONFIG_DIR so a typo (`ompp`) fails at parse time rather than
    silently emitting the hooks it was meant to suppress.
    """
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(h, str) for h in raw):
        raise SchemaError("recipe 'hooks.skip_harnesses' must be a list of harness names")
    skip = [h.strip() for h in raw if h.strip()]
    unknown = sorted(set(skip) - set(HARNESS_CONFIG_DIR))
    if unknown:
        raise SchemaError(
            f"recipe 'hooks.skip_harnesses': unknown harness(es) {unknown} — "
            f"valid harnesses: {', '.join(sorted(HARNESS_CONFIG_DIR))}"
        )
    return skip


@dataclass
class SetupConfigItem:
    """One config value a recipe's executable setup needs (recipe.yaml `setup.config[]`).

    Exactly one of `derive` / `prompt` drives it:
      * derive — a template over repo-identity primitives ({repo}, {gcd_db}, …), resolved silently.
      * prompt — asked on first launch (default is a template too); non-interactive → uses default.
    The resolved value is referenced in `setup.run` as {config.<key>}."""
    key: str
    derive: str | None = None
    prompt: str | None = None
    default: str | None = None


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
    # Executable, config-driven first-run setup (host-native). `config` items are resolved on first
    # launch (derived from repo-identity primitives, or prompted), then substituted into `run`, which
    # is executed once (gated by `condition`). See launcher._host_run_setups.
    config: list["SetupConfigItem"] = field(default_factory=list)
    run: str | None = None
    # BOTH-MODE replacement for `run` (and for `provision:`): a bash script in the recipe dir, run
    # host-side by the launcher AND inside the container before attach. Unlike `run` it receives the
    # resolved config as HARNESSED_CFG_<KEY> env vars rather than {config.<key>} substitution, so the
    # same file works in both modes with no templating. Mutually exclusive with `run`.
    # The script is expected to be idempotent — it runs on every launch, and self-gates.
    script: str | None = None


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

    run = raw_setup.get("run")
    if run is not None and (not isinstance(run, str) or not run.strip()):
        raise SchemaError("recipe 'setup.run', if set, must be a non-empty string")
    script = raw_setup.get("script")
    if script is not None and (not isinstance(script, str) or not script.strip()):
        raise SchemaError("recipe 'setup.script', if set, must be a non-empty string")
    if script and run:
        raise SchemaError(
            "recipe 'setup': 'script' and 'run' are mutually exclusive — 'script' is the "
            "both-mode replacement for 'run'"
        )
    if script and (Path(script).is_absolute() or ".." in Path(script).parts):
        raise SchemaError(
            f"recipe 'setup.script' {script!r} must be a relative path inside the recipe dir"
        )
    config = _parse_setup_config(raw_setup.get("config"))

    unknown = sorted(set(raw_setup) - {"summary", "reference", "condition", "run", "script", "config"})
    if unknown:
        raise SchemaError(
            f"recipe 'setup': unknown field(s) {unknown} — valid fields: "
            "summary, reference, condition, run, script, config"
        )
    return SetupSpec(
        summary=summary.strip(),
        reference=reference.strip(),
        condition=condition.strip() if condition else None,
        run=run.strip() if run else None,
        script=script.strip() if script else None,
        config=config,
    )


@dataclass
class InstallSpec:
    """A recipe's `install:` — the BUILD-phase sibling of `setup.script` (bd harnessed-8px.3).

    Same language (bash), same file-in-the-recipe-dir shape, same lint. The ONLY difference is the
    PHASE, and that difference is forced, not preferential:

      install  container: BUILD TIME  (`RUN bash install.sh` in the derived Dockerfile)
               host:      after `_materialize_host_home`, before setup
      setup    container: RUNTIME     (`podman exec` into the started container)
               host:      after install

    `setup` cannot run at build (no project bind-mount, so HARNESSED_PROJECT_DIR is unresolvable);
    `install` must not run at container runtime (it is baking the image — running it per container
    start would re-pay the clone every launch). The consequence for the env contract is that
    `install` sees a strictly PROJECT-INDEPENDENT env (see launcher._install_env): the folder-env
    vars a build cannot know are deliberately absent rather than present-but-wrong.
    """
    # Relative path to the bash script inside the recipe dir. OPTIONAL, but only because a
    # ROOT-ONLY install exists: a recipe whose install is ENTIRELY system-level (apt-get, a binary
    # landing in /usr/local/bin) has no user-level half to put in a script, yet still must be able
    # to declare `system:` so a host launch WARNS rather than silently shipping a stack that is
    # missing the tool. At least one of `script` / `system`, or `install:` says and does nothing.
    script: str | None = None
    # A PINNED content ref (tag/SHA/version). Its presence turns on the host content cache at
    # $XDG_CACHE_HOME/harnessed/install/<recipe>/<cache>, handed to the script as
    # $HARNESSED_INSTALL_CACHE. The cache is what makes "run on EVERY host launch" affordable:
    # `_materialize_host_home` rmtree's the home each launch (so the output cannot persist and
    # "first launch only" is structurally wrong), but the SOURCE content can persist, keyed by a
    # ref that by policy never moves. Floating values are rejected — a moving key is a stale cache.
    cache: str | None = None
    # Non-empty reason string ⇒ this recipe's install has a SYSTEM-LEVEL component (USER root,
    # apt-get, COPY into /usr/local/bin) that only a container build can perform. harnessed must
    # never sudo or mutate the user's system, so on a host launch that component is SKIPPED — but
    # LOUDLY, naming the recipe and this reason. A silent skip is exactly how harnessed-8px.1
    # (14 missing skills, no error) happened; the reason string is what makes it un-silent.
    system: str | None = None
    # Non-empty reason string ⇒ every pin behind this install script is MANUAL-UPGRADE-ONLY.
    # `harnessed update` (bd harnessed-tfm) may LIST a newer upstream ref for them, but must never
    # put them in the interactive bump set and must never fail `--check` on them. The motivating
    # case is SKILL content: a skill is agent INSTRUCTIONS run with the agent's full tool
    # permissions, so a compromised upgrade is prompt injection, not a CVE — nothing in the
    # osv/trivy/grype family detects it, and a human has to read the diff. `cache` cannot carry
    # this meaning: agent-carnet keys a CLI+skill install with it, so its presence classifies
    # nothing. Like `system`, the value is a REASON, not a flag — it is shown to whoever decides
    # whether to lift the hold.
    hold: str | None = None


# Bare refs that MOVE. `_FLOATING_REF_RE` only catches the decorated forms (`--branch main`,
# `@latest`), so a bare `cache: main` would sail through it — hence this second list.
_FLOATING_CACHE_KEYS = frozenset({"latest", "main", "master", "head", "trunk", "dev", "edge"})


def _parse_install(raw_install) -> "InstallSpec | None":
    """Parse the optional `install:` object — omitted by recipes that install nothing."""
    if not raw_install:
        return None
    if not isinstance(raw_install, dict):
        raise SchemaError("recipe 'install' must be an object with a 'script' or 'system' field")
    script = raw_install.get("script")
    if script is not None:
        if not isinstance(script, str) or not script.strip():
            raise SchemaError("recipe 'install.script' must be a non-empty string")
        script = script.strip()
        if Path(script).is_absolute() or ".." in Path(script).parts:
            raise SchemaError(
                f"recipe 'install.script' {script!r} must be a relative path inside the recipe dir"
            )
    cache = raw_install.get("cache")
    if cache is not None:
        if not isinstance(cache, str) or not cache.strip():
            raise SchemaError("recipe 'install.cache', if set, must be a non-empty string")
        cache = cache.strip()
        if cache.lower() in _FLOATING_CACHE_KEYS or _FLOATING_REF_RE.search(cache):
            raise SchemaError(
                f"recipe 'install.cache' {cache!r} is a floating ref — the cache key must be a "
                "pinned tag, version, or SHA, or the cache goes stale and never refreshes."
            )
        if "/" in cache or cache.startswith("."):
            raise SchemaError(
                f"recipe 'install.cache' {cache!r} must be a bare ref (no '/' or leading '.') — "
                "it becomes a single directory name under the harnessed install cache."
            )
    system = raw_install.get("system")
    if system is not None and (not isinstance(system, str) or not system.strip()):
        raise SchemaError(
            "recipe 'install.system', if set, must be a non-empty string explaining WHICH "
            "system-level step only a container build can perform (it is printed verbatim as the "
            "host-skip warning)"
        )
    hold = raw_install.get("hold")
    if hold is not None and (not isinstance(hold, str) or not hold.strip()):
        raise SchemaError(
            "recipe 'install.hold', if set, must be a non-empty string explaining WHY this "
            "recipe's pins are manual-upgrade-only (it is shown to whoever decides whether to "
            "lift the hold — a bare `hold: true` throws that away)"
        )
    unknown = sorted(set(raw_install) - {"script", "cache", "system", "hold"})
    if unknown:
        raise SchemaError(
            f"recipe 'install': unknown field(s) {unknown} — valid fields: script, cache, system, "
            "hold"
        )
    if hold and script is None:
        raise SchemaError(
            "recipe 'install.hold' without 'install.script' — the hold marks the pins fetched BY "
            "the script as manual-upgrade-only; a root-only install has no such pins to hold."
        )
    if cache and script is None:
        raise SchemaError(
            "recipe 'install.cache' without 'install.script' — the cache exists only to be "
            "populated and read BY the script; a root-only install has nothing to hand it to."
        )
    if script is None and not system:
        raise SchemaError(
            "recipe 'install' needs at least one of 'install.script' (the user-level half, run in "
            "BOTH modes) or 'install.system' (the reason a root-only step is container-only). With "
            "neither it declares nothing and executes nothing."
        )
    return InstallSpec(
        script=script,
        cache=cache,
        system=system.strip() if system else None,
        hold=hold.strip() if hold else None,
    )


def _parse_setup_config(raw_config) -> list["SetupConfigItem"]:
    if not raw_config:
        return []
    if not isinstance(raw_config, list):
        raise SchemaError("recipe 'setup.config' must be a list of {key, derive|prompt} items")
    out: list[SetupConfigItem] = []
    for entry in raw_config:
        if not isinstance(entry, dict):
            raise SchemaError(f"recipe 'setup.config' entry {entry!r} must be a mapping")
        key = str(entry.get("key", "")).strip()
        derive = entry.get("derive")
        prompt = entry.get("prompt")
        default = entry.get("default")
        if not key:
            raise SchemaError(f"recipe 'setup.config' entry {entry!r} needs a non-empty 'key'")
        if not (derive or prompt):
            raise SchemaError(f"recipe 'setup.config' '{key}' needs 'derive' or 'prompt'")
        unknown = sorted(set(entry) - {"key", "derive", "prompt", "default"})
        if unknown:
            raise SchemaError(f"recipe 'setup.config' '{key}': unknown field(s) {unknown}")
        out.append(SetupConfigItem(
            key=key,
            derive=str(derive).strip() if derive else None,
            prompt=str(prompt).strip() if prompt else None,
            default=str(default) if default is not None else None,
        ))
    return out


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
    # Harnesses on which THIS recipe's `hooks` are not emitted (recipe.yaml `hooks.skip_harnesses`,
    # bd main-4fx) — for a capability delivered natively on that harness, where replaying the same
    # hooks would double-fire. Other recipes' hooks in the same stack are unaffected.
    hooks_skip_harnesses: list[str] = field(default_factory=list)
    # Other recipe names this recipe must never be combined with in the same stack (e.g. two
    # recipes that both claim to be the agent's sole cross-session memory store). Checked
    # symmetrically across a stack's whole recipe list (see _check_recipe_conflicts) — declaring
    # it on either side is enough.
    conflicts: list[str] = field(default_factory=list)
    setup: "SetupSpec | None" = None
    # Build-phase install script (recipe.yaml `install:`) — ONE bash file executed by BOTH the
    # container build (`RUN bash install.sh`) and a host launch. The mechanism that makes a
    # Dockerfile RUN's deliverables exist on `launch --host` too. See InstallSpec.
    install: "InstallSpec | None" = None
    # Extra outbound hosts this recipe's tools need — appended to the container egress firewall
    # allowlist (catalog/base/egress-firewall.sh) at launch, ONLY when this recipe is in the stack
    # (the firewall stays default-DROP otherwise). Bare hostnames, no scheme/path/port (e.g.
    # `api.pulumi.com`). See docs/guides/egress.md.
    egress: list[str] = field(default_factory=list)
    # Extra mise-managed tools installed into the derived image as a `mise use -g` layer (e.g.
    # `pulumi@3.140.0`). MUST be pinned — a floating `@latest`/bare name is rejected, same as a
    # Dockerfile pin. Lets a recipe add a CLI + open its egress with NO Dockerfile. See egress.md.
    tools: list[str] = field(default_factory=list)
    # Spec → hold reason, for the `tools:` entries written in the mapping form (bd harnessed-c5t).
    # Held pins are still installed exactly like any other — the hold speaks only to `harnessed
    # update`, which lists them informationally and never offers to bump them. Empty for the
    # overwhelmingly common plain-string form. The install-script equivalent is InstallSpec.hold.
    tools_hold: dict[str, str] = field(default_factory=dict)
    # Environment for the RUNNING agent (recipe.yaml `env:`) — NAME → value template. The one
    # recipe deliverable a bash script cannot express (an `export` dies with the script). Values are
    # mode-portable templates; see _parse_env / resolve_recipe_env for the placeholder contract.
    # Distinct from McpServer.env, which is per-MCP-server.
    env: dict[str, str] = field(default_factory=dict)
    root: Path = field(default_factory=Path)  # the recipe dir (for resolving relative paths)
    # The catalog ref a stack used to load this recipe — `beads/stealth` for a variety, else the
    # plain name. Carries the FAMILY (the part before the slash), which _check_recipe_conflicts uses
    # to make sibling varieties implicitly exclusive. Defaults to `name` when loaded directly.
    ref: str = ""
    raw: dict = field(default_factory=dict)


# Authored `permissions:` values a stack.yaml may set — kept in sync with
# emit._PERMISSION_DEFAULT_MODE, the table that maps each to a Claude `permissions.defaultMode`.
# Claude's own mode names pass through verbatim; `prompt`/`yolo` are aliases (bd harnessed-8px.8).
# Restated rather than imported because emit imports schema — the dependency cannot be reversed.
# tests/test_schema.py asserts this set equals emit._PERMISSION_DEFAULT_MODE's keys, so the two
# cannot drift silently.
_STACK_PERMISSIONS_MODES = frozenset({
    "acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan",
    "prompt", "yolo",
})


@dataclass
class Stack:
    name: str
    recipes: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    # Harnesses this stack is meant to be built for. A stack stays harness-INDEPENDENT (the harness
    # is still a run-time argument); this is purely a build-time convenience: `harnessed build
    # <stack>` with no harness builds every name listed here, and a bare `harnessed build` includes
    # these (stack, harness) pairs in its reconciliation sweep. Empty → no declaration; `build
    # <stack>` then still requires an explicit harness argument.
    harnesses: list[str] = field(default_factory=list)
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
    # Opt-in (default OFF): forward host AWS credentials via the aws-sso ECS server (aws-sso-cli
    # `aws-sso ecs server`, default slot). When ON and the host has a bearer token configured (via
    # `harnessed aws-sso serve`), the launcher injects AWS_CONTAINER_CREDENTIALS_FULL_URI (pointing at
    # host.containers.internal:<port>) + AWS_CONTAINER_AUTHORIZATION_TOKEN so the in-container AWS SDK
    # pulls short-lived STS creds over HTTP — no aws-sso binary, ~/.aws-sso store, or SSO token ever
    # enters the container. SECRET-BEARING (STS creds are NOT touch-gated like the SSH agent) → opt-in,
    # unlike the agent auto-forward. No-op when the host token file is absent. See
    # _aws_sso_ecs_forward_args and docs/guides/aws-sso.md.
    forward_aws_sso: bool = False
    state: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class ServiceDef:
    """A service sidecar definition (design §3/§9, plan 04-01 SVC-01).

    Two scopes:

    `scope: global` (default) — the original shape. ONE image/container/volume on a
    host-published port (reachable via `host.containers.internal:<port>`; or by DNS name over the
    `HARNESSED_NET` bridge on bridge-capable hosts), with a lifecycle independent of any instance.
    A recipe references it via `mcp.servers[].service`; the assembler resolves the service name →
    a hatago URL-proxy entry pointing at `http://host.containers.internal:<port>/mcp`
    (the `HARNESSED_NET` opt-in bridge form is `http://<name>:<port>/mcp`; plan 04-01 Task 4).

    `scope: project` — one container PER PROJECT (git-common-dir keyed), for a service that holds
    an EXCLUSIVE on-disk lock over per-project data and therefore cannot be shared: a
    `dolt sql-server` is the motivating case. Two things follow from that:

      * `data.persist` replaces `volume`. The launcher bind-mounts the host dir behind a persist
        entry declared by a recipe in the stack, so the SERVICE inherits the RECIPE's placement
        choice (`location: in_repo` vs `host`) rather than owning a named volume of its own.
      * `socket` was the original answer to reaching it, and `publish: ephemeral` is the current
        one. See below — the socket form is still supported, but a socket-only server is reachable
        only by code that speaks unix sockets, and a client that falls back to TCP for any part of
        its work (bd's health checks do) has nothing to connect to.

    `publish: ephemeral` — publish the container's `port` on an ephemeral HOST port bound to
    127.0.0.1, then read back what the runtime chose (`podman port <ctr> <port>`). This is how a
    project-scoped service gets a port without the launcher owning any allocation machinery: the
    runtime allocates, so N per-project sidecars never collide and nothing is recorded on disk to
    drift. Loopback-bound deliberately — the published port is reachable by any local process, so
    a service using this must authenticate (see `client_env` `{password}`).

    `client_env` — the env a CLIENT needs to reach this service, declared BY THE SERVICE because
    only the service knows its own protocol's variable names. Values are templated on `{host}`,
    `{port}`, `{socket}`, `{password}`; the launcher resolves them per launch (the port does not
    exist until the container runs, so this cannot go through `resolve_recipe_env`, which runs at
    emit time) and injects the result into the agent's environment. Keeps `launcher` generic: it
    knows "a service declares client env", not "beads wants BEADS_DOLT_SERVER_PORT".
    """

    name: str
    image: str
    port: int = 0
    scope: str = "global"
    socket: str = ""
    publish: str = ""
    client_env: dict[str, str] = field(default_factory=dict)
    data_persist: str = ""
    volume: str = ""
    healthcheck: str = ""
    exclusive_lock: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_socket_only(self) -> bool:
        """True when peers reach this service through a unix socket, not a published port."""
        return bool(self.socket)

    @property
    def is_ephemeral_port(self) -> bool:
        """True when the runtime picks the host port at run time and the launcher reads it back."""
        return self.publish == "ephemeral"

    @property
    def wants_password(self) -> bool:
        """True when any client_env value needs `{password}` — the launcher then provisions one."""
        return any("{password}" in v for v in self.client_env.values())


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
    "conflicts", "hooks", "setup", "install", "egress", "tools", "env",  # typed
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


def _suggest_field(unknown: str, known: frozenset[str] = KNOWN_RECIPE_FIELDS) -> str | None:
    """The closest known field within edit distance 2 (so `skkills` → `skills`), else None."""
    best = min(known, key=lambda k: _levenshtein(unknown, k))
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


def _parse_egress(raw_egress, manifest: Path) -> list[str]:
    """Parse a recipe's `egress:` list into validated bare hostnames (no scheme/path/port)."""
    if not raw_egress:
        return []
    if not isinstance(raw_egress, list):
        raise SchemaError(f"{manifest}: 'egress' must be a list of hostnames")
    out: list[str] = []
    for entry in raw_egress:
        host = entry.strip() if isinstance(entry, str) else entry
        if not isinstance(host, str) or not _HOSTNAME_RE.match(host):
            raise SchemaError(
                f"{manifest}: egress entry {entry!r} is not a bare hostname "
                "(no scheme, path, or port — e.g. 'api.pulumi.com')"
            )
        out.append(host)
    return out



def _parse_tools(raw_tools, manifest: Path) -> tuple[list[str], dict[str, str]]:
    """Parse a recipe's `tools:` list into pinned mise tool specs (e.g. 'pulumi@3.140.0').

    Two entry forms, and the mapping one exists ONLY to carry a hold (bd harnessed-c5t):

        tools:
          - npm:ccstatusline@2.2.22            # plain — bumpable by `harnessed update`
          - spec: github:foo/bar@1.2.3         # held — listed informationally, never auto-bumped
            hold: "upstream 2.x drops the API we depend on"

    Returns (specs, holds). The specs list is IDENTICAL in both forms so every consumer of
    `Recipe.tools` (emit's and launcher's `mise use -g` layer) stays a list-of-strings and never
    learns that holds exist. Only `harnessed update` reads the second value.
    """
    if not raw_tools:
        return [], {}
    if not isinstance(raw_tools, list):
        raise SchemaError(f"{manifest}: 'tools' must be a list of pinned mise tools")
    out: list[str] = []
    holds: dict[str, str] = {}
    for entry in raw_tools:
        hold = None
        if isinstance(entry, dict):
            unknown = sorted(set(entry) - {"spec", "hold"})
            if unknown:
                raise SchemaError(
                    f"{manifest}: tools entry has unknown field(s) {unknown} — a mapping entry "
                    "takes exactly 'spec' and optionally 'hold'"
                )
            spec = entry.get("spec")
            if not isinstance(spec, str) or not spec.strip():
                raise SchemaError(
                    f"{manifest}: tools entry {entry!r} must carry a non-empty 'spec' — a hold "
                    "with nothing to hold is not a pin"
                )
            hold = entry.get("hold")
            if hold is not None and (not isinstance(hold, str) or not hold.strip()):
                raise SchemaError(
                    f"{manifest}: tools entry {spec!r} has a 'hold' that is not a non-empty "
                    "reason string — the reason is shown to whoever decides whether to lift it"
                )
        else:
            spec = entry
        spec = spec.strip() if isinstance(spec, str) else spec
        if not isinstance(spec, str) or not spec:
            raise SchemaError(f"{manifest}: tools entry {entry!r} must be a non-empty string")
        # A hold freezes the pin; it does not license a floating one. Both forms are pinned or
        # neither is — otherwise `hold:` becomes the escape hatch that reintroduces `@latest`.
        if _FLOATING_REF_RE.search(spec) or "@" not in spec:
            raise SchemaError(
                f"{manifest}: tools entry {spec!r} must be pinned to an explicit version "
                "(e.g. 'pulumi@3.140.0' — no '@latest' and no bare tool name)"
            )
        out.append(spec)
        if hold:
            holds[spec] = hold.strip()
    return out, holds


# --- Recipe `env:` — environment for the RUNNING agent (bd harnessed-8px.2) --------------------
#
# The one recipe deliverable that cannot become a bash script: a script's `export` dies with the
# script's process, but this env must be live for the agent (and its hooks and child processes).
# Hence a declarative field rather than another executable step.
#
# THE TRAP the templates exist to solve: a value like `/home/harnessed/.beads` is CONTAINER-absolute
# (`/home/harnessed` is the POD's $HOME). Copied literally into a `launch --host` it names a
# directory that does not exist on the host. So values are TEMPLATES over the launcher's existing
# path contract, resolved per mode, and ONE declaration yields the right absolute path in each:
#
#   {persist:<name>}  the dir this recipe's `persist:` entry <name> actually resolves to.
#                     container → $CONTAINER_HOME/<name> (where _persist_mounts bind-mounts it);
#                     host      → the real $XDG_DATA_HOME/harnessed/persist/... dir, keyed by the
#                                 entry's own scope (workspace vs project) — i.e. the same
#                                 arithmetic _persist_mounts / _service_data_dir already do.
#                     A `location: in_repo` entry resolves to the in-repo dir, which is identical in
#                     both modes (the workspace is mounted path-preserving).
#   {project_dir}     the project workspace root — mode-invariant for the same reason
#                     HARNESSED_PROJECT_DIR is (_build_mount_args mounts it at its own host path).
#   {host_home}       the REAL host $HOME, which in the pod is NOT $HOME (precedent: the HOST_HOME
#                     export in _init_shell_prologue).
#
# A `scope: global` persist entry is deliberately NOT referenceable: it is mounted path-preserving
# (host path == container path), so a recipe needing it writes the literal path and it is already
# correct in both modes.
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_ENV_BARE_PLACEHOLDERS = frozenset({"project_dir", "host_home"})


def _parse_env(raw_env, manifest: Path) -> dict[str, str]:
    """Parse a recipe's `env:` mapping of NAME → value template. NOT McpServer.env (that one is
    per-MCP-server and passed to that one server process; this one is the agent's own env)."""
    if not raw_env:
        return {}
    if not isinstance(raw_env, dict):
        raise SchemaError(f"{manifest}: 'env' must be a mapping of NAME: value")
    out: dict[str, str] = {}
    for name, val in raw_env.items():
        if not isinstance(name, str) or not _ENV_NAME_RE.match(name):
            raise SchemaError(
                f"{manifest}: env key {name!r} is not a valid environment variable name "
                "(letters, digits, underscore; not starting with a digit)"
            )
        if isinstance(val, bool) or val is None:
            raise SchemaError(
                f"{manifest}: env value for {name!r} must be a string or number, got {val!r} — "
                "quote it (e.g. \"1\") so the value is unambiguous"
            )
        out[name] = str(val)
    return out


def _validate_env_templates(env: dict[str, str], persist: PersistSpec, manifest: Path) -> None:
    """Reject unknown placeholders and dangling `{persist:<name>}` refs AT LOAD, not at launch —
    otherwise a typo surfaces as a literal `{persist:.bead}` in the agent's env, silently."""
    names = {e.name for e in persist.entries if e.name is not None}
    for var, template in env.items():
        for ph in _ENV_PLACEHOLDER_RE.findall(template):
            if ph in _ENV_BARE_PLACEHOLDERS:
                continue
            if not ph.startswith("persist:"):
                raise SchemaError(
                    f"{manifest}: env {var}: unknown placeholder '{{{ph}}}'. Known: "
                    "{persist:<name>}, {project_dir}, {host_home}"
                )
            ref = ph[len("persist:"):]
            if ref not in names:
                known = ", ".join(sorted(names)) or "(none declared)"
                raise SchemaError(
                    f"{manifest}: env {var}: '{{{ph}}}' references a persist entry this recipe does "
                    f"not declare. Declared persist names: {known}"
                )


def _persist_entry_dir(
    recipe: Recipe, entry: PersistEntry, *, mode: str, project_path: Path | None
) -> str | None:
    """Absolute path an `env:` template's `{persist:<name>}` resolves to, or None when it cannot be
    known yet (build time has no project). Mirrors _persist_mounts / _service_data_dir placement."""
    assert entry.name is not None
    if entry.location == "in_repo":
        # Path-preserving in both modes — but anchored at the checkout, so it needs the project.
        return None if project_path is None else str(paths.persist_in_repo_dir(project_path, entry.name))
    if mode == "container":
        # Where _persist_mounts bind-mounts it — a fixed container path, project-independent, which
        # is exactly why this case survives being baked into the image at build time.
        return f"{paths.CONTAINER_HOME}/{entry.name}"
    if project_path is None:
        return None
    if entry.scope == "project":
        return str(paths.persist_project_dir(recipe.name, project_path, entry.name))
    return str(paths.persist_workspace_dir(recipe.name, project_path, entry.name))


def resolve_recipe_env(
    recipe: Recipe, *, mode: str, project_path: Path | None
) -> dict[str, str]:
    """Resolve a recipe's `env:` templates for one mode ('container' or 'host').

    `project_path=None` means BUILD time (no project exists yet): any var whose value needs the
    project is OMITTED rather than half-substituted. Those still reach the agent at launch, where
    the project is known — build-time `ENV` is only the extra guarantee that an image-build step
    (a Dockerfile RUN / install script) sees what it can.
    """
    by_name = {e.name: e for e in recipe.persist.entries if e.name is not None}
    resolved: dict[str, str] = {}
    for var, template in recipe.env.items():
        deferred = False

        def _sub(m: re.Match) -> str:
            nonlocal deferred
            ph = m.group(1)
            if ph == "host_home":
                return str(Path.home())
            if ph == "project_dir":
                if project_path is None:
                    deferred = True
                    return ""
                return str(project_path)
            if ph.startswith("persist:"):
                entry = by_name.get(ph[len("persist:"):])
                if entry is None:  # unreachable: _validate_env_templates rejects this at load
                    raise SchemaError(
                        f"recipe '{recipe.name}': env {var}: no persist entry '{ph[len('persist:'):]}'"
                    )
                val = _persist_entry_dir(recipe, entry, mode=mode, project_path=project_path)
                if val is None:
                    deferred = True
                    return ""
                return val
            raise SchemaError(f"recipe '{recipe.name}': env {var}: unknown placeholder '{{{ph}}}'")

        value = _ENV_PLACEHOLDER_RE.sub(_sub, template)
        if not deferred:
            resolved[var] = value
    return resolved


def load_recipe(recipe_dir: Path, *, strict: bool = False, ref: str = "") -> Recipe:
    recipe_dir = Path(recipe_dir)
    manifest = recipe_dir / "recipe.yaml"
    if not manifest.is_file():
        raise SchemaError(f"recipe manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    if "name" not in raw:
        raise SchemaError(f"{manifest}: required field 'name' is missing")
    if strict:
        _validate_recipe_fields(raw, manifest)
    hooks, hooks_skip_harnesses = _parse_hooks(raw.get("hooks"))
    persist = _parse_persist(raw.get("persist"))
    env = _parse_env(raw.get("env"), manifest)
    _validate_env_templates(env, persist, manifest)
    tools, tools_hold = _parse_tools(raw.get("tools"), manifest)
    return Recipe(
        name=raw["name"],
        description=raw.get("description", ""),
        servers=_parse_servers(raw.get("mcp", {}) or {}),
        skills=_parse_fileext(raw.get("skills")),
        commands=_parse_fileext(raw.get("commands")),
        rules=_parse_fileext(raw.get("rules")),
        expect=_parse_expect(raw.get("expect")),
        persist=persist,
        init=_parse_init(raw.get("init")),
        hooks=hooks,
        hooks_skip_harnesses=hooks_skip_harnesses,
        conflicts=_parse_conflicts(raw.get("conflicts")),
        setup=_parse_setup(raw.get("setup")),
        install=_parse_install(raw.get("install")),
        egress=_parse_egress(raw.get("egress"), manifest),
        tools=tools,
        tools_hold=tools_hold,
        env=env,
        root=recipe_dir,
        ref=ref or raw["name"],
        raw=raw,
    )


KNOWN_STACK_FIELDS = frozenset({
    "name", "extends", "recipes", "services", "harnesses", "permissions", "instructions",
    "forward_git_credentials", "ssh_keys", "forward_aws_sso", "hatago", "state",
})
# `hatago` stays in the KNOWN set deliberately after its removal (bd harnessed-1t4.1): it must reach
# `_reject_removed_hatago_override`, whose message says what replaced it, rather than dying in the
# generic "unknown field / did you mean" path.

# Fields a child UNIONS with its parent's (parent order first, then the child's additions, de-duped).
# Everything else is an override: a key the child declares wins outright; a key it omits is
# inherited. `name` is never inherited (a stack is identified by its own directory), and `extends`
# itself is consumed here rather than carried into the merged manifest.
_STACK_UNION_FIELDS = ("recipes", "services", "harnesses", "ssh_keys")


def _validate_stack_fields(raw: dict, manifest: Path) -> None:
    """Reject unknown top-level stack fields.

    Stack parsing used to be tolerant (`additionalProperties: true`), which meant an unsupported or
    misspelled key did NOTHING, silently: an `extends:` written before the feature existed looked
    accepted and inherited nothing for months. A stack manifest is small and fully specified, so
    there is no forward-field case to protect (unlike recipes' D-14 fields) — an unknown key here is
    always a bug, and it should be loud.
    """
    unknown = sorted(set(raw) - KNOWN_STACK_FIELDS)
    if not unknown:
        return
    described = [
        f"{f!r}" + (f" (did you mean {s!r}?)" if (s := _suggest_field(f, KNOWN_STACK_FIELDS)) else "")
        for f in unknown
    ]
    raise SchemaError(
        f"{manifest}: unknown stack field(s): {', '.join(described)}. "
        f"Known fields: {', '.join(sorted(KNOWN_STACK_FIELDS))}."
    )


def _resolve_parent_stack_dir(parent: str, stack_dir: Path, manifest: Path) -> Path:
    """Locate the stack named by `extends:`.

    Same catalog root as the child first (so a fixture tree, or a self-contained overlay, resolves
    within itself), then the normal catalog search (user overlay first, then the repo) — which is
    what lets a stack in the user overlay extend one shipped in the repo catalog.
    """
    sibling = stack_dir.parent / parent
    if (sibling / "stack.yaml").is_file():
        return sibling
    try:
        return _resolve_dir(None, "stacks", parent)
    except SchemaError as exc:
        raise SchemaError(
            f"{manifest}: extends: '{parent}' — no such stack in this catalog root or the "
            f"catalog search path ({exc})"
        ) from exc


def _resolve_stack_extends(raw: dict, stack_dir: Path, manifest: Path, chain: tuple[Path, ...]) -> dict:
    """Merge a stack manifest onto the one it `extends:`, returning a single flat manifest.

    Merging happens on the RAW dict, before any field parsing, so inheritance needs no per-field
    knowledge and every validator downstream sees one fully-resolved manifest.

    Semantics:
      * `recipes` / `services` / `harnesses` / `ssh_keys` — UNION, parent's entries first, then the
        child's, de-duped. A base stack therefore carries a baseline recipe set that children extend
        rather than restate.
      * every other field — the child's value wins if it declares the key, else the parent's is
        inherited (`state` and `hatago` included: a declared value replaces, it does not deep-merge).
      * `name` is always the child's own; `extends` is consumed and never appears in the result.

    Chains are allowed (a stack may extend a stack that extends another); a cycle is an error.
    """
    parent_name = raw.get("extends")
    if not parent_name:
        return raw
    if not isinstance(parent_name, str):
        raise SchemaError(f"{manifest}: 'extends' must be a stack name (a string)")

    parent_dir = _resolve_parent_stack_dir(parent_name, stack_dir, manifest).resolve()
    if parent_dir in chain:
        cycle = " -> ".join(p.name for p in (*chain, parent_dir))
        raise SchemaError(f"{manifest}: 'extends' cycle: {cycle}")

    parent_raw = _load_stack_raw(parent_dir, chain=(*chain, parent_dir))

    merged = dict(parent_raw)
    for key, value in raw.items():
        if key == "extends":
            continue
        if key in _STACK_UNION_FIELDS:
            inherited = list(parent_raw.get(key, []) or [])
            merged[key] = list(dict.fromkeys([*inherited, *(value or [])]))
        else:
            merged[key] = value
    merged["name"] = raw["name"]  # identity is never inherited
    merged.pop("extends", None)
    return merged


def _load_stack_raw(stack_dir: Path, chain: tuple[Path, ...] = ()) -> dict:
    """Read + validate one stack manifest and fold in whatever it `extends:`."""
    manifest = stack_dir / "stack.yaml"
    if not manifest.is_file():
        raise SchemaError(f"stack manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    if "name" not in raw:
        raise SchemaError(f"{manifest}: required field 'name' is missing")
    _validate_stack_fields(raw, manifest)
    return _resolve_stack_extends(raw, stack_dir, manifest, chain)


def load_stack(stack_dir: Path) -> Stack:
    stack_dir = Path(stack_dir)
    manifest = stack_dir / "stack.yaml"
    raw = _load_stack_raw(stack_dir, chain=(stack_dir.resolve(),))
    # A stack is resolved by DIRECTORY name (`_resolve_dir(root, "stacks", stack_name)`), so the
    # directory is the identity and `name:` is a restatement of it. Nothing used to enforce that
    # they agree — and `staleness.compute_stamp` re-resolves the manifest from `stack.name`, so a
    # mismatch surfaced far downstream as a FileNotFoundError against a directory that never
    # existed. Fail here instead, where the fix is obvious.
    if raw["name"] != stack_dir.name:
        raise SchemaError(
            f"{manifest}: stack name '{raw['name']}' does not match its directory "
            f"'{stack_dir.name}' — a stack is resolved by directory name, so the two must agree "
            f"(rename the directory, or set name: {stack_dir.name})"
        )
    if raw["name"] in HARNESS_CONFIG_DIR:
        raise SchemaError(
            f"{manifest}: stack name '{raw['name']}' conflicts with a harness name — "
            f"choose a different name (harness names: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
    harnesses = _parse_harnesses(raw.get("harnesses"), manifest)
    ssh_keys = _parse_ssh_keys(raw.get("ssh_keys"), manifest)
    _reject_removed_hatago_override(raw, manifest)
    permissions = raw.get("permissions")
    if permissions is not None and permissions not in _STACK_PERMISSIONS_MODES:
        raise SchemaError(
            f"{manifest}: unsupported permissions '{permissions}' "
            f"(supported: {', '.join(sorted(_STACK_PERMISSIONS_MODES))})"
        )
    return Stack(
        name=raw["name"],
        recipes=list(raw.get("recipes", []) or []),
        services=list(raw.get("services", []) or []),
        harnesses=harnesses,
        permissions=permissions,
        instructions=raw.get("instructions"),
        forward_git_credentials=bool(raw.get("forward_git_credentials", False)),
        ssh_keys=ssh_keys,
        forward_aws_sso=bool(raw.get("forward_aws_sso", False)),
        state=dict(raw.get("state", {}) or {}),
        raw=raw,
    )


def _parse_harnesses(raw_harnesses, manifest: Path) -> list[str]:
    """Validate the stack `harnesses:` list — the harnesses `harnessed build <stack>` fans out to.

    Names are validated against HARNESS_CONFIG_DIR at LOAD time (not build time) so a typo like
    `opencodee` fails on the manifest that contains it, rather than midway through a fan-out that
    already built two other images.
    """
    if raw_harnesses is None:
        return []
    if not isinstance(raw_harnesses, list):
        raise SchemaError(f"{manifest}: 'harnesses' must be a list of harness names")
    names: list[str] = []
    for entry in raw_harnesses:
        if not isinstance(entry, str) or not entry:
            raise SchemaError(f"{manifest}: 'harnesses' entries must be non-empty strings")
        if entry not in HARNESS_CONFIG_DIR:
            raise SchemaError(
                f"{manifest}: unsupported harness '{entry}' in 'harnesses' "
                f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
            )
        if entry not in names:
            names.append(entry)
    return names


def _reject_removed_hatago_override(raw: dict, manifest: Path) -> None:
    """The stack `hatago: {repo, ref}` override is REMOVED (bd harnessed-1t4.1).

    It shallow-cloned a fork and built it from source inside the derived image — a 410-package layer
    on every build, on top of the hatago the base image already installs. The fork is published, so
    the base image installs it directly and there is nothing left to override.

    Stack parsing is otherwise tolerant of unknown fields (D-14), which would silently turn a
    still-present block into a no-op. This is a build-input change the author must see, so it fails.
    """
    if raw.get("hatago") is None:
        return
    raise SchemaError(
        f"{manifest}: the 'hatago:' stack override has been removed — hatago is installed from "
        f"the published @drmikecrowe/hatago-mcp-hub npm release in "
        f"catalog/base/Dockerfile.harnessed-base (which carries per-server tool filtering). "
        f"Delete the 'hatago:' block from this stack."
    )


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
    Requires `name` and `image`, plus EITHER `port` (reached at host.containers.internal:<port>)
    OR `socket` (reached through a unix socket in the service's own data dir — no published port).

    `scope: global` (default) defaults `volume` to `<name>-data`. `scope: project` instead requires
    `data.persist`: the persist entry whose host dir becomes the service's data dir, so the service
    follows the owning recipe's placement (in_repo vs host) instead of a named volume.
    """
    manifest = _resolve_dir(root, "services", name) / "service.yaml"
    if not manifest.is_file():
        raise SchemaError(f"service manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    for field_name in ("name", "image"):
        if field_name not in raw:
            raise SchemaError(f"{manifest}: required field '{field_name}' is missing")

    scope = raw.get("scope", "global")
    if scope not in ("global", "project"):
        raise SchemaError(f"{manifest}: 'scope' must be 'global' or 'project', got {scope!r}")

    socket = raw.get("socket", "")
    if socket:
        if scope != "project":
            raise SchemaError(f"{manifest}: 'socket' requires scope: project (got {scope!r})")
        if Path(socket).is_absolute():
            raise SchemaError(
                f"{manifest}: 'socket' must be RELATIVE to the service data dir, got {socket!r}"
            )
    elif "port" not in raw:
        raise SchemaError(f"{manifest}: required field 'port' is missing (or set 'socket')")

    # A DECLARED port must still be valid (0 is not a "no port" spelling — omit the key, or set
    # `socket`). Only an omitted port yields 0, and only a socket-backed service may omit it.
    port = 0
    if "port" in raw:
        port = int(raw["port"])
        if not (1 <= port <= 65535):
            raise SchemaError(f"{manifest}: 'port' must be 1–65535, got {port}")

    data_persist = ((raw.get("data") or {}).get("persist") or "").strip()
    if scope == "project" and not data_persist:
        raise SchemaError(
            f"{manifest}: scope: project requires 'data.persist' — the persist entry whose host "
            "dir becomes this service's data dir"
        )
    if scope == "global" and data_persist:
        raise SchemaError(f"{manifest}: 'data.persist' requires scope: project")

    exclusive_lock = (raw.get("exclusive_lock") or "").strip()
    if exclusive_lock and scope != "project":
        raise SchemaError(f"{manifest}: 'exclusive_lock' requires scope: project")

    publish = (raw.get("publish") or "").strip()
    if publish and publish != "ephemeral":
        raise SchemaError(f"{manifest}: 'publish' must be 'ephemeral' if set, got {publish!r}")
    # No `publish and not port` check: a manifest with neither `port` nor `socket` is already
    # rejected above, and `publish` cannot be combined with `socket`, so an unported publish
    # cannot reach here.
    if publish and socket:
        raise SchemaError(
            f"{manifest}: 'publish' and 'socket' are mutually exclusive — a service is reached "
            "one way, so clients cannot disagree about which"
        )

    client_env = raw.get("client_env") or {}
    if not isinstance(client_env, dict):
        raise SchemaError(f"{manifest}: 'client_env' must be a mapping of NAME: template")
    _CLIENT_ENV_TOKENS = frozenset({"host", "port", "socket", "password"})
    for key, value in client_env.items():
        if not isinstance(value, str):
            raise SchemaError(f"{manifest}: client_env[{key!r}] must be a string")
        for token in re.findall(r"\{(\w+)\}", value):
            if token not in _CLIENT_ENV_TOKENS:
                raise SchemaError(
                    f"{manifest}: client_env[{key!r}] uses unknown token {{{token}}} "
                    f"(known: {', '.join(sorted(_CLIENT_ENV_TOKENS))})"
                )
        if "{socket}" in value and not socket:
            raise SchemaError(f"{manifest}: client_env[{key!r}] uses {{socket}} but none is declared")
        if ("{port}" in value or "{host}" in value) and socket:
            raise SchemaError(
                f"{manifest}: client_env[{key!r}] uses {{host}}/{{port}} on a socket-only service"
            )

    return ServiceDef(
        name=raw["name"],
        image=raw["image"],
        port=port,
        scope=scope,
        socket=socket,
        publish=publish,
        client_env=client_env,
        data_persist=data_persist,
        # A project-scoped service takes its data dir from `data.persist`, never a named volume.
        volume="" if scope == "project" else (raw.get("volume") or f"{name}-data"),
        healthcheck=raw.get("healthcheck", ""),
        exclusive_lock=exclusive_lock,
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
    recipes = [
        load_recipe(_resolve_dir(root, "recipes", ref), strict=strict, ref=ref) for ref in stack.recipes
    ]
    _check_recipe_conflicts(stack.name, recipes)
    return stack, recipes


def _check_recipe_conflicts(stack_name: str, recipes: list[Recipe]) -> None:
    """Fail loudly if two recipes in the same stack are incompatible.

    Two sources of incompatibility:

    * DECLARED — a recipe lists the other in its `conflicts:`. Checked symmetrically: only one side
      needs to declare it.
    * IMPLICIT — two varieties of the same recipe family (`beads/stealth` + `beads/team`). They are
      the same tool wired differently, so they are always mutually exclusive; no `conflicts:` entry
      needed (and none should be written — the family is the source of truth).
    """
    seen_family: dict[str, str] = {}
    for r in recipes:
        family, _, variety = r.ref.partition("/")
        if not variety:
            continue
        if family in seen_family:
            raise SchemaError(
                f"stack {stack_name!r} combines {seen_family[family]!r} and {r.ref!r}, which are two "
                f"varieties of the same recipe ({family!r}) — pick one for the stack's recipes list."
            )
        seen_family[family] = r.ref

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
# --- bd harnessed-1t4.6: a clone ref must be IMMUTABLE, not merely "not main" ---------------------
# `_FLOATING_REF_RE` names three refs explicitly, which let `--branch "feat/per-server-tool-filtering"`
# through a gate that exists to stop exactly that: a feature branch moves like main does, so two
# builds a week apart produce different images from identical inputs. The rule is therefore stated
# positively — a clone ref is acceptable only if it is a version-like TAG or a full 40-hex SHA.
_CLONE_REF_RE = re.compile(r'--branch(?:=|\s+)(?P<ref>"[^"]*"|\'[^\']*\'|\S+)')
# v6.0.3, 1.2.3, 0.1.2, v2.0.0-rc.1 — and a full commit SHA. Deliberately narrow: an unrecognised
# shape fails closed rather than being guessed at.
_IMMUTABLE_REF_RE = re.compile(r'^(?:[0-9a-fA-F]{40}|v?\d+(?:\.\d+)*(?:[-+.][0-9A-Za-z.]+)?)$')
# `"$FOO"` / `${FOO}` — catalog scripts pin via `FOO_REF="v6.0.3"` and clone `--branch "$FOO_REF"`,
# so the gate follows exactly one hop to the literal assignment in the same body.
_SHELL_VAR_REF_RE = re.compile(r'^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$')
# --- bd harnessed-po7: an ARCHIVE download is a clone by another spelling -------------------------
# `curl .../archive/main.tar.gz` moves exactly as much as `--branch main`, but `_CLONE_REF_RE` only
# ever looked at `--branch`, so a branch-pinned archive sailed through the gate that exists to stop
# it. Proven when the bead was filed: swapping a SHA for `archive/main.tar.gz` left every pin test
# green. codeload.github.com is the same download under another hostname AND is in the egress
# allowlist, so omitting it would leave a reachable bypass.
#   github.com/<o>/<r>/archive/[refs/heads/|refs/tags/]<ref>.tar.gz|.zip
#   codeload.github.com/<o>/<r>/(tarball|zipball|tar.gz|zip)/[refs/heads/|refs/tags/]<ref>
# A git archive at a 40-hex SHA is content-addressed, so requiring one is the pin AND a cheap
# integrity check.
# `{1,2}` on the owner/repo segments is load-bearing, not laxity: the catalog's own fetch writes
#   curl -fsSL "https://github.com/$1/archive/$2.tar.gz"
# where `$1` IS `owner/repo` — ONE textual segment. Requiring two literal segments made this gate
# miss the exact file the bug was reported against, which synthetic `o/r` fixtures never revealed.
_ARCHIVE_REF_RE = re.compile(
    r'(?:github\.com/(?:[^/\s"\']+/){1,2}archive/'
    r'|codeload\.github\.com/(?:[^/\s"\']+/){1,2}(?:tarball|zipball|tar\.gz|zip)/)'
    r'(?P<qualifier>refs/heads/|refs/tags/)?'
    r'(?P<ref>[^\s"\'|>?&]+?)'
    r'(?:\.tar\.gz|\.tgz|\.zip)?(?=$|[\s"\'|>?&])'
)
# `$1`/`${2}` — a shell FUNCTION PARAMETER. Unlike the clone gate, this is a PASS-THROUGH rather
# than a fail-closed rejection: the catalog's own correctly-pinned recipe reads
#   fetch() { curl "https://github.com/$1/archive/$2.tar.gz" ...; }
#   fetch oakoss/agent-skills "$OAKOSS_SHA" ...
# and the ref simply is not knowable from the URL line. Failing closed would reject a recipe that
# is pinned exactly right, so the literal case (the reported bug) is what this gate catches.
_POSITIONAL_PARAM_RE = re.compile(r'^\$\{?\d+\}?$')
_SHELL_ASSIGN_RE = re.compile(
    r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|\'[^\']*\'|\S*)\s*$', re.MULTILINE
)
# A Dockerfile RUN instruction. Used by `validate_container_only_declared` to detect the half of a
# partially migrated recipe that a host launch cannot execute.
_DOCKERFILE_RUN_RE = re.compile(r'^\s*RUN\s', re.MULTILINE)
# A bare DNS hostname: labels of alnum/hyphen joined by dots, a 2+ char alpha TLD, ≤253 chars.
# No scheme, path, port, or wildcard — the egress firewall resolves each to IPs via getent.
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
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


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _mutable_clone_ref(body: str) -> str | None:
    """Return a human-readable description of the first NON-immutable `--branch` ref, else None.

    Comment-stripping is the caller's job (both call sites already do it for `_FLOATING_REF_RE`).
    Fail-closed: a ref this cannot prove immutable — including a variable with no literal assignment
    in the same body — is reported, because "can't tell" and "moves" have the same build consequence.
    """
    assigns = {m.group(1): _unquote(m.group(2)) for m in _SHELL_ASSIGN_RE.finditer(body)}
    for match in _CLONE_REF_RE.finditer(body):
        raw = _unquote(match.group("ref"))
        var = _SHELL_VAR_REF_RE.match(raw)
        if var:
            name = var.group(1)
            if name not in assigns:
                return (
                    f"${name} (no literal assignment in this file, so the ref cannot be shown "
                    f"immutable)"
                )
            ref, shown = assigns[name], f"${name} = '{assigns[name]}'"
        else:
            ref, shown = raw, f"'{raw}'"
        if not _IMMUTABLE_REF_RE.match(ref):
            return shown
    return None


def _mutable_archive_ref(body: str) -> str | None:
    """Describe the first github/codeload ARCHIVE ref that cannot be shown immutable, else None.

    Same shape as `_mutable_clone_ref` — one-hop variable resolution against literal assignments in
    the same body — with one deliberate difference: a positional parameter passes through instead
    of failing closed. See `_POSITIONAL_PARAM_RE` for why.
    """
    assigns = {m.group(1): _unquote(m.group(2)) for m in _SHELL_ASSIGN_RE.finditer(body)}
    for match in _ARCHIVE_REF_RE.finditer(body):
        # `refs/tags/v1.2.3` is already self-describing as immutable-ish; `refs/heads/x` is a
        # branch by definition and must go through the same check as a bare ref.
        if match.group("qualifier") == "refs/tags/":
            continue
        raw = _unquote(match.group("ref"))
        if _POSITIONAL_PARAM_RE.match(raw):
            continue
        var = _SHELL_VAR_REF_RE.match(raw)
        if var:
            name = var.group(1)
            if name not in assigns:
                return (
                    f"${name} (no literal assignment in this file, so the ref cannot be shown "
                    "immutable)"
                )
            ref, shown = assigns[name], f"${name} = '{assigns[name]}'"
        else:
            ref, shown = raw, f"'{raw}'"
        if not _IMMUTABLE_REF_RE.match(ref):
            return shown
    return None


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
    ref = _mutable_clone_ref(stripped)
    if ref:
        raise PinValidationError(
            f"recipe '{recipe_name}': Dockerfile clones a moving ref {ref}. "
            "A branch moves — clone a tag (e.g. v1.2.3) or a full commit SHA instead."
        )
    ref = _mutable_archive_ref(stripped)
    if ref:
        raise PinValidationError(
            f"recipe '{recipe_name}': Dockerfile downloads a source archive at a moving ref {ref}. "
            "An archive URL pins nothing unless the ref does — use a full commit SHA (which also "
            "makes the download content-addressed) or a version tag."
        )


def validate_setup_script(recipe: Recipe) -> None:
    """Lint a recipe's `setup.script` FILE body (existence + npm/npx + floating refs).

    Without this the script is a hole in both existing gates: `validate_no_raw_npm` only ever sees
    strings (`_recipe_raw_strings` reads a fixed key list, so a script PATH tells it nothing) and
    `validate_pin` only ever sees Dockerfile bodies. A `curl … | bash` of an unpinned ref, or a raw
    `npm install`, would otherwise pass every check purely by living in a .sh file.
    """
    if not (recipe.setup and recipe.setup.script):
        return
    _lint_script_file(recipe, "setup.script", recipe.setup.script)


def _lint_script_file(recipe: Recipe, field_name: str, rel_path: str) -> None:
    """Existence + npm/npx + floating-ref gate over one catalog-authored .sh FILE body.

    Shared by `validate_setup_script` and `validate_install_script`: BOTH fields move shell commands
    out of strings/Dockerfiles and into a file, and a file is invisible to the two text-reading
    gates (`validate_no_raw_npm` reads a fixed key list; `validate_pin` reads Dockerfile bodies).
    Every new script-bearing field must route through here or pin enforcement silently stops for it.
    """
    path = recipe.root / rel_path
    if not path.is_file():
        raise RecipeLintError(
            f"recipe '{recipe.name}': {field_name} '{rel_path}' not found at {path}"
        )
    body = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    match = _RAW_NPM_RE.search(body)
    if match:
        token = match.group(0)
        raise RecipeLintError(
            f"recipe '{recipe.name}': {field_name} '{rel_path}' uses raw npm/npx token "
            f"'{token}'. Replace it with the pnpm equivalent '{_NPM_TO_PNPM.get(token, 'pnpm')}'."
        )
    match = _FLOATING_REF_RE.search(body)
    if match:
        raise PinValidationError(
            f"recipe '{recipe.name}': {field_name} '{rel_path}' contains a floating ref "
            f"'{match.group(0).strip()}'. Pin to an explicit tag, version, or SHA."
        )
    ref = _mutable_clone_ref(body)
    if ref:
        raise PinValidationError(
            f"recipe '{recipe.name}': {field_name} '{rel_path}' clones a moving ref {ref}. "
            "A branch moves — clone a tag (e.g. v1.2.3) or a full commit SHA instead."
        )
    ref = _mutable_archive_ref(body)
    if ref:
        raise PinValidationError(
            f"recipe '{recipe.name}': {field_name} '{rel_path}' downloads a source archive at a "
            f"moving ref {ref}. An archive URL pins nothing unless the ref does — use a full commit "
            "SHA (which also makes the download content-addressed) or a version tag."
        )


def validate_install_script(recipe: Recipe) -> None:
    """Lint a recipe's `install.script` FILE body — the same gate as `setup.script`.

    `install:` is the field that empties recipe Dockerfiles, so without this it would be the LARGEST
    hole in `validate_pin`: every `git clone --branch`, every version-pinned download that the pin
    gate exists to police moves out of the Dockerfile text and into a .sh the gate never reads.
    """
    if not (recipe.install and recipe.install.script):
        return
    _lint_script_file(recipe, "install.script", recipe.install.script)


def validate_no_claude_writes(recipe: Recipe, dockerfile_body: str) -> None:
    """Reject a recipe Dockerfile that touches `~/.claude` — content belongs in `install.script`.

    The launcher used to extract image-baked `~/.claude` content back out into the profile, because
    the profile bind-mount would otherwise hide it. That pass is gone (bd harnessed-8px.7): every
    content recipe now writes into `$HARNESSED_CONFIG_DIR` via `install:`, which lands in BOTH modes.

    Without this lint, deleting the extraction turns a Dockerfile `~/.claude` write into a SILENT
    content loss in container mode — the same shape as harnessed-8px.1, just with the modes swapped.
    A recipe that needs to deliver content has `install.script`; one that genuinely needs a
    container-only step declares `install.system`.
    """
    body = "\n".join(
        line for line in dockerfile_body.splitlines() if not line.lstrip().startswith("#")
    )
    if ".claude" not in body:
        return
    raise RecipeLintError(
        f"recipe '{recipe.name}': Dockerfile references '~/.claude'. Content delivered that way is "
        "invisible to a host launch AND hidden by the profile bind-mount in a container. Write it "
        "into \"$HARNESSED_CONFIG_DIR\" from install.script instead, which lands in both modes."
    )


def validate_container_only_declared(recipe: Recipe, dockerfile_body: str) -> None:
    """Reject a PARTIALLY migrated recipe that leaves a container-only `RUN` undeclared.

    `install:` moves a Dockerfile RUN body into a script BOTH modes run. A recipe may legitimately
    keep some RUNs behind — a root step, a global package install — but that means a host launch
    delivers LESS than the recipe promises. `install.system` is the reason string the launcher prints
    when it skips that half; without it the shortfall reaches the user as nothing at all, which is
    precisely how harnessed-8px.1 (14 missing skills, no error) happened. A comment in the recipe
    explaining the gap does not count: comments are invisible at runtime.

    Only recipes that HAVE an `install:` are gated. A recipe with no `install:` has not been migrated
    and is container-only by construction — there is no half-delivered state to mis-report.
    """
    if not recipe.install or recipe.install.system:
        return
    body = "\n".join(
        line for line in dockerfile_body.splitlines() if not line.lstrip().startswith("#")
    )
    match = _DOCKERFILE_RUN_RE.search(body)
    if not match:
        return
    raise RecipeLintError(
        f"recipe '{recipe.name}': Dockerfile still has a RUN step but 'install.system' is not set. "
        "A recipe with an 'install:' runs its script in both modes, so any RUN left in the "
        "Dockerfile is container-only and a host launch silently delivers less than the recipe "
        "promises. Set 'install.system' to a reason naming what a host launch does NOT get (it is "
        "printed verbatim at launch), or move the step into install.script so both modes get it."
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
