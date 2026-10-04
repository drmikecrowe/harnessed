"""Merge JSON settings without losing what the user already had.

Harness settings files are co-owned: harnessed needs certain keys present, and the user's own file
must survive that. A blind overwrite loses their config; a blind skip loses ours. These two do the
recursive merge that keeps both, and are separated from the callers that decide WHAT to merge.
"""
from __future__ import annotations

import json

from pathlib import Path

from . import emit
from .console import _out


def _deep_merge_json(base: object, overlay: object) -> object:
    """Recursively merge two JSON-like trees, preferring values from `overlay`.

    Dicts merge by key (recurse on matching keys). Non-dicts (including lists/scalars) are
    replaced wholesale by `overlay` so host-authored arrays preserve order exactly.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, val in overlay.items():
            if key in out:
                out[key] = _deep_merge_json(out[key], val)
            else:
                out[key] = val
        return out
    return overlay


# The permission lists Claude Code itself appends to when a user answers a prompt in a stack.
_LIVE_PERMISSION_LISTS = ("allow", "deny", "ask", "additionalDirectories")


def carry_live_permissions(merged: dict, live: object) -> dict:
    """Union the live file's `permissions` lists back into a profile-wins `merged` (#538).

    Both relaunch paths rebuild settings.json from the profile, and the profile always defines
    `permissions`, so a rule written only into the live file ("Don't ask again") was replaced on
    every launch. Each list keeps the profile's entries first, then appends live entries it lacks.
    Scalars such as `defaultMode` are untouched: the profile still wins on those.
    """
    live_perms = live.get("permissions") if isinstance(live, dict) else None
    if not isinstance(live_perms, dict):
        return merged
    perms = merged.get("permissions")
    if not isinstance(perms, dict):
        return merged
    out = dict(perms)
    for key in _LIVE_PERMISSION_LISTS:
        extra = live_perms.get(key)
        if not isinstance(extra, list):
            continue
        current = out.get(key)
        base = list(current) if isinstance(current, list) else []
        out[key] = base + [e for e in extra if e not in base]
    return {**merged, "permissions": out}


def _merge_host_claude_settings(prof: Path, required: dict, harness: str = "") -> None:
    """Apply host ~/.claude/settings.json into the profile settings for launch-time parity.

    The profile's settings.json is the file mounted into the container. Merge host preferences into
    that file at launch, then re-apply harnessed-required grants/hooks so host customizations do not
    disable the MCP hub.
    """
    host = Path.home() / ".claude" / "settings.json"
    target = prof / "settings.json"
    if not (host.is_file() and target.is_file()):
        return

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ settings:[/yellow] {msg}")

    try:
        target_raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        target_raw = {}
    target_obj = target_raw if isinstance(target_raw, dict) else {}

    try:
        host_text = host.read_text(encoding="utf-8")
    except OSError:
        return
    host_obj = emit.read_baked_settings(host_text, warn=_warn)
    if host_obj is None:
        return

    # `statusLine.command` is a host-absolute path (e.g. /home/<hostuser>/.local/share/mise/shims/…)
    # that can never resolve inside the container (home is /home/harnessed). Letting the host's
    # version win here would point Claude Code's status line at a nonexistent binary → it silently
    # renders nothing. Drop it so the container-correct value survives.
    #
    # That value is NOT in the profile: bd harnessed-8px.21.4 moved `install:` off build-time image
    # layers, so the ccstatusline recipe's install.sh now writes statusLine into the per-stack config
    # VOLUME at container runtime. The profile never carries the key at all — which is why
    # `volumes._merged_settings_text` merges the profile into the volume instead of copying over it.
    host_obj.pop("statusLine", None)

    merged = _deep_merge_json(target_obj, host_obj)
    if not isinstance(merged, dict):
        merged = host_obj
    final = emit.merge_settings(merged, required, warn=_warn)
    target.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    if harness:
        emit.warn_duplicate_hooks(final, harness, warn=_warn)
