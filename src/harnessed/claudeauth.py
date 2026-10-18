"""One Claude login per machine, refreshed by the host alone (GH-597).

`~/.claude/.credentials.json` (the host store) is the only file that holds the refresh token. Every
host stack home and every container pod gets a VIEW of it: the same `claudeAiOauth` without
`refreshToken`. Measured against Claude Code 2.1.299 in the GH-597 spike (2026-10-18):

  * a view serves model requests and remote control, and claude never refreshes or rewrites it,
    even after `expiresAt` has passed;
  * a running session that gets a 401 re-reads the file, replaced or rewritten in place, and
    recovers on its next request;
  * a holder WITH a refresh token refreshes in the last minutes before expiry by REPLACING the file.
    That turned every symlinked stack home into a private copy (#556), and it left each pod copy on
    a refresh token another holder had already rotated away (#597).

So the host store is refreshed by claude itself, against its own config dir, and `sync` copies the
result into every view. `python -m harnessed.claudeauth` is the refresher: it keeps the host login
alive with no claude session open, and re-syncs whenever the host store changes.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import paths
from .hosthome import (
    _credentials_are_usable,
    _host_claude_config_override,
    _host_claude_source,
    _host_oauth_token_configured,
    _rescue_host_credentials,
)

#: The keys only the host store may hold. A view without them can never refresh.
_REFRESH_KEYS = ("refreshToken", "refreshTokenExpiresAt")

# claude refreshes only in the last minutes before expiry. The spike saw it refresh with 115 s left,
# so a pass that fires inside this lead is known to land inside claude's window.
_REFRESH_LEAD_S = 110
_TICK_S = 60
_REFRESH_TIMEOUT_S = 120
_REFRESH_BACKOFF_S = 300


def host_store() -> Path:
    """The one credentials file that holds the refresh token."""
    return _host_claude_source() / ".credentials.json"


def _state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "harnessed"


def pod_view_path(inst: str) -> Path:
    """The host file bind-mounted over a claude pod's `~/.claude/.credentials.json`."""
    return _state_root() / inst / "credentials.json"


def access_view(store: Path) -> dict | None:
    """The host login without its refresh token, or None when the store holds no usable login."""
    if not _credentials_are_usable(store):
        return None
    # The usability check also accepts a bare token object; claude itself always nests it.
    try:  # a second read: a refresh or logout may have replaced or removed the store since
        oauth = json.loads(store.read_text(encoding="utf-8")).get("claudeAiOauth")
    except (OSError, ValueError):
        return None
    if not isinstance(oauth, dict):
        return None
    return {k: v for k, v in oauth.items() if k not in _REFRESH_KEYS}


def _merged(text: str | None, view: dict) -> dict | None:
    """`text`'s JSON with its login set to `view`, or None when it already holds `view`."""
    data: dict = {}
    if text:
        try:
            loaded = json.loads(text)
        except ValueError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    if data.get("claudeAiOauth") == view:
        return None
    data["claudeAiOauth"] = view
    return data


def write_view(path: Path, view: dict, *, in_place: bool) -> bool:
    """Set `path`'s login to `view`, keeping its other keys (claude stores `mcpOAuth` here too).

    `in_place` is for pod files: a single-file bind mount pins the inode, so a replace on the host
    would leave the pod reading the old file. A host home's file is replaced atomically instead,
    which also turns a pre-GH-597 symlink into a regular file without writing through it.
    Returns True when the file changed.
    """
    if in_place:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            # Read, merge and write under one lock: the refresher and a launch can both sync, and
            # a merge read before the lock would drop keys the other writer just stored.
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = _merged(os.read(fd, os.fstat(fd).st_size or 1).decode("utf-8", "replace"), view)
            if data is None:
                return False
            # Raw writes over the old bytes, then trim: never an empty file, and one write(2) for a
            # body this small, so a pod reading mid-write sees the old or the new login. A crash
            # between write and trim leaves a torn file; it fails to parse, so the next sync
            # rewrites it.
            raw = json.dumps(data).encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            written = 0
            while written < len(raw):
                written += os.write(fd, raw[written:])
            os.ftruncate(fd, len(raw))
        finally:
            os.close(fd)
        return True
    text = None
    if path.is_file() and not path.is_symlink():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = None
    data = _merged(text, view)
    if data is None:
        return False
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def _host_views() -> list[Path]:
    """Every host stack home's credentials file. Same depths as `_rescue_host_credentials`."""
    root = paths.host_homes_root()
    if not root.is_dir():
        return []
    return [*root.glob("*/*/*/.credentials.json"), *root.glob("*/*/.credentials.json")]


def _pod_views() -> list[Path]:
    """Every pod's view. An isolated-auth login lives one level deeper and is never matched."""
    root = _state_root()
    return sorted(root.glob("*/credentials.json")) if root.is_dir() else []


def sync() -> None:
    """Promote a newer login a stack holds, then write the host login into every view.

    A `/login` inside a host stack writes a full pair into that stack's file; the rescue promotes it
    to the host store before this overwrites it. Pod files are never promoted: a pod's sign-in
    (`container-acp --cli`) already writes the host store.
    """
    # Under a token nothing reads these files; the host side refuses to maintain them too.
    if _host_oauth_token_configured():
        return
    _rescue_host_credentials()
    view = access_view(host_store())
    if view is None:
        return
    for p in _host_views():
        write_view(p, view, in_place=False)
    for p in _pod_views():
        write_view(p, view, in_place=True)


def _expires_at(store: Path) -> float:
    try:
        return json.loads(store.read_text(encoding="utf-8"))["claudeAiOauth"]["expiresAt"] / 1000
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def refresh_host(store: Path) -> None:
    """Have claude refresh the host store: one minimal request, which claude precedes with a refresh
    once the login is inside its expiry window. Run against the host store's own config dir, so
    claude's refresh lock also serialises it with the user's plain `claude` sessions.
    """
    claude = shutil.which("claude")
    if claude is None:
        print("claude not on PATH; cannot refresh the host login", flush=True)
        return
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    # Unset means ~/.claude. Setting it to ~/.claude instead would move `.claude.json` into that dir.
    override = _host_claude_config_override()
    if override is None:
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(override)
    with tempfile.TemporaryDirectory() as cwd:
        # Project settings only, from an empty dir: no user hooks, MCP servers or plugins start.
        proc = subprocess.run(
            [claude, "-p", "--model", "haiku", "--no-session-persistence", "--strict-mcp-config",
             "--setting-sources", "project", "Reply with: ok"],
            cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=_REFRESH_TIMEOUT_S, check=False,
        )
    state = "refresh ran" if proc.returncode == 0 else f"claude exited {proc.returncode}"
    print(f"{state}; host login expires at {time.ctime(_expires_at(store))}", flush=True)


_last_refresh = 0.0


def tick() -> None:
    """One refresher pass: refresh the host login when it is about to expire, then sync."""
    global _last_refresh
    if _host_oauth_token_configured():
        return
    store = host_store()
    due = access_view(store) is not None and _expires_at(store) - time.time() < _REFRESH_LEAD_S
    # A login whose refresh keeps failing needs a /login; retrying every tick would only spam.
    if due and time.time() - _last_refresh > _REFRESH_BACKOFF_S:
        _last_refresh = time.time()
        refresh_host(store)
    sync()


def _lock_path() -> Path:
    return _state_root() / "claude-auth-refresher.lock"


def start_refresher() -> None:
    """Start the refresher unless one already runs. It is detached: it outlives the launch that
    started it, and the next launch after a reboot starts it again."""
    # Nothing to refresh. Also keeps a test that runs the CLI in a subprocess, out of reach of
    # conftest's stub, from leaving a refresher idling in a deleted tmp home.
    if access_view(host_store()) is None:
        return
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return  # a refresher holds the lock
    # The child inherits the locked fd, so the lock is never free between this check and the
    # child: a concurrent launch cannot start a second refresher.
    try:
        with (lock.parent / "claude-auth-refresher.log").open("a") as log:
            subprocess.Popen(
                [sys.executable, "-m", "harnessed.claudeauth", str(fd)], pass_fds=(fd,),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
    finally:
        os.close(fd)


def main() -> None:
    if len(sys.argv) > 1:
        fd = int(sys.argv[1])  # inherited from `start_refresher`, already locked
    else:
        lock = _lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return  # a refresher already runs
    print(f"refresher started, pid {os.getpid()}", flush=True)
    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 — one bad pass must not end the only refresher
            print(f"refresher pass failed: {exc!r}", flush=True)
        time.sleep(_TICK_S)


if __name__ == "__main__":
    main()
