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

_yaml = YAML(typ="safe", pure=True)

# Harness → config directory name (Claude Code canonical, design §8). One harness per stack.
HARNESS_CONFIG_DIR = {
    "claude": ".claude",
}


class SchemaError(Exception):
    """A recipe/stack manifest is missing a required field or is malformed."""


class RecipeLintError(SchemaError):
    """A recipe uses raw npm/npx instead of the pnpm equivalent (BLD-03 supply-chain lint)."""


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
class Recipe:
    name: str
    description: str = ""
    servers: list[McpServer] = field(default_factory=list)
    skills: list[FileExt] = field(default_factory=list)
    commands: list[FileExt] = field(default_factory=list)
    root: Path = field(default_factory=Path)  # the recipe dir (for resolving relative paths)
    raw: dict = field(default_factory=dict)


@dataclass
class Stack:
    name: str
    config: str = "isolated"
    harness: str = "claude"
    recipes: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    permissions: str | None = None
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

    A service is its OWN image/container/volume on `harnessed-net`, with a lifecycle
    independent of any instance. A recipe references it via `mcp.servers[].service`;
    the assembler resolves the service name → a hatago URL-proxy entry pointing at
    `http://<name>:<port>/mcp` (plan 04-01 Task 4).
    """

    name: str
    image: str
    port: int
    volume: str = ""
    healthcheck: str = ""
    raw: dict = field(default_factory=dict)


def _parse_servers(raw_mcp: dict) -> list[McpServer]:
    servers: list[McpServer] = []
    for entry in (raw_mcp or {}).get("servers", []) or []:
        if "name" not in entry:
            raise SchemaError(f"mcp server entry missing 'name': {entry!r}")
        servers.append(
            McpServer(
                name=entry["name"],
                command=entry.get("command"),
                args=list(entry.get("args", []) or []),
                transport=entry.get("transport", "stdio"),
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


def load_recipe(recipe_dir: Path) -> Recipe:
    recipe_dir = Path(recipe_dir)
    manifest = recipe_dir / "recipe.yaml"
    if not manifest.is_file():
        raise SchemaError(f"recipe manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    if "name" not in raw:
        raise SchemaError(f"{manifest}: required field 'name' is missing")
    return Recipe(
        name=raw["name"],
        description=raw.get("description", ""),
        servers=_parse_servers(raw.get("mcp", {}) or {}),
        skills=_parse_fileext(raw.get("skills")),
        commands=_parse_fileext(raw.get("commands")),
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
    return Stack(
        name=raw["name"],
        config=raw.get("config", "isolated"),
        harness=raw.get("harness", "claude"),
        recipes=list(raw.get("recipes", []) or []),
        services=list(raw.get("services", []) or []),
        permissions=raw.get("permissions"),
        state=dict(raw.get("state", {}) or {}),
        raw=raw,
    )


def load_service(root: Path, name: str) -> ServiceDef:
    """Load services/<name>/service.yaml under `root` (mirrors load_recipe/load_stack).

    Requires `name`, `image`, and `port`; defaults `volume` to `<name>-data`. Raises
    SchemaError on a missing file or required field (same fail-fast shape as load_recipe).
    Reusable by the assembler to resolve a `service:`-referenced MCP server → its port.
    """
    root = Path(root)
    manifest = root / "services" / name / "service.yaml"
    if not manifest.is_file():
        raise SchemaError(f"service manifest not found: {manifest}")
    raw = _load_yaml(manifest)
    for field_name in ("name", "image", "port"):
        if field_name not in raw:
            raise SchemaError(f"{manifest}: required field '{field_name}' is missing")
    return ServiceDef(
        name=raw["name"],
        image=raw["image"],
        port=int(raw["port"]),
        volume=raw.get("volume") or f"{name}-data",
        healthcheck=raw.get("healthcheck", ""),
        raw=raw,
    )


def load_stack_with_recipes(root: Path, stack_name: str) -> tuple[Stack, list[Recipe]]:
    """Load a stack and every recipe it references, resolved under `root`.

    `root` is the directory holding `stacks/` and `recipes/` (the repo root or the
    mounted build dir). Reusable by the capability test (plan 02-03).
    """
    root = Path(root)
    stack = load_stack(root / "stacks" / stack_name)
    recipes = [load_recipe(root / "recipes" / name) for name in stack.recipes]
    return stack, recipes


# --- BLD-03: raw npm/npx recipe lint (RESEARCH Pattern 3 / Code §7) -----------------------------
# Word-boundaried COMMAND tokens only — a package named like `npmlog` must NOT match (Pitfall 4).
_RAW_NPM_RE = re.compile(r"\bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b")
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


@dataclass
class Capabilities:
    """What a stack's running instance is expected to expose — the test oracle (§18)."""

    mcp_servers: list[str]
    skills: list[str]
    commands: list[str]


def expected_capabilities(stack: Stack, recipes: list[Recipe]) -> Capabilities:
    """Derive the declared capabilities from the manifest (plan 02-03 reuses this)."""
    mcp: list[str] = []
    skills: list[str] = []
    commands: list[str] = []
    for recipe in recipes:
        mcp.extend(s.name for s in recipe.servers)
        skills.extend(s.name for s in recipe.skills)
        commands.extend(c.name for c in recipe.commands)
    return Capabilities(mcp_servers=mcp, skills=skills, commands=commands)
