"""Materialize and maintain the per-stack HOME for a host-native launch.

Container mode mounts a profile over the harness's config dir. Host mode has nothing to mount over,
so the profile has to be laid down as a real directory tree — and then kept honest across launches:
stale content cleared when the stack's fingerprint changes, daemon/runtime state preserved rather
than wiped, live session history shared back up to the user's real home, and credentials REFERENCED
rather than copied (ARCHITECTURE.md §Constraints).

Pure filesystem derivation from a profile plus a home path. Nothing here launches an agent.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .__init__ import __version__
from .assemble import compute_recipe_hash
from .console import _err


_OAUTH_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105 — variable name, not a hardcoded credential


def _host_stack_fingerprint(stack: str, recipes: list) -> str:
    """What the host config dir's content is a function of: the stack's recipe closure, plus
    harnessed's own version.

    The version is in there because a host launch has no image build to force a refresh. Change what
    `emit` writes into settings.json and the recipe closure is byte-identical, so without the version
    every existing config dir would keep serving the old output forever.
    """
    stack_dir = paths.find_in_catalog("stacks", stack)
    return f"{__version__}:{compute_recipe_hash(stack_dir / 'stack.yaml', recipes)}"


# Written INSIDE the config dir, deliberately: the stamp must die with the content it describes, so
# a hand-deleted or half-written dir reads as "no fingerprint" and rebuilds rather than being trusted.
_HOST_STACK_FINGERPRINT = ".harnessed-stack"


# `<project_hash>` dirs from the pre-8px.12 layout, now nested inside the config dir itself.
_LEGACY_PROJECT_DIR_RE = re.compile(r"^[0-9a-f]{8}$")


def _migrate_legacy_host_homes(home: Path) -> None:
    """Scrub pre-8px.12 per-project config dirs that are now nested INSIDE the config dir.

    The old key was `<stack>/<harness>/<project_hash>`; the new config dir IS `<stack>/<harness>`, so
    every old per-project dir became a child of it. They must be SCRUBBED rather than swept away by
    the rmtree below: after bd harnessed-8px.10 any of them that saw a token refresh holds a real
    `.credentials.json`, and a bare rmtree would leave that token recoverable on disk.

    Matched narrowly — an 8-hex name AND something that actually looks like a config dir — so a
    recipe that ever ships an 8-hex-named directory is not silently deleted.
    """
    if not home.is_dir():
        return
    for child in sorted(home.iterdir()):
        if not (child.is_dir() and not child.is_symlink()):
            continue
        if not _LEGACY_PROJECT_DIR_RE.match(child.name):
            continue
        if not ((child / "settings.json").is_file() or (child / ".credentials.json").exists()):
            continue  # 8-hex name but not a config dir — leave it alone
        _err.print(
            f"[blue][INFO][/blue] Migrating away a pre-8px.12 per-project config dir "
            f"({child.name}); its credential file is scrubbed, not just unlinked."
        )
        _scrub_host_home(child)


@contextmanager
def _host_home_lock(home: Path) -> Generator[None, None, None]:
    """Serialize fingerprint-check + wipe + rebuild + install for one (stack, harness).

    The window this closes is narrow by construction: with the wipe gated on the fingerprint
    (bd harnessed-8px.12), an unchanged stack never rebuilds, so two launches only contend when both
    observe a CHANGED fingerprint. Compare the behaviour it replaces, where every launch was
    destructive and a second launch could wipe a running session's config dir outright.

    Held across the installs too, not just the materialize: releasing after the rebuild would let a
    second launch see a matching stamp, skip installs, and exec the agent while the first launch's
    install scripts were still writing into the same dir.

    The lock file is a SIBLING of the config dir — anything inside it dies in the rmtree.
    `<harness>.lock` is a file, so host-gc's `is_dir()` scan skips it.
    """
    lock_path = home.parent / f"{home.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


# Files Claude Code's daemon keeps in its per-project state dir. Presence of ANY of these marks a
# directory as live daemon state rather than recipe content.
_DAEMON_STATE_MARKERS = (
    "daemon.json", "daemon.log", "daemon-auth-status.json", "daemon-auth-cooldown",
)


def _is_daemon_state(entry: Path) -> bool:
    """True when `entry` is Claude Code's own daemon/runtime state, which a rebuild must NOT delete.

    Identified by CONTENT, not by name. The daemon's per-project state dirs are opaque 8-hex-char
    keys (`51ba83b8`, `d8551d86`); matching that shape would be guesswork, and a recipe is free to
    ship a directory with any name. A directory holding `daemon.json`/`daemon.log`/`daemon-auth-*`
    is unambiguously the daemon's.
    """
    if not entry.is_dir() or entry.is_symlink():
        return False
    if entry.name == "daemon":
        return True
    return any((entry / marker).exists() for marker in _DAEMON_STATE_MARKERS)


def _clear_host_home_except_runtime(home: Path) -> None:
    """Empty the config dir the way the wholesale rmtree did — but spare live daemon state.

    bd harnessed-8px.20. `_materialize_host_home` used to `shutil.rmtree(home)`. That is right for
    RECIPE CONTENT: the wipe is what stops a recipe dropped from the stack leaving files behind
    (8px.12). It is wrong for Claude Code's own runtime state, which lives in the same directory and
    belongs to a process that may be RUNNING.

    Observed (2026-07-21): a rebuild deleted `daemon.json`/`daemon.log` out from under a daemon alive
    13h53m. ~200ms after losing its state the daemon wrote `{"status":"auth_required"}` and the
    credential file was gutted; the orphaned daemon then held `control.sock` with nothing valid
    behind it, so the next launch timed out reaching the background service. One rmtree, both bugs.

    Selective deletion rather than move-aside-and-restore: an interrupted rebuild can then never
    strand the preserved state somewhere the next launch will not look for it.
    """
    for entry in home.iterdir():
        if _is_daemon_state(entry):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()  # covers files AND symlinks (never follow one into ~/.claude)


def _materialize_host_home(prof: Path, home: Path, *, fingerprint: str | None = None) -> bool:
    """Copy the assembled profile's CONTENT layer into a host CLAUDE_CONFIG_DIR (`home`).

    Content-only: the `.claude/*` tree (skills/commands/rules/agents + CLAUDE.md) plus the
    settings.json floor — exactly what the container bind-mounts onto ~/.claude, minus the
    container-only artifacts (.mcp.json, hatago.config.json, the derived Dockerfile) which wire the
    MCP hub that does not exist host-side.

    Returns True if it (re)built, False if an up-to-date home was left untouched.

    GATED on `fingerprint` (bd harnessed-8px.12). The rebuild is still WHOLESALE — the dir stays a
    pure function of (profile + installs), so a recipe removed from the stack still cannot leave
    files behind — but it now happens only when the stack actually changed, instead of on every
    launch. That wipe-every-time was the root of three separate problems: it forced the project into
    the config-dir key (to stop one launch wiping another's live dir), it made install scripts re-run
    per project per launch (with `install.cache` existing purely to make that affordable), and it
    reset `.claude.json` — so MCP approvals and folder trust never persisted.

    Passing `fingerprint=None` keeps the old unconditional-rebuild behaviour, which is what the
    materialize-only tests want.
    """
    if fingerprint is not None:
        stamp = home / _HOST_STACK_FINGERPRINT
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    # BEFORE the rmtree: it would delete a legacy per-project dir without scrubbing its credential.
    _migrate_legacy_host_homes(home)
    if home.exists():
        _clear_host_home_except_runtime(home)
    home.mkdir(parents=True, exist_ok=True)
    src_claude = prof / ".claude"
    if src_claude.is_dir():
        # Contents of .claude/ become the config-dir root: .claude/skills -> <home>/skills, etc.
        shutil.copytree(src_claude, home, dirs_exist_ok=True)
    settings = prof / "settings.json"
    if settings.is_file():
        shutil.copy2(settings, home / "settings.json")
    return True


def _stamp_host_home(home: Path, fingerprint: str) -> None:
    """Record the fingerprint — the LAST step of a successful build, after the installs.

    Deliberately NOT written by `_materialize_host_home`: the content it certifies is not complete
    until every `install.script` has run. Stamping at the end of the copy instead meant a FAILED
    install left a matching stamp behind, so the next launch saw "unchanged", skipped both the
    rebuild and the installs, and started the agent against a permanently half-installed stack —
    silently. Seen for real: a host launch died on context-mode's install with the stamp already on
    disk (bd harnessed-8px.15).
    """
    (home / _HOST_STACK_FINGERPRINT).write_text(fingerprint + "\n", encoding="utf-8")


def _host_claude_source() -> Path:
    """The host's live claude config dir — source for auth seeding. Honors a CLAUDE_CONFIG_DIR the
    host may already run under; else the ~/.claude default."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


# Session-state subdirs SHARED with the real ~/.claude — the host analog of the container's
# bind-mounts (projects/file-history/tasks/session-env/todos), plus shell-snapshots.
_HOST_SHARED_STATE = ("projects", "file-history", "todos", "tasks", "session-env", "shell-snapshots")


def _relink(link: Path, target: Path) -> None:
    """Point `link` at `target`, replacing whatever is there (a prior symlink, file, or dir)."""
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(target)


def _scrub_host_home(home: Path) -> None:
    """Remove a host config dir, overwriting any real .credentials.json before deletion.

    Overwrites the credential file with null bytes and fsync's before unlinking, then removes the
    entire directory tree. This reduces the window in which a stranded token is recoverable from
    disk. LIMITATION: on SSDs with wear-leveling firmware the controller may have already remapped
    the underlying flash blocks, so overwrite does not guarantee physical erasure — it is better
    than a bare unlink and is the level of assurance available without raw device access.
    """
    cred = home / ".credentials.json"
    if cred.is_file() and not cred.is_symlink():
        size = max(cred.stat().st_size, 1)
        with cred.open("r+b") as fh:
            fh.write(b"\x00" * size)
            fh.flush()
            os.fsync(fh.fileno())
        cred.unlink()
    shutil.rmtree(home)


def _credentials_are_usable(path: Path) -> bool:
    """True when this credentials file actually holds a token worth propagating.

    Observed failure (real logout, 2026-07-21): `~/.claude/.credentials.json` and a stack home both
    held a GUTTED credential — the envelope intact (scopes, subscriptionType, rateLimitTier,
    refreshTokenExpiresAt) but `accessToken` and `refreshToken` empty strings and `expiresAt` 0.
    `_rescue_host_credentials` promoted it anyway, because its only guard was mtime: an emptied file
    that happens to be NEWEST overwrites a perfectly good shared token, and every stack sourcing
    from shared is then logged out. One stack going empty poisoned all of them.

    So freshness is necessary but NOT sufficient — a credential must also be usable. Unreadable or
    unparseable counts as unusable: this gate only ever decides whether to COPY a file over a
    working one, so refusing on doubt costs nothing and prevents exactly the poisoning above.

    Deliberately NOT checked: whether `expiresAt` is in the future. An expired ACCESS token is the
    normal, healthy state of a credential whose refresh token is still good — that is the case the
    whole refresh mechanism exists to serve. Rejecting it would throw away the token we most need to
    keep. Only a MISSING/EMPTY token or a zeroed expiry marks the gutted file.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    oauth = data.get("claudeAiOauth", data)
    if not isinstance(oauth, dict):
        return False
    if not (oauth.get("accessToken") or "").strip():
        return False
    if not (oauth.get("refreshToken") or "").strip():
        return False
    # expiresAt 0 accompanied the gutted file; a real credential always carries a real stamp.
    return bool(oauth.get("expiresAt"))


def _host_oauth_token_configured() -> bool:
    """True when a `CLAUDE_CODE_OAUTH_TOKEN` will reach the host agent, so the credentials file is
    dead weight and must not be maintained, shared or rescued.

    `os.environ` alone is sufficient HERE.  The container twin
    `_claude_oauth_token_configured` calls `_varlock_resolve` directly for the
    same reason this function only reads `os.environ`: both check the authoritative
    structured source rather than scanning a serialised file.  `_launch_host`
    applies `_resolve_launch_env` (varlock / `.env`) to this process at
    launcher.py:5209 BEFORE `_host_launch_plan` runs, so any token from those
    sources is already in `os.environ` by the time the credential wiring fires.
    Keep that ordering if either function moves.

    Empty is NOT configured — `export CLAUDE_CODE_OAUTH_TOKEN=` is how a shell profile turns it off,
    and reading the bare name as "configured" would retire a load-bearing credential file and log
    the user out with no way back.
    """
    return bool(os.environ.get(_OAUTH_TOKEN_VAR))


def _rescue_host_credentials() -> None:
    """Promote the newest refreshed token found in ANY host home into the shared `~/.claude` copy.

    Must run BEFORE `_materialize_host_home`, which `shutil.rmtree`s the home being launched —
    otherwise that home's copy of the token is deleted before it can be rescued.

    Scans EVERY home, not just the one being launched, because a config dir is keyed
    `<stack>/<harness>/<project>`: one stack open in three projects has three of them. Rescuing only
    the launching home would converge lazily — a token refreshed in project A would not reach the
    shared copy until project A itself relaunched, so launching project B first would still restore
    a stale token and force a login. Scanning all of them is what makes "one login everywhere" true
    across stacks and projects rather than only within one.

    `_share_host_claude_state` symlinks `home/.credentials.json` at the real `~/.claude` one so a
    refresh propagates and one login serves everywhere. That holds only while the symlink survives.
    Claude Code rewrites this file on token refresh, and the rewrite REPLACES the symlink with a
    regular file: the refreshed token lands in the stack's config dir and the shared copy never sees
    it. The next launch then wipes the config dir and re-links to the now-stale shared copy — so the
    user is logged out roughly every time the token would have refreshed (bd harnessed-8px.10).

    Evidence it is a replace and not a write-through: the shared file's mtime stayed hours behind the
    per-stack regular files that had superseded it.

    So: if the symlink is gone and what replaced it is NEWER than the shared copy, copy it back
    before the wipe. Self-healing — no exit hook, which matters because `_launch_host` hands the
    process to `os.execvpe` and never regains control.
    """
    # Under a token nothing reads this file, so promoting a copy is pure downside: the rescue exists
    # to keep a credential alive, and its worst failure mode is writing a bad candidate over the
    # user's real login. Skip it rather than run it for a file the harness ignores.
    if _host_oauth_token_configured():
        return
    root = paths.host_homes_root()
    if not root.is_dir():
        return
    # Explicit depths, never `**`: a config dir contains SYMLINKED state dirs (projects/, tasks/, …)
    # pointing back into ~/.claude, and a recursive walk risks following them out of the tree.
    # `*/*/*` is the current <stack>/<harness>/<project> layout; `*/*` catches pre-project-keying
    # homes still on disk.
    newest: Path | None = None
    for cand in (*root.glob("*/*/*/.credentials.json"), *root.glob("*/*/.credentials.json")):
        # A surviving symlink means that home's refresh propagated live — it IS the shared copy.
        if cand.is_symlink() or not cand.is_file():
            continue
        # Freshness alone is not enough: a GUTTED credential (empty tokens, expiresAt 0) is often
        # the newest file on disk, and promoting it overwrites a working shared token and logs
        # every other stack out. Never let one become the winner.
        if not _credentials_are_usable(cand):
            continue
        if newest is None or cand.stat().st_mtime > newest.stat().st_mtime:
            newest = cand
    if newest is None:
        return
    real = _host_claude_source() / ".credentials.json"
    # A shared copy that is already gutted must be HEALED even though it is newer — that is exactly
    # the state a previous poisoning leaves behind, and the mtime guard alone would preserve it
    # forever while every stack that sources from it starts logged out.
    if real.is_file() and _credentials_are_usable(real):
        if real.stat().st_mtime >= newest.stat().st_mtime:
            return  # shared copy is usable AND at least as fresh — never move a token backwards
    real.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(newest, real)
    real.chmod(0o600)


def _share_host_claude_state(home: Path) -> None:
    """Wire the stack home to the real ~/.claude for the pieces that should be SHARED — the host
    analog of the container's bind-mounts:
      * session state (projects/file-history/todos/tasks/session-env/shell-snapshots) → SYMLINKED, so
        transcripts, todos, and resumable sessions persist and also show up in your normal claude;
      * the auth token (.credentials.json) → SYMLINKED, so a refresh in either place propagates —
        one login everywhere, no stale copy.
    The account snapshot (.claude.json) is COPIED (skips onboarding) so the stack's own writes don't
    leak back into your global claude state. Config (skills/commands/rules/agents/CLAUDE.md/settings/
    .mcp.json) stays isolated per-stack (copied from the profile by _materialize_host_home)."""
    real = _host_claude_source()
    if real.resolve() == home.resolve():
        return
    real.mkdir(parents=True, exist_ok=True)
    for name in _HOST_SHARED_STATE:
        src = real / name
        src.mkdir(parents=True, exist_ok=True)  # ensure it exists so the symlink resolves
        _relink(home / name, src)
    # A configured CLAUDE_CODE_OAUTH_TOKEN takes precedence over the credentials file, so linking one
    # in maintains state nothing reads — while carrying the entire 8px.10 failure mode, because a
    # refresh replaces the symlink with a regular file and the next launch restores a stale copy.
    # The container path has refused to mount a credential file under a token since it was added
    # (`_claude_creds_seed_mount`); this is the host's missing half.
    #
    # Retire a copy an earlier no-token launch left behind, or the stale file this gate exists to
    # eliminate simply outlives the switch. ONLY the per-stack copy: `real` is the user's own login,
    # outside any stack, and deleting it would log them out of plain `claude` too.
    cred = real / ".credentials.json"
    stack_cred = home / ".credentials.json"
    if _host_oauth_token_configured():
        if stack_cred.is_symlink() or stack_cred.exists():
            stack_cred.unlink(missing_ok=True)
    elif cred.exists():
        _relink(stack_cred, cred)  # live token, shared
    # .claude.json (account/onboarding) lives NEXT TO the config dir, not inside it: at
    # $CLAUDE_CONFIG_DIR/.claude.json when that's set, else $HOME/.claude.json — NOT ~/.claude/.claude.json.
    env_ccd = os.environ.get("CLAUDE_CONFIG_DIR")
    acct = (Path(env_ccd) if env_ccd else Path.home()) / ".claude.json"
    if acct.is_file():
        shutil.copy2(acct, home / ".claude.json")  # snapshot account → skips onboarding, isolated writes


def _propagate_host_settings(profile_settings: Path, live: Path) -> None:
    """Write the freshly-computed profile settings.json over the live one WITHOUT dropping keys an
    install script wrote into it.

    Resolves a collision between two gates. `install:` scripts write into $HARNESSED_CONFIG_DIR —
    the LIVE home, not the profile — e.g. ccstatusline's `statusLine` block. Those installs are
    skipped when the stack fingerprint matches (bd harnessed-8px.12), while settings.json is
    re-propagated on every launch (bd harnessed-8px.18). A plain copy therefore deleted the
    installer's output with nothing left to put it back: the status line survived the first launch
    after a stack change and vanished on every restart after it.

    Profile keys always WIN — that is 8px.18's whole point (the host's live ~/.claude preferences
    and harnessed's required grants are recomputed each launch). ONLY keys the profile does not
    define at all are carried over. This is the host-side analogue of `emit.merge_settings` carrying
    every non-required baked key through verbatim container-side.
    """
    try:
        fresh = json.loads(profile_settings.read_text() or "{}")
        prior = json.loads(live.read_text() or "{}") if live.is_file() else {}
    except (OSError, ValueError):
        # Unparseable/unreadable on either side → fall back to the plain copy. A settings file the
        # user hand-edited into invalid JSON must not take the whole launch down with it.
        shutil.copy2(profile_settings, live)
        return
    carried = (
        {k: v for k, v in prior.items() if k not in fresh}
        if isinstance(fresh, dict) and isinstance(prior, dict)
        else {}
    )
    if not carried:
        shutil.copy2(profile_settings, live)  # nothing to preserve → byte-identical propagation
        return
    live.write_text(json.dumps({**fresh, **carried}, indent=2) + "\n")
