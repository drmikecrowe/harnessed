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


