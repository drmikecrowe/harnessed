"""A stack as a Claude Code plugin in harnessed's own local marketplace (GH-649).

`emit_plugin(stack)` turns the stack's assembled claude profile into `<mkt>/plugins/<stack>` and
rewrites `<mkt>/.claude-plugin/marketplace.json`. `harnessed use` registers that marketplace with
the `claude` CLI and enables one plugin; plain `claude` then loads the stack against the real
`~/.claude`. Nothing here writes under `~/.claude`.

What a plugin carries: skills, commands, hooks and MCP servers. Rules and instructions have no
plugin component, so they are joined into `context.md` and printed by a SessionStart hook.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import hostrun, paths
from .emit import _recipe_hooks_settings
from .schema import load_stack_with_recipes

MARKETPLACE = "harnessed"
CONTEXT_HOOK = 'cat "${CLAUDE_PLUGIN_ROOT}/context.md"'
# `${CLAUDE_CONFIG_DIR:-<fallback>}` is how recipe hooks find the config dir on both backends.
_CONFIG_DIR_DEFAULT = re.compile(r"\$\{CLAUDE_CONFIG_DIR:-(?:[^{}]|\$\{[^{}]*\})*\}")
# `claude plugin validate --strict` fails a plugin.json without these three (GH-649 spike).
_MANIFEST = {"version": "0.0.0", "author": {"name": "harnessed"}}


def marketplace_dir() -> Path:
    """`$XDG_DATA_HOME/harnessed/marketplace`: anchored on XDG data, never on the cwd."""
    return paths.xdg_data_home() / "harnessed" / "marketplace"


def plugin_id(stack: str) -> str:
    return f"{stack}@{MARKETPLACE}"


def rewrite_hook_command(command: str) -> str:
    """Point a hook's config-dir path at the plugin root instead."""
    return _CONFIG_DIR_DEFAULT.sub("${CLAUDE_PLUGIN_ROOT}", command).replace(
        "CLAUDE_CONFIG_DIR", "CLAUDE_PLUGIN_ROOT"
    )


def plugin_hooks(stack: str, recipes, bin_dirs: list[Path], *, context: bool) -> dict:
    """The plugin's `hooks` block: the recipes' hooks for claude, rewritten, then the context hook.

    Built from the recipes, never from the profile's settings.json, which a host launch merges the
    user's own hooks and permissions into (agent decision A1).
    """
    prefix = f'PATH="{":".join(str(d) for d in bin_dirs)}:$PATH" ' if bin_dirs else ""
    hooks = _recipe_hooks_settings(recipes, "claude")
    for groups in hooks.values():
        for group in groups:
            for hook in group["hooks"]:
                hook["command"] = prefix + rewrite_hook_command(hook["command"])
    if context:
        hooks.setdefault("SessionStart", []).append(
            {"hooks": [{"type": "command", "command": CONTEXT_HOOK}]}
        )
    return hooks


def _context(claude_dir: Path) -> str:
    """Instructions, then each rule file in sorted relative-path order, joined by a blank line."""
    parts = []
    if (claude_dir / "CLAUDE.md").is_file():
        parts.append((claude_dir / "CLAUDE.md").read_text())
    rules = claude_dir / "rules"
    if rules.is_dir():
        parts += [p.read_text() for p in sorted(rules.rglob("*"), key=lambda p: p.relative_to(rules).as_posix())
                  if p.is_file()]
    return "".join(part.rstrip("\n") + "\n\n" for part in parts)[:-1]


def _mcp_servers(stack: str, bin_dirs: list[Path]) -> dict | None:
    """`hostrun._host_native_mcp`, with each stdio command resolved to its stack tool binary."""
    servers = hostrun._host_native_mcp(stack)
    if not servers:
        return None
    search = ":".join(str(d) for d in bin_dirs)
    for entry in servers.values():
        found = search and entry.get("command") and shutil.which(entry["command"], path=search)
        if found:
            entry["command"] = found
    return servers


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def emit_plugin(stack: str) -> Path:
    """Write `<mkt>/plugins/<stack>` from the stack's assembled claude profile, then the marketplace.

    The plugin dir is rebuilt from nothing, so a file gone from the profile is gone from the plugin.
    Copies follow symlinks, so the plugin holds bytes and never a link into another tree.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    claude_dir = paths.profile_dir(stack, "claude") / ".claude"
    bin_dirs = hostrun._host_tool_bin_dirs(stack)
    out = marketplace_dir() / "plugins" / stack
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for kind in ("skills", "commands"):
        if (claude_dir / kind).is_dir():
            shutil.copytree(claude_dir / kind, out / kind, symlinks=False)
    context = _context(claude_dir)
    if context:
        (out / "context.md").write_text(context)
    hooks = plugin_hooks(stack, recipes, bin_dirs, context=bool(context))
    if hooks:
        _write_json(out / "hooks" / "hooks.json", {"hooks": hooks})
    servers = _mcp_servers(stack, bin_dirs)
    if servers:
        _write_json(out / ".mcp.json", {"mcpServers": servers})
    _write_json(out / ".claude-plugin" / "plugin.json",
                {"name": stack, "description": f"harnessed stack {stack}", **_MANIFEST})
    write_marketplace()
    return out


def write_marketplace() -> Path:
    """`<mkt>/.claude-plugin/marketplace.json`, listing every emitted plugin under `<mkt>/plugins`."""
    plugins = sorted(m.parent.parent.name for m in (marketplace_dir() / "plugins").glob("*/.claude-plugin/plugin.json"))
    path = marketplace_dir() / ".claude-plugin" / "marketplace.json"
    _write_json(path, {
        "name": MARKETPLACE,
        "owner": {"name": "harnessed"},
        "metadata": {"description": "Stacks built by harnessed"},
        "plugins": [{"name": name, "source": f"./plugins/{name}"} for name in plugins],
    })
    return path
