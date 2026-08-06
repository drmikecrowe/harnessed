"""The last launch configuration for a project, so `--last` can replay it.

Replaces the `[tasks.<harness>]` half of `mise.local.toml` (bd harnessed-7mt). That table existed to
give the aoe dashboard row a STABLE command to invoke — `mise run <harness> --` names only the
harness, so a launch flag could change without re-keying every existing row (see
`aoe.command_for`'s note on identity). The flags lived in the task body, inside the user's repo.

Here the flags live in harnessed's own state directory instead, and the stable command becomes
`harnessed <verb>-run <harness> --last --`. Same property, one writer and one reader, both inside
harnessed, and nothing written into anybody's repo.

KEYED PER WORKTREE, deliberately NOT per checkout. `paths.git_common_dir` is the right key for the
project TOOL ENV — every worktree of a repo wants the same tools — and its docstring says so. It is
the wrong key for "what did I last launch here": worktrees routinely run different stacks, and
sharing the key would let a launch in one worktree become the replay target in another. That is the
stale-replay failure this feature has to avoid, not cause.

NEVER FATAL ON WRITE. A launch that got as far as recording state has already done the useful work;
losing the shortcut is not worth killing it. Read failures are loud, because a `--last` that cannot
find its record must say so rather than silently launch a baseline (see `launcher._resolve_last`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import paths

# Bumped when a recorded field changes meaning. An unknown version is treated as no record at all:
# replaying a launch we cannot fully understand is exactly the silent-wrong-stack failure mode.
_VERSION = 1


def _store(project_path: Path) -> Path:
    """The record for a project. `project_hash` normalizes the path, so `/p` and `/p/` agree."""
    return (
        paths.xdg_state_home() / "harnessed" / "last-run"
        / f"{paths.project_hash(project_path)}.json"
    )


def _key(verb: str, harness: str) -> str:
    """One record file per project, one entry per (verb, harness).

    `host-run claude` and `container-run claude` in the same folder are different launches with
    different backends, and the aoe row names both — so replay has to distinguish them too.
    """
    return f"{verb}/{harness}"


def record(
    verb: str, stack: str, harness: str, project_path: Path,
    *, group: Optional[str] = None, title: Optional[str] = None, no_strict_mcp: bool = False,
) -> None:
    """Store what `--last` needs to reproduce this launch. Never raises.

    The RESOLVED stack name, never the user's original argv — a dynamic `--recipe` set is minted
    before this is reached, so recording `stack` replays it exactly. Same canonical form
    `aoe.command_for` records, for the same reason.

    NOT recorded: `--fresh`, `--rm`, and the other per-invocation lifecycle flags. They describe
    what you want THIS time, not what the stack is, and the existing design deliberately keeps them
    out of the replay command. Adding them here would make a replay quietly destructive.
    """
    project_path = Path(project_path).resolve()
    entry = {
        "stack": stack,
        "no_strict_mcp": bool(no_strict_mcp),
        "aoe_group": group,
        "aoe_title": title,
    }
    try:
        store = _store(project_path)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.parent.chmod(0o700)
        data = _read(store)
        data["version"] = _VERSION
        data["path"] = str(project_path)
        data.setdefault("runs", {})[_key(verb, harness)] = entry
        # Whole-file rewrite through a temp sibling: two launches racing in one project must not
        # leave a half-written record that reads as "no record" on the next --last.
        tmp = store.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(store)
    except OSError:
        return


def _read(store: Path) -> dict:
    """The record as a dict, or an empty one. A corrupt or foreign file is treated as absent."""
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != _VERSION:
        return {}
    return data


def load(verb: str, harness: str, project_path: Path) -> Optional[dict]:
    """The recorded launch for this (project, verb, harness), or None.

    None means "nothing to replay" and the caller MUST fail loudly on it. Returning a default here
    would turn `--last` in a fresh folder into a silent baseline launch — the wrong-stack-at-exit-0
    class this whole design exists to stay out of.
    """
    entry = _read(_store(Path(project_path).resolve())).get("runs", {}).get(_key(verb, harness))
    if not isinstance(entry, dict) or not entry.get("stack"):
        return None
    return entry
