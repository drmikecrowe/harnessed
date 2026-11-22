"""The catalog sources beyond the user overlay and the shipped catalog (HF-20261122-private-catalogs-add-two).

Three new kinds, all searched by `paths.catalog_sources()`:

- a FLAG source: a folder named by `--catalog <dir>`. `launcher.main` takes the flag out of argv
  and exports it in `HARNESSED_CATALOG`, so a harnessed child process sees the same folders.
- a PROJECT source: the nearest `.harnessed/catalog`, from the project directory up to its git
  top level. Read only once `harnessed catalog trust` has recorded its path: a cloned repository
  must not run its catalog's code on this host just because a launch started inside it.
- a GIT source: the clone of a registered repository, checked out detached at its locked commit.
  Only `harnessed catalog add` and `update` run git; a build reads the clone as it is.

This module holds no typer code. Every failure a user can cause raises `CatalogError` with the text
the CLI prints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from harnessed import paths

ENV_FLAG = "HARNESSED_CATALOG"

_flag: list[Path] | None = None
_project_dir: Path | None = None
_warned_untrusted: set[str] = set()
_storage: dict[tuple[str, tuple[str, ...]], str] = {}


class CatalogError(Exception):
    """A catalog command or lookup failed for a reason the user can fix; the text says how."""


def reset() -> None:
    """Forget every per-process choice: flag sources, project directory, warnings, storage names."""
    global _flag, _project_dir
    _flag = None
    _project_dir = None
    _warned_untrusted.clear()
    _storage.clear()
    paths._new_source_shadow_warned.clear()


# --- flag sources -----------------------------------------------------------------------------


def set_flag_sources(dirs: list[Path]) -> None:
    """Record the `--catalog` folders, in command-line order, and export them to child processes."""
    global _flag
    seen: list[Path] = []
    for d in dirs:
        r = Path(d).resolve()
        if r not in seen:
            seen.append(r)
    _flag = seen
    _storage.clear()
    if seen:
        os.environ[ENV_FLAG] = os.pathsep.join(str(p) for p in seen)
    else:
        os.environ.pop(ENV_FLAG, None)


def flag_sources() -> list[Path]:
    """The `--catalog` folders. A process that set none reads the ones its parent exported."""
    if _flag is not None:
        return list(_flag)
    raw = os.environ.get(ENV_FLAG, "")
    return [Path(p) for p in raw.split(os.pathsep) if p]


# --- project source ---------------------------------------------------------------------------


def set_project_dir(path: Path | None) -> None:
    """Set the directory project discovery starts from. None means no project source."""
    global _project_dir
    _project_dir = Path(path).resolve() if path is not None else None
    _storage.clear()
    # A new project is a new source set: a hidden entry there deserves its own warning (PR #669).
    paths._new_source_shadow_warned.clear()


def project_dir() -> Path | None:
    return _project_dir


def git_top_level(start: Path) -> Path | None:
    """The nearest directory from `start` upward that holds an entry named `.git`, or None.

    Reads directories only. Running git here would make every lookup depend on git being installed.
    """
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def discover_project_catalog(start: Path) -> Path | None:
    """The first `.harnessed/catalog` from `start` up to its git top level; only `start` without one."""
    start = Path(start).resolve()
    top = git_top_level(start)
    dirs = [start] if top is None else [start, *start.parents[: len(start.parents) - len(top.parents)]]
    for d in dirs:
        cand = d / ".harnessed" / "catalog"
        if cand.is_dir():
            return cand.resolve()
    return None


def trust_file() -> Path:
    return paths.xdg_state_home() / "harnessed" / "trusted-catalogs.json"


def trusted_paths() -> list[str]:
    f = trust_file()
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data["trusted"]
        if not isinstance(items, list):
            raise TypeError("'trusted' is not a list")
    except (ValueError, KeyError, TypeError) as exc:
        raise CatalogError(f"cannot read the trust record {f}: {exc}. Fix or delete it.") from None
    return [str(p) for p in items]


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_trusted(items: list[str]) -> None:
    _write_atomic(trust_file(), json.dumps({"trusted": items}, indent=2) + "\n")


def _record_trust(cat: Path) -> None:
    items = trusted_paths()
    if str(cat) not in items:
        _write_trusted([*items, str(cat)])


def _found_catalog(project: Path | None) -> Path:
    start = Path(project).resolve() if project is not None else Path.cwd()
    cat = discover_project_catalog(start)
    if cat is None:
        raise CatalogError(f"no .harnessed/catalog in {start} or a parent up to its git top level")
    return cat


def trust(project: Path | None = None) -> Path:
    """Trust the project catalog discovery finds from `project` (default: the current directory)."""
    cat = _found_catalog(project)
    _record_trust(cat)
    _warned_untrusted.discard(str(cat))
    return cat


def untrust(project: Path | None = None) -> Path:
    """Withdraw trust from the project catalog discovery finds from `project`."""
    cat = _found_catalog(project)
    items = trusted_paths()
    if str(cat) not in items:
        raise CatalogError(f"{cat} is not trusted")
    _write_trusted([p for p in items if p != str(cat)])
    return cat


def project_catalog() -> Path | None:
    """The discovered project catalog, trusted or not, for the current project directory."""
    return discover_project_catalog(_project_dir) if _project_dir is not None else None


def project_source() -> Path | None:
    """The trusted project catalog, or None. An untrusted one is named once, on stderr, and skipped."""
    cat = project_catalog()
    if cat is None:
        return None
    if str(cat) in trusted_paths():
        return cat
    if str(cat) not in _warned_untrusted:
        _warned_untrusted.add(str(cat))
        sys.stderr.write(
            f"warning: ignoring the untrusted project catalog {cat}\n"
            f"  Read it with: harnessed catalog trust {cat.parent.parent}\n"
        )
    return None


# --- git sources ------------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def registry_file() -> Path:
    return paths.xdg_config_home() / "harnessed" / "catalogs.yaml"


def clones_root() -> Path:
    return paths.xdg_data_home() / "harnessed" / "catalogs"


def clone_dir(name: str) -> Path:
    return clones_root() / name


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    return y


def load_registry() -> list[dict]:
    f = registry_file()
    if not f.is_file():
        return []
    try:
        data = _yaml().load(f.read_text(encoding="utf-8")) or {}
        items = data.get("catalogs", []) or []
        if not isinstance(items, list):
            raise TypeError("'catalogs' is not a list")
        return [{k: str(item[k]) for k in ("name", "url", "ref", "sha")} for item in items]
    except (YAMLError, AttributeError, KeyError, TypeError) as exc:
        raise CatalogError(f"cannot read the catalog registry {f}: {exc}. Fix or delete it.") from None


def _write_registry(items: list[dict]) -> None:
    buf = StringIO()
    _yaml().dump({"catalogs": [dict(i) for i in items]}, buf)
    _write_atomic(registry_file(), buf.getvalue())


def git_sources() -> list[tuple[str, Path]]:
    """(name, clone dir) for each registered catalog, in registry order."""
    return [(i["name"], clone_dir(i["name"])) for i in load_registry()]


def missing_clones() -> list[str]:
    return [name for name, d in git_sources() if not d.is_dir()]


def name_from_url(url: str) -> str:
    """The last path segment of `url`, after the last `/` or `:`, less a trailing `.git`."""
    tail = re.split(r"[/:]", url.rstrip("/"))[-1]
    return tail[: -len(".git")] if tail.endswith(".git") else tail


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name) or name.startswith(".") or ".." in name:
        raise CatalogError(
            f"invalid catalog name {name!r}: use letters, digits, '.', '_' and '-', "
            "with no leading '.' and no '..'"
        )


def _check_url_ref(url: str, ref: str | None) -> None:
    """Refuse a URL or ref git would read as an option, and git's command-running transports.

    `--upload-pack=<cmd>` as a URL, or `ext::<cmd>`, runs a command on this host. A user can type
    one, but a script that forwards a URL from a manifest should not be able to.
    """
    if url.startswith("-") or re.match(r"^(ext|fd)::", url):
        raise CatalogError(f"refusing catalog URL {url!r}: it reads as a git option or command transport")
    if ref is not None and (ref.startswith("-") or not ref.strip()):
        raise CatalogError(f"refusing ref {ref!r}: it reads as a git option")


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run git with the user's own configuration and credentials; stderr is captured for errors."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )


def _git_ok(args: list[str], cwd: Path | None = None) -> str:
    done = _git(args, cwd)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise CatalogError(f"git {args[0]} failed: {detail[-1] if detail else f'exit {done.returncode}'}")
    return done.stdout.strip()


def _default_branch(clone: Path) -> str:
    ref = _git_ok(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], clone)
    return ref.removeprefix("origin/")


def _resolve_ref(clone: Path, ref: str) -> str:
    """The commit `ref` names in `clone`: a remote branch first, then a tag or a commit id."""
    for cand in (f"refs/remotes/origin/{ref}", f"refs/tags/{ref}", ref):
        done = _git(["rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"], clone)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    raise CatalogError(f"ref {ref!r} not found in the repository")


def _checkout(clone: Path, sha: str) -> None:
    _git_ok(["checkout", "--quiet", "--force", "--detach", sha], clone)
    _git_ok(["clean", "--quiet", "-d", "--force"], clone)


def _clone_at(url: str, ref: str | None, dest: Path) -> tuple[str, str]:
    """Clone `url` into `dest` at `ref` (default branch when None); return (ref, sha).

    Clones into a temporary sibling first, so a failure leaves no directory at `dest`.
    """
    _check_url_ref(url, ref)
    clones_root().mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=clones_root(), prefix=f".{dest.name}."))
    try:
        _git_ok(["clone", "--quiet", "--no-checkout", "--", url, str(tmp)])
        if ref is None:
            ref = _default_branch(tmp)
        sha = _resolve_ref(tmp, ref)
        _checkout(tmp, sha)
        tmp.rename(dest)
        return ref, sha
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def add(url: str, ref: str | None = None, name: str | None = None) -> dict:
    """Register `url`: clone it, lock the commit `ref` names, and append it to the registry."""
    name = name if name is not None else name_from_url(url)
    _check_name(name)
    items = load_registry()
    if any(i["name"] == name for i in items):
        raise CatalogError(f"a catalog named {name!r} is already registered; choose another with --name")
    dest = clone_dir(name)
    if dest.exists():
        raise CatalogError(f"{dest} already exists and is not registered; remove it first")
    ref, sha = _clone_at(url, ref, dest)
    item = {"name": name, "url": url, "ref": ref, "sha": sha}
    try:
        _write_registry([*items, item])
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return item


def update(name: str) -> tuple[str, str]:
    """Move one catalog's lock to the current commit of its recorded ref; return (old, new)."""
    items = load_registry()
    idx = next((n for n, i in enumerate(items) if i["name"] == name), None)
    if idx is None:
        raise CatalogError(f"no catalog named {name!r} is registered")
    item = items[idx]
    dest = clone_dir(name)
    old = item["sha"]
    if not dest.is_dir():
        _, new = _clone_at(item["url"], item["ref"], dest)
    else:
        pinned = bool(_SHA_RE.match(item["ref"]))
        if not (pinned and _git(["cat-file", "-e", f"{item['ref']}^{{commit}}"], dest).returncode == 0):
            _git_ok(["fetch", "--quiet", "--force", "--tags", "--prune", "origin"], dest)
        new = _resolve_ref(dest, item["ref"])
        _checkout(dest, new)
    if new != old:
        items[idx] = {**item, "sha": new}
        _write_registry(items)
    return old, new


def remove(name: str) -> None:
    """Drop one catalog: its registry entry, then its clone when the clone still exists."""
    items = load_registry()
    if not any(i["name"] == name for i in items):
        raise CatalogError(f"no catalog named {name!r} is registered")
    _write_registry([i for i in items if i["name"] != name])
    shutil.rmtree(clone_dir(name), ignore_errors=True)


# --- scope ------------------------------------------------------------------------------------


def folder_sources() -> list[Path]:
    """The flag sources and the trusted project source, in source order, as resolved paths."""
    out = [p.resolve() for p in flag_sources()]
    proj = project_source()
    if proj is not None and proj not in out:
        out.append(proj)
    return out


def scope_suffix() -> str:
    """`-` and 8 hex of the SHA-256 of the folder sources' paths, newline-joined, in source order."""
    joined = "\n".join(str(p) for p in folder_sources())
    return "-" + hashlib.sha256(joined.encode()).hexdigest()[:8]


def _inside(path: Path, roots: list[Path]) -> bool:
    r = path.resolve()
    return any(r == root or r.is_relative_to(root) for root in roots)


def _closure(stack: str) -> list[Path]:
    """The directories `stack` loads: its own, each `extends:` parent, each recipe and service.

    A stack that cannot be loaded yields only the directories found before the failure. Agents are
    left out: the agent image is keyed on the harness alone, so scoping a stack for one would not
    separate anything.
    """
    from harnessed import schema

    stack_dir = paths.find_in_catalog("stacks", stack)
    if not (stack_dir / "stack.yaml").is_file():
        return []
    dirs = [stack_dir]
    try:
        cur, seen = stack_dir, {stack_dir.resolve()}
        while True:
            raw = schema._load_yaml(cur / "stack.yaml")
            parent = raw.get("extends") if isinstance(raw, dict) else None
            if not isinstance(parent, str) or not parent:
                break
            cur = schema._resolve_parent_stack_dir(parent, cur, cur / "stack.yaml")
            if cur.resolve() in seen:
                break
            seen.add(cur.resolve())
            dirs.append(cur)
        stk = schema.load_stack(stack_dir)
        dirs += [paths.find_in_catalog("recipes", r) for r in stk.recipes]
        dirs += [paths.find_in_catalog("services", s) for s in _service_names(stk)]
    except (schema.SchemaError, OSError, ValueError):
        pass
    return dirs


def _service_names(stk) -> list[str]:
    out = []
    for s in getattr(stk, "services", []) or []:
        out.append(s if isinstance(s, str) else getattr(s, "name", str(s)))
    return out


def storage_name(stack: str) -> str:
    """The name stored state is keyed on: `stack`, plus the scope suffix for a scoped stack.

    A stack is scoped when anything it loads comes from a folder source. With no folder source this
    returns `stack` without reading anything, so no existing profile, image or volume is renamed.
    """
    folders = folder_sources()
    if not folders:
        return stack
    key = (stack, tuple(str(p) for p in folders))
    if key not in _storage:
        scoped = any(_inside(d, folders) for d in _closure(stack))
        _storage[key] = f"{stack}{scope_suffix()}" if scoped else stack
    return _storage[key]
