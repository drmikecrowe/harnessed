"""The last launch configuration for a project, so `--last` can replay it.

Replaces the `[tasks.<harness>]` half of `mise.local.toml` (bd harnessed-7mt). That table existed to
give the aoe dashboard row a STABLE command to invoke — `mise run <harness> --` names only the
harness, so a launch flag could change without re-keying every existing row (see
`aoe.command_for`'s note on identity). The flags lived in the task body, inside the user's repo.

Here the flags live in harnessed's own state directory instead, and the stable command becomes
`harnessed <verb>-run <harness> --last --`. Same property, one writer and one reader, both inside
harnessed, and nothing written into anybody's repo.

KEYED PER WORKTREE, deliberately NOT per checkout — and deliberately NOT the same key the project
tool env uses.

The two want opposite things. `project_env_path` keys on `git_common_dir` because every worktree of
a checkout needs the SAME tools; sharing is the point. "What did I last launch here" is the
opposite: worktrees routinely run different stacks, which is what worktrees are for. Sharing that
key lets a launch in one worktree silently become the replay target in another — `--last` in the
worktree you are standing in starts what you ran somewhere else, and reports success.

It was briefly keyed on `git_common_dir` on the theory that per-worktree keying multiplies aoe rows.
It does not: rows are keyed by (command, path) and a worktree launch already records its own path,
so the row count is identical either way. The keying decides only WHICH stack `--last` replays.

Falls back to the given path when there is no git dir, which for this key is not really a fallback —
a non-git directory is its own worktree by definition.

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
    """The record for a WORKTREE. `project_hash` normalizes, so `/p` and `/p/` agree.

    The project path itself, NOT `paths.git_common_dir` — see the module docstring. Sibling
    worktrees of one checkout get separate records, because they routinely run different stacks and
    replaying the wrong one is silent.
    """
    return paths.xdg_state_home() / "harnessed" / "last-run" / f"{paths.project_hash(project_path)}.json"


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
        # Restricted at creation, not only after — see the same call in
        # `setupenv._write_project_tool_env` for why a 0755 window matters even briefly.
        store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        store.parent.chmod(0o700)
        data = _read(store)
        data["version"] = _VERSION
        data["path"] = str(project_path)
        data.setdefault("runs", {})[_key(verb, harness)] = entry
        # Whole-file rewrite through a temp sibling: two launches racing in one project must not
        # leave a half-written record that reads as "no record" on the next --last.
        #
        # Not a full lock. Two launches with DIFFERENT (verb, harness) keys can still race
        # read-modify-write and lose one entry — the loser's next `--last` reports "nothing to
        # replay", which is loud and recoverable by launching explicitly once. A lock is not worth
        # it for a file whose worst failure is one re-typed command.
        #
        # chmod BEFORE the write and on the TEMP file: `replace()` keeps the source's mode, so
        # chmod-ing after the rename would leave a window at the umask default, and chmod-ing the
        # destination would not touch what we actually wrote. The 0700 parent already bars other
        # users; this is the same defence-in-depth `_write_project_tool_env` gives its dotenv.
        tmp = store.with_suffix(".json.tmp")
        tmp.touch(mode=0o600, exist_ok=True)
        tmp.chmod(0o600)
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
    # `runs` is checked too, not just the envelope. `load` does `.get("runs", {}).get(...)`, so a
    # same-version file holding a non-dict — `{"version": 1, "runs": []}` — would raise
    # AttributeError out of a function whose contract is "a corrupt record reads as absent", and
    # turn `--last` into a traceback. Anything unexpected here means "no record", never a crash.
    if not isinstance(data.get("runs", {}), dict):
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
