"""Single source of truth for host-side and container-side path resolution.

All profile dirs, instance names, project relpaths, and container-internal paths
are derived here. No caller computes these independently (fixes B6 scatter).

Profile location: $XDG_DATA_HOME/harnessed/profiles/<stack>/  (resolves B5 — keeps
the install clone as immutable source; profiles are DATA, not cache or throwaway).
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

class HomeNotFoundError(RuntimeError):
    """harnessed's catalog could not be located — see `harnessed_home`."""


# Container home — the legible session-slug root (design §15 / D-06).
CONTAINER_HOME = Path("/home/harnessed")

# The uid/gid the `harnessed` user is baked as in every image (catalog/base/Dockerfile.harnessed-base,
# catalog/services/*/Dockerfile — ubuntu:24.04 ships its `ubuntu` user at 1000 and the images keep it).
CONTAINER_UID = 1000
CONTAINER_GID = 1000

# THE userns argument, for every `podman run` / `pod create` harnessed issues.
#
# Bare `--userns=keep-id` maps the invoking host uid to the SAME NUMBER inside the container, while
# the container process is the image's uid 1000. So a bind-mounted host dir is writable from inside
# only when the invoking user *happens to be* uid 1000 — true on many dev boxes, false on a GitHub
# `ubuntu-latest` runner, where `live.yml` failed six runs in a row with
#     mkdir: cannot create directory '/data/dolt': Permission denied
# (bd harnessed-rv2.1).
#
# Pinning the mapping to the image's uid makes the container's uid-1000 process BE the invoking host
# user whatever that user's host uid is, so ownership stops depending on a numeric coincidence. It is
# a no-op where the host uid is already 1000, which is why it cannot regress those boxes.
USERNS_ARG = f"--userns=keep-id:uid={CONTAINER_UID},gid={CONTAINER_GID}"


def pod_host_uid() -> int | None:
    """The HOST uid the pod's process writes as, or None when the mapping does not determine it.

    A bind-mounted host dir is writable from inside the pod exactly when it is owned by this uid, so
    this is the number every ownership check must compare against (`persist.guard_ownership`).

    Read off `USERNS_ARG` rather than assumed. `guard_ownership` exists so that a wrong assumption
    about the mapping surfaces as a named pre-launch error rather than a silent EACCES deep inside a
    container — and a guard that assumes the mapping is correct cannot catch the mapping being
    wrong. That circularity is why the guard passed on six consecutive red CI runs while
    `mkdir -p /data/dolt` failed inside the beads-server sidecar (bd harnessed-rv2.1).

      keep-id pinned to CONTAINER_UID → the invoking user IS the pod's uid-1000 process → os.getuid()
      host                            → no user namespace, so container CONTAINER_UID IS host CONTAINER_UID
      anything else                   → None

    **None means UNRESOLVED, and callers must refuse rather than guess.** An earlier version
    answered `CONTAINER_UID` here and called it fail-safe. It is not (CodeRabbit): under bare
    `keep-id` on a host whose user is 1001, podman maps host 1001 → container 1001 and the image's
    uid 1000 is drawn from the SUBUID range, so the pod's writes land as ~100999 on the host, not as
    1000. Answering "1000" would ACCEPT a persist dir owned by host uid 1000 that the pod cannot
    write — fail-OPEN, in precisely the state the original bug produces.

    SCOPE: this reasons about the DECLARED argument only. It cannot observe what podman actually
    did — a rootful daemon or a missing subuid range still yields a silent EACCES, and only the
    runner's `podman info --format '{{.Host.IDMappings}}'` (bd harnessed-rv2.3) shows that.
    """
    if USERNS_ARG == "--userns=host":
        return CONTAINER_UID
    if not USERNS_ARG.startswith("--userns=keep-id"):
        return None
    mapped = re.search(r"\buid=(\d+)", USERNS_ARG)
    if mapped and int(mapped.group(1)) == CONTAINER_UID:
        return os.getuid()
    return None


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


def xdg_cache_home() -> Path:
    """Return $XDG_CACHE_HOME, defaulting to ~/.cache."""
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    return Path(xdg) if xdg else Path.home() / ".cache"


def install_cache_dir(recipe_name: str, cache_key: str) -> Path:
    """Content cache for one recipe's `install.script`, keyed by its PINNED ref.

    Host installs re-run on EVERY launch — `_materialize_host_home` rmtree's the home each time, so
    their output cannot survive and a first-launch-only gate would leave the home permanently empty.
    Re-cloning per launch is the price unless the SOURCE is cached, and caching is only safe with a
    key that never moves — which the repo's pin policy already guarantees (`_parse_install` rejects
    floating keys). Cache MISS = this directory does not exist; the script populates it and copies
    out of it. Bumping the recipe's pin yields a new directory, so an upgrade can never read stale
    content.
    """
    return xdg_cache_home() / "harnessed" / "install" / recipe_name / cache_key


def harnessed_home() -> Path:
    """harnessed's home: the directory that CONTAINS `catalog/`. Never derived from the CWD.

    This is the single anchor for BOTH catalog lookup and the podman build context, so
    `harnessed build <stack>` behaves identically from any working directory.

    Resolution:
      1. `$HARNESSED_DIR` — explicit override (unchanged; still wins).
      2. The catalog shipped WITH the package, at `<pkg>/catalog`. In an installed wheel that is a
         real directory (packaged via `[tool.setuptools.package-data]`). In a source checkout it is
         a symlink to the repo-root `catalog/`, which is the authoring surface.

    `.resolve()` collapses either form to a REAL directory, so home is the repo root in a checkout
    and `site-packages/harnessed` in a wheel — and the build context never contains a symlink that
    escapes it (podman rejects those). The Dockerfiles' context-relative `COPY catalog/base/...`
    paths are therefore correct in both cases, unchanged.

    Raises when no catalog can be found, rather than returning a plausible-looking directory that
    has none — that used to surface as a baffling "unknown stack '<x>'" for every stack.
    """
    env = os.environ.get("HARNESSED_DIR")
    if env:
        return Path(env)
    catalog = Path(__file__).resolve().parent / "catalog"
    if not catalog.exists():
        raise HomeNotFoundError(
            "cannot locate harnessed's catalog: expected it alongside the installed package at "
            f"{catalog} (a real directory in a wheel; a symlink to the repo-root catalog/ in a "
            "source checkout). Reinstall harnessed, or set HARNESSED_DIR to the directory that "
            "contains catalog/."
        )
    return catalog.resolve().parent


def source_checkout() -> Path | None:
    """`harnessed_home()` when it is a harnessed SOURCE CHECKOUT, else None.

    Dev-only conveniences (the `catalog/<kind>.local` overlay symlinks, the `docs/` wiki clone)
    are meaningful only in a checkout. Gating them here keeps them from firing against whatever
    directory the user happened to `cd` into — and, in an installed wheel, from writing into
    `site-packages`.
    """
    home = harnessed_home()
    if (home / "pyproject.toml").is_file() and (home / "src" / "harnessed").is_dir():
        return home
    return None


def user_catalog() -> Path:
    """The user's overlay catalog: $XDG_CONFIG_HOME/harnessed/catalog."""
    return xdg_config_home() / "harnessed" / "catalog"


def local_links_dir(checkout: Path) -> Path:
    """Where the DX overlay symlinks live in a source checkout: `<checkout>/catalog-local/`.

    DELIBERATELY OUTSIDE `catalog/`. `catalog/` is shipped inside the wheel, and setuptools follows
    symlinks — so a `<kind>.local` symlink parked inside it would package the user's PRIVATE overlay
    (~/.config/harnessed/catalog/...) into a distributable artifact. Keeping the host-local symlinks
    in a sibling directory makes that structurally impossible rather than merely excluded.
    """
    return checkout / "catalog-local"


def catalog_roots() -> list[Path]:
    """Catalog search roots in PRECEDENCE order (first wins on name clash).

    User catalog overlays the repo catalog: ~/.config/harnessed/catalog overrides the shipped
    catalog/ for any same-named agent/recipe/service/stack, and adds names the repo doesn't have.

    The generated-stack root (`generated_catalog_root`) is LAST: a machine-minted stack must never
    shadow one you authored under the same name. It is included only when it exists, so a user who
    has never run `harnessed run` gets exactly the previous two roots.
    """
    roots: list[Path] = []
    uc = user_catalog()
    if uc.is_dir():
        roots.append(uc)
    roots.append(harnessed_home() / "catalog")
    gen = generated_catalog_root()
    if gen.is_dir():
        roots.append(gen)
    return roots


def catalog_relpath(name: str) -> Path:
    """Map a catalog ref to its on-disk path under catalog/<kind>/.

    A ref may name a VARIETY of a recipe family: `beads/stealth` is the `stealth` variety of the
    `beads` family, living at catalog/recipes/beads/stealth/. The ref IS the relative path — a
    family is exactly one dir deep, and each variety is a complete, self-contained recipe (its own
    recipe.yaml + Dockerfile + tests/).

    Refs without a slash (every agent/service/stack, and an unfamilied recipe) map to themselves.
    Validated, not merely joined: an empty or traversing component would escape the catalog root.
    """
    parts = name.split("/")
    if len(parts) > 2:
        raise ValueError(f"invalid catalog ref {name!r}: a family is one level deep (<family>/<variety>)")
    if any(not p or p in (".", "..") for p in parts):
        raise ValueError(f"invalid catalog ref {name!r}: empty or traversing path component")
    return Path(*parts)


def find_in_catalog(kind: str, name: str) -> Path:
    """Resolve catalog/<kind>/<name> across the catalog roots (user first); first existing wins.

    `kind` is the plural dir: agents | recipes | services | stacks. `name` may be a variety
    ref (see `catalog_relpath`). Returns the resolved directory even if absent (so the loader raises
    a clear not-found pointing at the highest-precedence root).
    """
    rel = catalog_relpath(name)
    roots = catalog_roots()
    for r in roots:
        cand = r / kind / rel
        if cand.exists():
            return cand
    return roots[0] / kind / rel


def overlay_shadowed_repo_path(kind: str, name: str) -> Path | None:
    """The repo-catalog path a user-overlay entry shadows; None when nothing is shadowed.

    Shadowed means BOTH copies exist: `user_catalog()/<kind>/<relpath>` AND
    `harnessed_home()/catalog/<kind>/<relpath>`. On a name clash the overlay wins (see
    `catalog_roots`), so the repo copy is never read — a session then quietly assembles stale
    overlay content while the newer repo copy sits unused. That silent drift has already caused
    real regressions, which is why the loader warns on it. `name` may be a variety ref (see
    `catalog_relpath`).
    """
    rel = catalog_relpath(name)
    repo = harnessed_home() / "catalog" / kind / rel
    if (user_catalog() / kind / rel).exists() and repo.exists():
        return repo
    return None


# The manifest file that marks a real entry of each catalog kind (its plural dir → marker file).
_KIND_MARKER = {
    "agents": "agent.yaml",
    "recipes": "recipe.yaml",
    "services": "service.yaml",
    "stacks": "stack.yaml",
}


def list_catalog(kind: str) -> list[str]:
    """Every <kind> name visible across the catalog roots, deduped by name (user overlay wins).

    Origin-blind: an entry present in the user overlay (a.k.a. catalog/<kind>.local) and in the repo
    catalog is a single name in the unified list — callers must not care where it came from. `kind` is
    the plural dir: agents | recipes | services | stacks. Route ALL enumeration through here so a new
    lister can't accidentally see only the repo catalog.

    A dir with no marker file is treated as a recipe FAMILY: its immediate children that DO carry a
    marker are listed as variety refs (`beads/stealth/recipe.yaml` → `beads/stealth`). See
    `catalog_relpath` — the family itself is never a usable ref.
    """
    marker = _KIND_MARKER[kind]
    seen: set[str] = set()
    names: list[str] = []
    for root in catalog_roots():
        kind_dir = root / kind
        if not kind_dir.is_dir():
            continue
        for entry in sorted(kind_dir.iterdir()):
            if not entry.is_dir():
                continue
            if (entry / marker).is_file():
                found = [entry.name]
            else:
                found = [
                    f"{entry.name}/{sub.name}"
                    for sub in sorted(entry.iterdir())
                    if sub.is_dir() and (sub / marker).is_file()
                ]
            for name in found:
                if name not in seen:
                    seen.add(name)
                    names.append(name)
    return sorted(names)


def list_catalog_stacks() -> list[str]:
    """Every stack name visible across the catalog roots (see `list_catalog`).

    Used by `harnessed build`'s no-arg reconciliation pass and `harnessed list`.
    """
    return list_catalog("stacks")


def generated_catalog_root() -> Path:
    """Catalog root for MACHINE-MINTED stacks (`harnessed run`) — XDG DATA, never the overlay.

    A CATALOG ROOT, i.e. the dir that CONTAINS `stacks/` — the same shape as the other two, because
    `list_catalog` iterates `root / kind`. Manifests land at `<root>/stacks/<name>/stack.yaml`.

    Deliberately not `~/.config/harnessed/catalog`: that is where the user authors, and mixing
    generated manifests into it means `harnessed list` cannot tell them apart and a regenerated
    file silently clobbers a hand edit. Derived, disposable, reproducible from its inputs — the
    same category as `profiles_root`, and stored beside it for that reason.
    """
    return xdg_data_home() / "harnessed" / "generated"


def profiles_root() -> Path:
    """Root directory for all emitted stack profiles (XDG DATA)."""
    return xdg_data_home() / "harnessed" / "profiles"


def profile_dir(stack: str, harness: str) -> Path:
    """Absolute host path to the assembled profile for `stack` + `harness`."""
    return profiles_root() / stack / harness


def is_built(stack: str, harness: str) -> bool:
    """Return True if `stack`/`harness` has an assembled profile (.mcp.json at root)."""
    return (profile_dir(stack, harness) / ".mcp.json").is_file()


def host_homes_root() -> Path:
    """Root for host-native stack homes — the CLAUDE_CONFIG_DIR trees `launch --host` materializes."""
    return xdg_data_home() / "harnessed" / "home"


def host_home(stack: str, harness: str) -> Path:
    """Absolute host CLAUDE_CONFIG_DIR for `stack` + `harness` (host-native launch backend).

    NOT keyed by project (bd harnessed-8px.12). `--host` isolates CONFIGURATION, and the STACK is
    what defines the configuration — so the config dir is the stack's identity and nothing else
    belongs in the key. Nothing project-specific lives in here: `.mcp.json` is built from the stack's
    recipes alone, no `setup.script` writes to the config dir, and `.claude.json` is internally a
    path-keyed map that has served every project from one file since `~/.claude` existed.

    It USED to carry a `project_hash`, but only to dodge a self-inflicted hazard: the materialize
    wiped the dir on every launch, so two projects sharing one would let a second launch yank the dir
    out from under a running session. That wipe is now gated on the stack fingerprint
    (`_materialize_host_home`), so an unchanged stack never wipes and the hazard is gone — along with
    the per-project duplication of identical stack content, the orphan sprawl, and re-running every
    install script on every launch of every project.
    """
    return host_homes_root() / stack / harness


def host_home_shim(home: Path) -> Path:
    """A stable dir whose `.claude` symlinks to `home` — the host value of `$HARNESSED_HOME_SHIM`.

    Upstream installers commonly only know how to install "globally" into `$HOME/.claude`. Host-side
    that would mean the USER'S real `~/.claude`, so a recipe runs them under a fake `$HOME` whose
    `.claude` points at the stack's config dir instead.

    A SIBLING of `home`, not a child: `_materialize_host_home` rmtree's `home` on every launch, so a
    shim inside it would not survive. Sibling-per-project rather than one per stack, because the
    `.claude` symlink can only point at one config dir and two projects must not alias onto each
    other's.

    Stability is the entire point. Recipes previously improvised this with `mktemp -d` plus a trap,
    so every absolute path the installer recorded (gsd-core baked 12 hook paths into settings.json)
    pointed into a dir that was deleted seconds later — bd harnessed-8px.9.
    """
    return home.parent / f"{home.name}.home"


def project_hash(project_path: str | Path) -> str:
    """Stable 8-hex project key: sha1[:8] of the normalized project path.

    Single source for the per-project key used by BOTH `instance_name` and persist-dir
    resolution — no caller recomputes the digest independently, so the pod name and its
    persisted data can never drift apart on a trailing slash or symlink (the same
    `.rstrip("/")` normalization governs both).
    """
    p = str(Path(project_path)).rstrip("/")
    return hashlib.sha1(p.encode(), usedforsecurity=False).hexdigest()[:8]


def instance_name(stack: str, harness: str, project_path: str | Path) -> str:
    """Stable instance name: harnessed-<harness>-<stack>-<project_hash>."""
    return f"harnessed-{harness}-{stack}-{project_hash(project_path)}"


# Linux caps a hostname at HOST_NAME_MAX, which is 64 on every platform harnessed targets.
_HOST_NAME_MAX = 64


def container_hostname(inst: str) -> str:
    """A kernel-acceptable hostname for an instance name — `inst` itself when it already fits.

    Podman derives the hostname from the pod/container NAME when none is given, and crun then fails
    the pod's infra container with `sethostname: Invalid argument` (EINVAL) for anything past
    HOST_NAME_MAX. Authored stack names never got close; a content-derived one does —
    `harnessed-omp-default.beads-team.serena.superpowers-f6eb0941-59258991` is 69 characters, and
    every launch of it died before the harness container started.

    Truncates the MIDDLE, keeping the `harnessed-<harness>-` head and the whole trailing project
    hash: those are what tell two prompts apart, and the stack name in between is the part that is
    already a machine-minted hash. Purely cosmetic — nothing keys on the hostname, so a collision
    between two long stacks in one project costs nothing. Trailing `-`/`.` is stripped so the cut
    cannot leave an invalid label.
    """
    if len(inst) <= _HOST_NAME_MAX:
        return inst
    head, _, tail = inst.rpartition("-")
    return f"{head[:_HOST_NAME_MAX - len(tail) - 1].rstrip('-.')}-{tail}"


def setup_dismissed_flag(stack: str, harness: str, project_path: str | Path) -> Path:
    """Marker recording that the user dismissed a stack's unconditional `setup:` notices for this
    project (XDG STATE). Keyed per (stack, harness, project) via `instance_name`, so worktrees and
    other stacks/harnesses stay independent. Its mere existence means "dismissed" — see
    launcher._prompt_setup_notices. Conditional notices are NOT gated by this flag; they follow
    their own `setup.condition` every launch.
    """
    return xdg_state_home() / "harnessed" / "setup-dismissed" / instance_name(stack, harness, project_path)


def svc_ports_file() -> Path:
    """Registry of every `publish: stable` host port harnessed has handed out (XDG DATA).

    ONE file for the whole machine, not one per project: the question an allocation has to answer
    is "is this port already promised to some OTHER project?", and a per-project file cannot see
    far enough to answer it. Data rather than state — losing it does not just cost a cache refill,
    it re-allocates ports that are already written into projects' mise.local.toml.
    """
    return xdg_data_home() / "harnessed" / "svc-ports.json"


def persist_root() -> Path:
    """Root for recipe-declared persistent data (XDG DATA).

    A sibling of `profiles_root()` under harnessed's data dir, in its own `persist/`
    namespace so a recipe name can never collide with `profiles/` or another top-level
    data dir. Bind mounts (not named volumes) live here — the host owns the bytes.
    """
    return xdg_data_home() / "harnessed" / "persist"


class GitLookupFailed(Exception):
    """A git lookup could not be COMPLETED — distinct from completing and finding no repository.

    The distinction matters wherever the answer keys something persistent (bd harnessed-654). A
    caller that treats both as "no repo" falls back to the project path, so a transient failure
    silently produces a DIFFERENT key than the one written when git was healthy. Nothing errors;
    the wrong location is simply used and found empty.

    "Not a repository" and "git is not installed" are answers, not failures: both are stable across
    calls, so the fallback they trigger is stable too. A timeout, a permission error or an
    unrecognised git failure are not stable, and are what this reports.
    """


def git_common_dir_checked(project_path: str | Path) -> Path | None:
    """The git common dir, None if genuinely not a repository, raising on an incomplete lookup.

    Use this when the result keys something durable. Use `git_common_dir` when a fallback is
    harmless and you would rather not handle an exception.

    Timed out rather than trusted to return: this can be called per-directory by a shell hook, and
    a stalled filesystem must not hang the shell that asked.
    """
    # A directory that is not there is an ANSWER, not a failure: `git -C` cannot chdir into it, and
    # it will not be able to next time either. Checked here rather than pattern-matched out of
    # git's stderr, which says "cannot change to" and never mentions a repository at all.
    if not Path(project_path).is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except FileNotFoundError:
        return None  # git absent — stable, so the caller's fallback is stable too
    except subprocess.CalledProcessError as exc:
        if "not a git repository" in (exc.stderr or "").lower():
            return None  # a real answer: this directory is not in a repo
        raise GitLookupFailed(f"git rev-parse failed in {project_path}: {exc.stderr}") from exc
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise GitLookupFailed(f"git rev-parse could not run in {project_path}: {exc}") from exc

    p = Path(result.stdout.strip())
    if not p.exists():
        # git named a common dir that is not there. Not "no repo" — something is wrong underneath,
        # and keying on the fallback would be a guess.
        raise GitLookupFailed(f"git reported a common dir that does not exist: {p}")
    return p


def git_common_dir(project_path: str | Path) -> Path | None:
    """Return the git common dir for project_path (shared across all worktrees), or None.

    Uses `git rev-parse --path-format=absolute --git-common-dir`. This is the same path
    for every worktree of a given checkout, so it is the correct key for cross-worktree
    persistence. Returns None for non-git directories or when git is not available.

    LOSSY BY DESIGN, and kept that way so the fifteen-odd callers that only want "a repo root if
    there is one" need no error handling. A caller keying something durable on the answer wants
    `git_common_dir_checked` instead — see `GitLookupFailed`.
    """
    try:
        return git_common_dir_checked(project_path)
    except GitLookupFailed:
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


def persist_in_repo_dir(project_path: str | Path, name: str) -> Path:
    """Host dir for an `location: in_repo` persist entry, anchored at the CHECKOUT ROOT.

    A worktree-aware anchor, so every worktree of one checkout resolves to the SAME dir — matching
    how tools that key their in-repo state off the git common dir already behave (verified: `bd
    where` in a bare + linked-worktree layout resolves to `<bare>/.beads`, not `<worktree>/.beads`).

      * normal checkout — common dir is `<root>/.git`  → `<root>/<name>`
      * bare + linked worktrees — common dir is `<...>/.bare` → `<...>/.bare/<name>`
      * not a git repo — falls back to `<project_path>/<name>`

    This is the dir a project-scoped service bind-mounts as its data dir when the owning recipe
    declares `location: in_repo` (see launcher._service_data_dir).
    """
    gcd = git_common_dir(project_path)
    if gcd is None:
        return Path(project_path) / name
    root = gcd.parent if gcd.name == ".git" else gcd
    return root / name


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


def aws_sso_ecs_token_file() -> Path:
    """User-owned aws-sso ECS-server bearer token: $XDG_CONFIG_HOME/harnessed/aws-sso-ecs.token.

    Single source of truth shared between `harnessed aws-sso serve` (which generates it, loads it into
    the aws-sso secure store, and writes this file mode 0600) and the launcher's
    `_aws_sso_ecs_forward_args` (which reads it to build AWS_CONTAINER_AUTHORIZATION_TOKEN for a stack
    with `forward_aws_sso: true`). USER-owned (config dir, never the repo). See docs/guides/aws-sso.md.
    """
    return xdg_config_home() / "harnessed" / "aws-sso-ecs.token"


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
