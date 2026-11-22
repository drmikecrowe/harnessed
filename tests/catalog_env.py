"""Shared fixture tree for the private-catalog tests (HF-20261122-private-catalogs-add-two).

Every root a test touches lives under `tmp_path`: the user overlay (`XDG_CONFIG_HOME`), the clones,
the generated root and the profiles (`XDG_DATA_HOME`), the trust record (`XDG_STATE_HOME`), and the
shipped catalog (`HARNESSED_DIR`). Nothing reads the developer's real catalog.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from harnessed import catalogsources, paths, schema

_MARKER = {
    "agents": "agent.yaml",
    "recipes": "recipe.yaml",
    "services": "service.yaml",
    "stacks": "stack.yaml",
}


@dataclass
class Env:
    tmp: Path
    overlay: Path
    shipped: Path
    data: Path
    state: Path

    @property
    def generated(self) -> Path:
        return self.data / "harnessed" / "generated"

    @property
    def clones(self) -> Path:
        return self.data / "harnessed" / "catalogs"


def install(monkeypatch, tmp_path: Path) -> Env:
    cfg, data, state, home = (tmp_path / n for n in ("cfg", "data", "state", "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("HARNESSED_DIR", str(home))
    # set, then delete: monkeypatch records the variable, so teardown removes the value a test's
    # `set_flag_sources` exported instead of leaking it into every later test.
    monkeypatch.setenv(catalogsources.ENV_FLAG, "")
    monkeypatch.delenv(catalogsources.ENV_FLAG)
    (home / "catalog").mkdir(parents=True)
    catalogsources.reset()
    schema._reset_overlay_shadow_warnings()
    return Env(tmp_path, cfg / "harnessed" / "catalog", home / "catalog", data, state)


def entry(root: Path, kind: str, name: str, body: str | None = None) -> Path:
    """Write `<root>/<kind>/<name>/<marker>`; a stack gets `recipes: []` unless `body` says more."""
    d = root / kind / paths.catalog_relpath(name)
    d.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = f"name: {name}\nrecipes: []\n" if kind == "stacks" else f"name: {name}\n"
    (d / _MARKER[kind]).write_text(body)
    return d


def project(tmp_path: Path, rel: str = "proj", *, git: bool = True) -> Path:
    """A project directory holding `.harnessed/catalog`, with a `.git` dir when `git` is set."""
    p = tmp_path / rel
    (p / ".harnessed" / "catalog").mkdir(parents=True)
    if git:
        (p / ".git").mkdir()
    return p


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd or "/"),
             "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return out.stdout.strip()


def remote(tmp_path: Path, name: str = "harnessed-catalog", branch: str = "main") -> tuple[Path, Path]:
    """A bare repository at `<tmp>/remotes/<name>.git` and a work clone that pushes to it.

    Returns (bare URL path, work dir). The work dir starts with one commit holding `stacks/team`.
    """
    bare = tmp_path / "remotes" / f"{name}.git"
    work = tmp_path / "work" / name
    bare.parent.mkdir(parents=True, exist_ok=True)
    git("init", "--bare", "-q", f"--initial-branch={branch}", str(bare))
    work.mkdir(parents=True)
    git("init", "-q", f"--initial-branch={branch}", cwd=work)
    entry(work, "stacks", "team")
    commit(work, "first")
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "-q", "origin", branch, cwd=work)
    return bare, work


def commit(work: Path, msg: str) -> str:
    git("add", "-A", cwd=work)
    git("commit", "-q", "--allow-empty", "-m", msg, cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def push(work: Path, branch: str = "main") -> None:
    git("push", "-q", "origin", branch, cwd=work)
