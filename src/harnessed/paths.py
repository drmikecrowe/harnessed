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


def instance_name(stack: str, project_path: str | Path) -> str:
    """Stable instance name: harnessed-<stack>-<sha1[:8] of project_path>."""
    p = str(Path(project_path)).rstrip("/")
    h = hashlib.sha1(p.encode()).hexdigest()[:8]
    return f"harnessed-{stack}-{h}"


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
