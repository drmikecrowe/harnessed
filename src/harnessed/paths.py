"""Single source of truth for host-side and container-side path resolution.

All profile dirs, instance names, project relpaths, and container-internal paths
are derived here. No caller computes these independently (fixes B6 scatter).

Profile location: $XDG_DATA_HOME/harnessed/profiles/<stack>/  (resolves B5 — keeps
the install clone as immutable source; profiles are DATA, not cache or throwaway).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

# Container home — the legible session-slug root (design §15 / D-06).
CONTAINER_HOME = Path("/home/harnessed")

# Default port the hatago hub listens on (design D-04).
HATAGO_PORT = 3535


def hatago_port() -> int:
    """The hatago hub port — honors the `HATAGO_PORT` env override, default `HATAGO_PORT`."""
    return int(os.environ.get("HATAGO_PORT", str(HATAGO_PORT)))


def hatago_endpoint() -> str:
    """hatago's single Streamable-HTTP endpoint inside the shared pod netns (design D-04)."""
    return f"http://localhost:{hatago_port()}/mcp"


def xdg_data_home() -> Path:
    """Return $XDG_DATA_HOME, defaulting to ~/.local/share."""
    xdg = os.environ.get("XDG_DATA_HOME", "")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def xdg_config_home() -> Path:
    """Return $XDG_CONFIG_HOME, defaulting to ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(xdg) if xdg else Path.home() / ".config"


def xdg_state_home() -> Path:
    """Return $XDG_STATE_HOME, defaulting to ~/.local/state."""
    xdg = os.environ.get("XDG_STATE_HOME", "")
    return Path(xdg) if xdg else Path.home() / ".local" / "state"


def repo_root() -> Path:
    """The installed source root (HARNESSED_DIR override, else the package's repo).

    src/harnessed/paths.py → parent(harnessed) → parent(src) → repo root.
    """
    env = os.environ.get("HARNESSED_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def user_catalog() -> Path:
    """The user's overlay catalog: $XDG_CONFIG_HOME/harnessed/catalog."""
    return xdg_config_home() / "harnessed" / "catalog"


def catalog_roots() -> list[Path]:
    """Catalog search roots in PRECEDENCE order (first wins on name clash).

    User catalog overlays the repo catalog: ~/.config/harnessed/catalog overrides the shipped
    catalog/ for any same-named agent/recipe/service/stack, and adds names the repo doesn't have.
    """
    roots: list[Path] = []
    uc = user_catalog()
    if uc.is_dir():
        roots.append(uc)
    roots.append(repo_root() / "catalog")
    return roots


def find_in_catalog(kind: str, name: str) -> Path:
    """Resolve catalog/<kind>/<name> across the catalog roots (user first); first existing wins.

    `kind` is the plural dir: agents | recipes | services | stacks. Returns the resolved directory
    even if absent (so the loader raises a clear not-found pointing at the highest-precedence root).
    """
    roots = catalog_roots()
    for r in roots:
        cand = r / kind / name
        if cand.exists():
            return cand
    return roots[0] / kind / name


def profiles_root() -> Path:
    """Root directory for all emitted stack profiles (XDG DATA)."""
    return xdg_data_home() / "harnessed" / "profiles"


def profile_dir(stack: str) -> Path:
    """Absolute host path to the assembled profile for `stack`."""
    return profiles_root() / stack


def is_built(stack: str) -> bool:
    """Return True if `stack` has an assembled profile (.mcp.json at root)."""
    return (profile_dir(stack) / ".mcp.json").is_file()


def project_hash(project_path: str | Path) -> str:
    """Stable 8-hex project key: sha1[:8] of the normalized project path.

    Single source for the per-project key used by BOTH `instance_name` and persist-dir
    resolution — no caller recomputes the digest independently, so the pod name and its
    persisted data can never drift apart on a trailing slash or symlink (the same
    `.rstrip("/")` normalization governs both).
    """
    p = str(Path(project_path)).rstrip("/")
    return hashlib.sha1(p.encode()).hexdigest()[:8]


def instance_name(stack: str, project_path: str | Path) -> str:
    """Stable instance name: harnessed-<stack>-<project_hash>."""
    return f"harnessed-{stack}-{project_hash(project_path)}"


def persist_root() -> Path:
    """Root for recipe-declared persistent data (XDG DATA).

    A sibling of `profiles_root()` under harnessed's data dir, in its own `persist/`
    namespace so a recipe name can never collide with `profiles/` or another top-level
    data dir. Bind mounts (not named volumes) live here — the host owns the bytes.
    """
    return xdg_data_home() / "harnessed" / "persist"


def git_common_dir(project_path: str | Path) -> Path | None:
    """Return the git common dir for project_path (shared across all worktrees), or None.

    Uses `git rev-parse --path-format=absolute --git-common-dir`. This is the same path
    for every worktree of a given checkout, so it is the correct key for cross-worktree
    persistence. Returns None for non-git directories or when git is not available.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        p = Path(result.stdout.strip())
        return p if p.exists() else None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def bare_worktree_container(project_path: str | Path) -> Path | None:
    """Parent directory of a bare repo's git-common-dir, if project_path sits inside a bare +
    linked-worktree checkout (e.g. `harnessed/.bare` + `harnessed/main`) — otherwise None.

    Same is-bare-repository check as `primary_worktree`. Used to auto-widen the launch mount to the
    directory containing the bare repo, so sibling worktrees are visible without an explicit
    `--mount-folder`. Returns None for an ordinary repo, a non-repo directory, or when git is
    unavailable — callers should fall back to project_path in all of those cases.
    """
    gcd = git_common_dir(project_path)
    if gcd is None:
        return None
    try:
        is_bare = subprocess.run(
            ["git", "--git-dir", str(gcd), "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() == "true"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return gcd.parent if is_bare else None


def primary_worktree(project_path: str | Path) -> Path:
    """The work tree that owns the repository's default branch — where a bare + linked-worktree
    checkout keeps its shared, repo-level `location: in_repo` data.

    HOST-side mirror of the container's `bd-resolve-beads-dir` (beads recipe): in a NORMAL repo this
    is just `project_path`; in a BARE + linked-worktree layout the git common dir is a bare repo with
    NO work tree, so an in-repo item (e.g. beads' `.beads/`) is anchored to the work tree checked out
    to the bare repo's default branch — NOT the (possibly feature) launch worktree. Keeps the
    host-side init marker aligned with where the container actually writes. Falls back to
    `project_path` when git is unavailable, the layout isn't bare, or no default-branch work tree
    exists.
    """
    gcd = git_common_dir(project_path)
    if gcd is None:
        return Path(project_path)
    try:
        if subprocess.run(
            ["git", "--git-dir", str(gcd), "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() != "true":
            return Path(project_path)
        head = subprocess.run(
            ["git", "--git-dir", str(gcd), "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "--git-dir", str(gcd), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path(project_path)
    # Porcelain blocks: "worktree <path>\nHEAD <sha>\nbranch refs/heads/<name>". Return the worktree
    # whose branch is the bare repo's default branch.
    target = f"refs/heads/{head}" if head else None
    current: str | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree ") :]
        elif target and line == f"branch {target}" and current:
            return Path(current)
    return Path(project_path)


def persist_workspace_dir(recipe: str, project_path: str | Path, name: str) -> Path:
    """Host dir for a workspace-scoped persist entry: persist/<recipe>/<workspace_hash>/<name>/.

    Keyed by the RESOLVED CURRENT PATH (per-worktree/per-branch). Two worktrees of the same
    git checkout get separate dirs under this scheme. For cross-worktree sharing, use
    persist_project_dir which keys on the git-common-dir instead.
    """
    return persist_root() / recipe / project_hash(project_path) / name


def persist_project_dir(recipe: str, project_path: str | Path, name: str) -> Path:
    """Host dir for a project-scoped persist entry: keyed by git-common-dir (cross-worktree).

    Two worktrees of the same git checkout resolve to the SAME host dir because they share the
    same git-common-dir. This is the right scope for tools whose state spans branches
    (e.g. a beads DB, a cross-branch notes dir).

    Falls back to the workspace hash (same result as persist_workspace_dir) when project_path is
    not inside a git repository — callers that warn on this fallback must check git_common_dir
    themselves.

    Keyed by BOTH recipe and project: two recipes that each declare an entry with the same name
    never share a dir, and the same recipe in two independent checkouts stays isolated.
    """
    gcd = git_common_dir(project_path)
    key_path: str | Path = gcd if gcd is not None else project_path
    return persist_root() / recipe / project_hash(key_path) / name


def persist_allowlist_path() -> Path:
    """User-owned allowlist gating `global:` persist mounts: $XDG_CONFIG_HOME/harnessed/persist-allowlist.

    Default-deny: a recipe's `global:` persist entry is only bind-mounted if its realpath is
    listed here (or nested under a listed dir). FORMAT — one host path per line; blank lines and
    lines beginning with `#` are comments. `~` and `$VARS` are expanded and the path is
    realpath-canonicalized before comparison, so a symlink or `..` cannot smuggle a path past the
    list. The file is USER-owned (lives in the user config dir, never the repo) so a recipe can
    never widen its own access — only the human running harnessed can. A handful of sensitive dirs
    (`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/harnessed`, and `$HOME` itself) are hard-denied
    REGARDLESS of this file.
    """
    return xdg_config_home() / "harnessed" / "persist-allowlist"


def extra_tools_path() -> Path:
    """User-owned list of extra mise tools baked into the base image: $XDG_CONFIG_HOME/harnessed/extra-tools.txt.

    One tool per line; blank lines and lines beginning with `#` are ignored. Seeded from the shipped
    `catalog/base/extra-tools.default.txt` on first build. USER-owned (config dir, never the repo) so
    a fresh clone or git worktree builds without carrying a user-local file, and edits never surface
    as repo diffs — same rationale as `persist_allowlist_path`. The base build stages a copy into the
    build context (`catalog/base/extra-tools.txt`, gitignored) for the Dockerfile COPY.
    """
    return xdg_config_home() / "harnessed" / "extra-tools.txt"


def corp_proxy_ca_path() -> Path:
    """User-owned corporate proxy CA bundle: $XDG_CONFIG_HOME/harnessed/corp-proxy-ca.crt.

    When present, harnessed passes it as a build secret to Dockerfile.harnessed-base so the
    base image can install it into the system trust store (update-ca-certificates). The file is
    user-local (config dir, never the repo) and may be populated via the `--corp-proxy-ca-crt` flag
    to `harnessed build`.
    """
    return xdg_config_home() / "harnessed" / "corp-proxy-ca.crt"


def project_relpath(project_path: str | Path) -> str:
    """Legible project relpath under host $HOME → mounted at CONTAINER_HOME/<relpath>."""
    p = Path(project_path)
    home = Path.home()
    try:
        return str(p.relative_to(home))
    except ValueError:
        return p.name


def container_project_path(project_path: str | Path) -> Path:
    """Container-side path for the project (path mirroring, MNT2-02)."""
    return Path(project_path)


def container_mcp_config() -> Path:
    """Container-side path to the harness .mcp.json (passed via --mcp-config)."""
    return CONTAINER_HOME / ".mcp.json"


def hatago_config_container() -> Path:
    """Container-side path to hatago.config.json."""
    return CONTAINER_HOME / "hatago.config.json"
