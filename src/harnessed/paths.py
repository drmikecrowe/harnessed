"""Single source of truth for host-side and container-side path resolution.

All profile dirs, instance names, project relpaths, and container-internal paths
are derived here. No caller computes these independently (fixes B6 scatter).

Profile location: $XDG_DATA_HOME/harnessed/profiles/<stack>/  (resolves B5 — keeps
the install clone as immutable source; profiles are DATA, not cache or throwaway).
"""

from __future__ import annotations

import hashlib
import os
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


def persist_project_dir(recipe: str, project_path: str | Path, name: str) -> Path:
    """Host dir for a project-scoped persist entry: persist/<recipe>/<project_hash>/<name>/.

    Keyed by BOTH recipe and project: two recipes that each declare `project: [name]`
    never share a dir, and the same recipe in two different projects stays isolated.
    """
    return persist_root() / recipe / project_hash(project_path) / name


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
