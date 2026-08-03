"""Resolve the environment a launch runs with — varlock schemas and plain `.env` files.

Two shapes of the same answer, because the two launch modes consume it differently:

  * `_resolve_launch_secrets` returns a list of `--env-file` paths, for the container path (podman
    needs a FILE).
  * `_resolve_launch_env` returns a `KEY -> value` map, for the host path (`os.environ` IS the box,
    so nothing is written to disk).

Both read the same sources in the same global -> project order, and that shared precedence is the
reason they live together: the two must not drift.

Pure resolution only — nothing here knows about podman, containers, or the Typer surface.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

from pathlib import Path

from .console import _err

# Memo for `_varlock_resolve`, keyed on the resolved schema dir. Populated for the lifetime of one
# CLI process, which is exactly one launch.
#
# `varlock load` shells out and may authenticate against a secrets manager (1Password), so each call
# costs real latency. The same dir is resolved by several callers in a single launch:
# `_varlock_resolve_env_file` builds the --env-file set, then `_claude_oauth_token_configured` asks
# the same dirs whether a token is present (and `_resolve_launch_env` does both on the host path).
# Uncached that is up to 4 subprocesses per launch where 2 suffice.
#
# Caching is safe here BECAUSE the process is short-lived and one launch must see a CONSISTENT
# secret set anyway — resolving the same dir twice and acting on different answers would be a bug,
# not a feature. Tests that need fresh resolution monkeypatch `_varlock_resolve` wholesale (which
# bypasses this entirely) or call `_varlock_cache_clear()`.
_VARLOCK_CACHE: dict[Path, dict[str, str] | None] = {}


def _varlock_cache_clear() -> None:
    """Drop the `_varlock_resolve` memo. For tests that resolve the same dir across differing state."""
    _VARLOCK_CACHE.clear()


def _varlock_resolve(schema_dir: Path) -> dict[str, str] | None:
    """Run `varlock load --format json` in schema_dir and return the resolved `KEY -> value` map
    (values stringified, `None`s dropped). Returns None on varlock failure so a launch degrades
    gracefully rather than hard-failing.

    Uses `--format json` (not `--format env`) because the `env` format double-quotes every value
    (`KEY="val"`) and podman `--env-file` keeps those quotes literal; JSON gives raw values, which
    both consumers want — see `_varlock_resolve_env_file` (container) and `_resolve_launch_env`
    (host, where the values go straight into `os.environ` and never touch disk).

    Memoized per schema dir — see `_VARLOCK_CACHE`. The failure result (None) is cached too, so a
    broken varlock reports its error once per dir instead of once per caller.

    Assumes a `.env.schema` in schema_dir and `varlock` on PATH (checked by the caller).
    `OP_SERVICE_ACCOUNT_TOKEN` is included when already set in the host env (headless / CI path —
    service-account bearer auth, no desktop app required).
    """
    cache_key = schema_dir.resolve()
    if cache_key in _VARLOCK_CACHE:
        return _VARLOCK_CACHE[cache_key]

    result = subprocess.run(
        ["varlock", "load", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(schema_dir),
    )
    if result.returncode != 0:
        _err.print(
            f"[bold red]error:[/bold red] varlock load failed in {schema_dir} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
        _VARLOCK_CACHE[cache_key] = None
        return None

    try:
        resolved = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        _err.print(f"[bold red]error:[/bold red] varlock load returned invalid JSON: {e}")
        _VARLOCK_CACHE[cache_key] = None
        return None

    def _fmt(v: object) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    values = {k: _fmt(v) for k, v in resolved.items() if v is not None}
    op_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if op_token:
        values["OP_SERVICE_ACCOUNT_TOKEN"] = op_token
    _VARLOCK_CACHE[cache_key] = values
    return values


def _varlock_resolve_env_file(schema_dir: Path) -> Path | None:
    """Resolve schema_dir via varlock, writing a mode-0600 temp env-file of clean `KEY=VALUE` lines
    and returning its path. The caller MUST unlink the file after launch.

    Values are written verbatim: `_varlock_resolve` hands back raw (unquoted) values, and podman
    reads an env-file value to end-of-line — so no quoting or escaping is needed for the
    single-line values this carries (API keys/tokens). Returns None when resolution fails, so the
    launch degrades gracefully rather than hard-failing.
    """
    resolved = _varlock_resolve(schema_dir)
    if resolved is None:
        return None

    # podman env-file is KEY=VALUE with the value literal to end-of-line — no quoting needed.
    lines = "".join(f"{k}={v}\n" for k, v in resolved.items())

    fd, tmp = tempfile.mkstemp(prefix="harnessed-env.", suffix=".env")
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(lines)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return Path(tmp)


def _parse_plain_env_line(raw: str) -> tuple[str, str] | None:
    """Parse one dotenv line into (key, value), stripping an `export ` prefix and one pair of
    surrounding quotes. Returns None for blank/comment/`=`-less lines (nothing to set)."""
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):]
    key, _, val = stripped.partition("=")
    key, val = key.strip(), val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return key, val


def _plain_env_values(src: Path) -> dict[str, str]:
    """Read a plain `.env` into a `KEY -> value` map (same normalization as
    `_normalize_plain_env_file`, minus the temp file). Used by the host path, which sets the values
    in-process instead of handing podman an env-file."""
    return dict(
        pair for raw in src.read_text().splitlines()
        if (pair := _parse_plain_env_line(raw)) is not None
    )


def _normalize_plain_env_file(src: Path) -> Path:
    """Copy a plain `.env` into a mode-0600 temp env-file, stripping one pair of surrounding quotes
    from each value and any `export ` prefix. The caller MUST unlink the returned file after launch.

    podman `--env-file` keeps quotes literal (`KEY="v"` → the container sees `"v"`), so a user's
    dotenv-style `.env` — where quoting values is idiomatic — would otherwise land quoted inside the
    container. We rewrite `KEY="v"` / `KEY='v'` → `KEY=v`. Comment/blank lines pass through (podman
    ignores them); lines without `=` pass through unchanged.
    """
    out: list[str] = []
    for raw in src.read_text().splitlines():
        pair = _parse_plain_env_line(raw)
        if pair is None:
            out.append(raw)
            continue
        out.append(f"{pair[0]}={pair[1]}")

    fd, tmp = tempfile.mkstemp(prefix="harnessed-env.", suffix=".env")
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(out) + "\n")
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return Path(tmp)


def _resolve_launch_secrets(project_path: Path | None = None) -> tuple[list[Path], list[Path]]:
    """Resolve launch-time env-files, layered global → project (podman --env-file is last-wins,
    so project values override the global schema).

    Sources, in --env-file order:
      1. User-global ~/.config/harnessed/: `.env.schema` resolved via varlock (opt-in: needs the
         schema present and `varlock` on PATH), else a bare `.env` read literally. This is also the
         sole source of scanner tokens for `harnessed rescan` (_scan_image_in_container).
      2. Per-project env from project_path:
         - <project>/.env.schema present → `varlock load` in the project dir (varlock already
           cascades .env / .env.local overlays on top of the schema).
         - else <project>/.env present → normalized into a temp env-file (surrounding quotes /
           `export ` stripped so podman doesn't ingest them literally); no varlock, no resolution.

    Returns (env_files, temp_files): env_files is the ordered list to hand to --env-file;
    temp_files is the subset the caller MUST unlink after launch (resolved secrets must not
    linger on disk). Every env-file here is a generated temp — the user's own `.env` is copied,
    never handed to podman directly, so it is never modified or unlinked.
    """
    env_files: list[Path] = []
    temp_files: list[Path] = []
    have_varlock = bool(shutil.which("varlock"))

    global_dir = Path.home() / ".config" / "harnessed"
    global_schema = global_dir / ".env.schema"
    global_env = global_dir / ".env"
    if global_schema.is_file() and have_varlock:
        p = _varlock_resolve_env_file(global_dir)
        if p:
            env_files.append(p)
            temp_files.append(p)
    elif global_env.is_file():
        # Same precedence as the per-project pair below: a schema wins (varlock already cascades a
        # sibling .env), and a bare .env is read literally — no varlock, no op:// resolution.
        p = _normalize_plain_env_file(global_env)
        env_files.append(p)
        temp_files.append(p)

    if project_path is not None:
        proj_schema = project_path / ".env.schema"
        proj_env = project_path / ".env"
        if proj_schema.is_file() and have_varlock:
            p = _varlock_resolve_env_file(project_path)
            if p:
                env_files.append(p)
                temp_files.append(p)
        elif proj_env.is_file():
            p = _normalize_plain_env_file(proj_env)
            env_files.append(p)
            temp_files.append(p)

    return env_files, temp_files


def _resolve_launch_env(project_path: Path | None = None) -> dict[str, str]:
    """The host-native twin of `_resolve_launch_secrets`: the same sources and the same
    global → project precedence (project wins), returned as a `KEY -> value` map instead of a list
    of `--env-file` paths.

    Host mode has no pod to hand an env-file to — `os.environ` IS the box — so the values are set
    in-process by the caller and NEVER written to disk. That is strictly better than the container
    path's mode-0600 temp file, which is only there because podman needs a file.

    Returns {} when nothing is configured (no schema / no `varlock` on PATH / no `.env`), or when
    varlock fails — a launch must not hard-fail on secrets that may not be needed at all.
    """
    values: dict[str, str] = {}
    have_varlock = bool(shutil.which("varlock"))

    global_dir = Path.home() / ".config" / "harnessed"
    global_schema = global_dir / ".env.schema"
    global_env = global_dir / ".env"
    if global_schema.is_file() and have_varlock:
        resolved = _varlock_resolve(global_dir)
        if resolved:
            values.update(resolved)
    elif global_env.is_file():
        values.update(_plain_env_values(global_env))

    if project_path is not None:
        proj_schema = project_path / ".env.schema"
        proj_env = project_path / ".env"
        if proj_schema.is_file() and have_varlock:
            resolved = _varlock_resolve(project_path)
            if resolved:
                values.update(resolved)
        elif proj_env.is_file():
            values.update(_plain_env_values(proj_env))

    return values
