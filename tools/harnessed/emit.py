"""Write the assembled artifacts into the mounted build dir (EMIT ONLY).

Pure file emission — no podman/docker, no daemon. Everything is written under
`profiles/<stack>/` inside the build dir:

  profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/   the fanned tree
  profiles/<stack>/.claude/.mcp.json                               single hatago endpoint
  profiles/<stack>/hatago.config.json                              hatago child-server config
  profiles/<stack>/baked-servers.json                              servers the hatago image must bake

The profile is regenerated from scratch on every run so the committed tree is a pure
function of the recipes/stack (reproducible build).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .schema import McpServer, Recipe, Stack

# hatago's single Streamable-HTTP endpoint (design D-04; default port 3535). The harness
# `.mcp.json` points ONLY here — never at a stdio server directly.
HATAGO_PORT = 3535
HATAGO_ENDPOINT = f"http://localhost:{HATAGO_PORT}/mcp"
HATAGO_MCP_KEY = "hatago"

# The harness-native subdirs the assembler manages (Claude-canonical, design §4b/§7).
PROFILE_SUBDIRS = ("skills", "commands", "agents", "hooks", "rules")


def reset_profile(profile_dir: Path) -> None:
    """Wipe and recreate the profile dir so emission is fully reproducible."""
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True)


def ensure_profile_tree(harness_dir: Path) -> None:
    """Create the harness-native subdir skeleton (forward-compat for all extension kinds)."""
    for sub in PROFILE_SUBDIRS:
        (harness_dir / sub).mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_mcp_json(harness_dir: Path) -> Path:
    """Emit the harness `.mcp.json` — exactly ONE entry pointing at the hatago endpoint.

    `type: http` is REQUIRED — Claude Code only treats an entry as a Streamable-HTTP server
    when the type is set; without it the server is not loaded. The launcher passes this file
    via `claude --mcp-config <file> --strict-mcp-config`, so hatago is the ONLY MCP server the
    isolated harness sees (no host/project/account-synced servers leak in).
    """
    out = harness_dir / ".mcp.json"
    _write_json(out, {"mcpServers": {HATAGO_MCP_KEY: {"type": "http", "url": HATAGO_ENDPOINT}}})
    return out


def write_settings_json(harness_dir: Path, servers: list[McpServer]) -> Path:
    """Emit `.claude/settings.json` — pre-approve the hatago hub's MCP tools.

    Without this, an interactive isolated session prompts for permission the first time it uses an
    MCP tool, so a skill that drives (e.g.) the time server appears to "fail". The server-level
    wildcard `mcp__<hub>` allows every tool hatago exposes — the hub's child tool names are only
    known at runtime, so the hub-level grant is the static, assembler-knowable permission.
    """
    settings: dict = {}
    if servers:
        settings["permissions"] = {"allow": [f"mcp__{HATAGO_MCP_KEY}"]}
    out = harness_dir / "settings.json"
    _write_json(out, settings)
    return out


def _hatago_entry(server: McpServer) -> dict:
    """Map an MCP server to a hatago `mcpServers` entry (schema per hatago docs)."""
    if server.is_stdio_child:
        entry: dict = {"command": server.command, "args": list(server.args)}
        if server.env:
            entry["env"] = dict(server.env)
        return entry
    # Network-native server: hatago proxies it by URL (transport http/sse).
    entry = {"url": server.url, "type": server.transport}
    if server.headers:
        entry["headers"] = dict(server.headers)
    return entry


def write_hatago_config(profile_dir: Path, servers: list[McpServer]) -> Path:
    """Emit hatago.config.json declaring each server as a hatago child/proxy."""
    out = profile_dir / "hatago.config.json"
    _write_json(
        out,
        {
            "version": 1,
            "logLevel": "info",
            "mcpServers": {s.name: _hatago_entry(s) for s in servers},
        },
    )
    return out


def write_derived_dockerfile(profile_dir: Path, stack: Stack, recipes: list[Recipe]) -> Path:
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
            and not ln.strip().upper().startswith("ARG HARNESS")
        ]
        lines.append(f"# --- recipe: {recipe.name} ---")
        lines.extend(filtered)
        lines.append("")

    out = profile_dir / f"Dockerfile.harnessed-{stack.name}"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_baked_manifest(profile_dir: Path, stack: Stack, baked: list[McpServer]) -> Path:
    """Emit the manifest of stdio servers the hatago image must bake (base/Dockerfile.hatago)."""
    out = profile_dir / "baked-servers.json"
    _write_json(
        out,
        {
            "stack": stack.name,
            "servers": [
                {
                    "name": s.name,
                    "command": s.command,
                    "args": list(s.args),
                    "transport": s.transport,
                }
                for s in baked
            ],
        },
    )
    return out
