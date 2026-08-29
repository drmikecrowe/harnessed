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
import re
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

# Generous enough for a real 1Password unlock the user is actually present for (biometric or
# password prompt), short enough that an unattended launch — CI, a cron-fired agent, a machine whose
# desktop app is not running — fails with a message instead of hanging forever. bd harnessed-prf.
_VARLOCK_TIMEOUT = 60

# Per-item proxy mode, keyed on schema dir. Same lifetime and same rationale as _VARLOCK_CACHE:
# `varlock proxy rules` is a subprocess, and both launch paths ask about the same dirs.
_PROXY_MODES_CACHE: dict[Path, dict[str, str] | None] = {}

# Dirs already warned about, so the four call sites (global/project x container/host) print once.
_PROXY_WARNED: set[Path] = set()

# What `varlock proxy rules` reports per item, and what each means for a launch:
#   proxied      pod holds a placeholder, real value injected at the wire      — the goal state
#   passthrough  pod holds the REAL value; deliberate (`@proxy=passthrough`)   — old exposure, fine
#   placeholder  sensitive but NO rule: reaches neither the pod NOR any upstream — BROKEN
#   omit         resolution failed, withheld from the child entirely            — BROKEN
#
# The last two are why this warning exists. varlock treats every item as sensitive by default, so
# an item nobody classified silently degrades to a useless placeholder: the agent gets a
# real-looking value that no upstream will ever accept, and the failure surfaces far away as a
# confusing 401. Naming them at launch is the whole point (issue #388, finding F1).
_PROXY_MODES_OK = ("proxied", "passthrough")

_RULES_HEADER_RE = re.compile(r"^Rules \((\d+)\)\s*$")
_SECRETS_HEADER_RE = re.compile(r"^Secrets \((\d+)\)\s*$")
# `  NAME<column padding>mode: description`. The padding is always >= 2 because the column is
# right-padded to the longest name.
_SECRET_LINE_RE = re.compile(r"^\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s{2,}(?P<mode>[a-z-]+):")

# The opt-in gate. Matches the ANNOTATION forms and not a prose mention of the word, because the
# only thing on the other side of this test is a `varlock proxy rules` subprocess that RESOLVES
# values — it can sit on a 1Password unlock prompt for up to `_VARLOCK_TIMEOUT`. A schema whose
# only `@proxy` is inside a sentence must not buy that.
#
# Measured against varlock 1.17.0, which is why the shapes are exactly these:
#   `@proxy(domain="…")`    -> a routing rule            (the item is proxied)
#   `@proxy=passthrough`    -> an explicit opt-out       (the item keeps its real value)
#   `@proxyConfig={egress=…}` -> schema-wide proxy policy
#   bare `@proxy`           -> an INVALID schema. `proxy rules` reports the item as `omit`
#                              (withheld entirely) and `varlock load` fails validation outright,
#                              so `_varlock_resolve` already returns None and the launch reports
#                              it. Excluding it from this gate costs no warning that is not
#                              already being made, more loudly, by the resolution path.
_PROXY_ANNOTATION_RE = re.compile(r"@proxy(?:Config)?\s*[(=]")


def _varlock_cache_clear() -> None:
    """Drop the `_varlock_resolve` memo. For tests that resolve the same dir across differing state."""
    _VARLOCK_CACHE.clear()
    _PROXY_MODES_CACHE.clear()
    _PROXY_WARNED.clear()


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

    try:
        result = subprocess.run(
            ["varlock", "load", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=str(schema_dir),
            timeout=_VARLOCK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        # Same degradation as a non-zero exit: a launch must not hang forever on secrets it may not
        # even need. Without the timeout this blocks indefinitely — `varlock load` authenticates
        # against a secrets manager, so it waits on a 1Password approval nobody is there to give, or
        # on a network fault with no deadline of its own. Every launch runs this on the critical
        # path, so the failure mode is "harnessed hangs", with no output explaining why.
        _err.print(
            f"[bold red]error:[/bold red] varlock load timed out after {_VARLOCK_TIMEOUT}s in "
            f"{schema_dir} — is it waiting on a 1Password approval? Secrets from this schema will "
            f"not be available to this launch."
        )
        _VARLOCK_CACHE[cache_key] = None
        return None
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

    A value containing a newline is SKIPPED with a warning rather than written. The format cannot
    represent one: podman reads to end-of-line, so a PEM block or SSH private key would arrive
    truncated at its first line and every following line would be parsed as its own KEY=VALUE (or
    rejected). Truncated key material fails later, somewhere that gives no hint it was truncated
    here — so omitting it and saying so is strictly better than corrupting it. bd harnessed-4gk.
    """
    resolved = _varlock_resolve(schema_dir)
    if resolved is None:
        return None

    # podman env-file is KEY=VALUE with the value literal to end-of-line — no quoting needed.
    writable = {}
    for k, v in resolved.items():
        if "\n" in v or "\r" in v:
            _err.print(
                f"[yellow]warning:[/yellow] secret '{k}' spans multiple lines and cannot be passed "
                f"through a podman --env-file — skipping it rather than truncating it. (A "
                f"host-native launch has no such limit.)"
            )
            continue
        writable[k] = v
    lines = "".join(f"{k}={v}\n" for k, v in writable.items())

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


def _schema_declares_proxy(schema_dir: Path) -> bool:
    """Whether this schema carries a `@proxy` ANNOTATION — the cheap gate on everything below.

    A text test, not a parse, and deliberately so: it costs one file read, and a schema with no
    `@proxy` anywhere is every schema shipped today. That keeps `varlock proxy rules` — which
    RESOLVES values, so it can prompt for a 1Password unlock — entirely off the critical path until
    somebody opts into the proxy model.

    Matches `_PROXY_ANNOTATION_RE`, not the bare word. A prose line like
    `# TODO: add @proxy after the migration` used to pass this gate and buy a resolving subprocess
    for a schema that had opted into nothing.

    Two known limits, both erring toward a MISSING warning rather than a false one:

      * It reads the entry schema only, so a `@proxy` living exclusively in an imported fragment is
        missed. Must be revisited when recipe `env.schema` fragments land — see #388 Phase 1.
      * Prose that happens to quote a full annotation (`use @proxy=passthrough for these`) still
        matches. Unavoidable without parsing, and the cost is one spurious subprocess rather than a
        wrong claim about anybody's secrets.
    """
    try:
        text = (schema_dir / ".env.schema").read_text(encoding="utf-8")
    except OSError:
        return False
    return _PROXY_ANNOTATION_RE.search(text) is not None


def _varlock_proxy_modes(schema_dir: Path) -> dict[str, str] | None:
    """`{KEY: mode}` from `varlock proxy rules`, or None when the output cannot be trusted.

    `proxy rules` is the ONLY source of per-item proxy mode — `varlock load --format json-full`
    reports `isSensitive` and the schema-wide egress setting but nothing per item — and it prints
    for humans, with no `--format json`. So this parses display text, which will drift.

    It therefore refuses to guess. The `Secrets (N)` header states its own count; if the number of
    lines parsed does not match N, or either header is missing, this returns None and the caller
    says so out loud. A guardrail that quietly stops guarding is the failure mode we already have
    one open bug for (#429) — not a pattern to repeat here.
    """
    cached = _PROXY_MODES_CACHE.get(schema_dir, ...)
    if cached is not ...:
        return cached  # type: ignore[return-value]

    result: dict[str, str] | None = None
    try:
        proc = subprocess.run(
            ["varlock", "proxy", "rules"],
            cwd=schema_dir, capture_output=True, text=True, timeout=_VARLOCK_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        proc = None

    if proc is not None and proc.returncode == 0:
        rule_count: int | None = None
        declared: int | None = None
        modes: dict[str, str] = {}
        in_secrets = False
        for line in proc.stdout.splitlines():
            if (m := _RULES_HEADER_RE.match(line)):
                rule_count = int(m.group(1))
                continue
            if (m := _SECRETS_HEADER_RE.match(line)):
                declared, in_secrets = int(m.group(1)), True
                continue
            if in_secrets:
                if not line.strip():
                    in_secrets = False
                    continue
                if (m := _SECRET_LINE_RE.match(line)):
                    modes[m.group("name")] = m.group("mode")
        # Both headers must have been seen and the count must agree, or the parse is not
        # trustworthy. `rule_count` is read purely as that structural check.
        if rule_count is not None and declared is not None and len(modes) == declared:
            result = modes

    _PROXY_MODES_CACHE[schema_dir] = result
    return result


def _warn_unproxied_secrets(schema_dir: Path) -> None:
    """Name the secrets the credential proxy will NOT carry, once per schema dir per launch.

    A READINESS REPORT, not a live fault. Today `_varlock_resolve` runs `varlock load`, which hands
    back the real value for every item whatever its proxy mode — so an unrouted item still works.
    It stops working the moment the launch switches to the broker's placeholder env (#388 Phase 1),
    and at that point the failure is invisible: a real-looking placeholder no API accepts,
    surfacing far away as a 401. Saying so while the schema is still being authored is the entire
    value; a warning that arrives only after the cutover arrives too late to be cheap.

    The wording therefore states both tenses. Do not tighten it to the present until the broker
    path is the one actually delivering these values.

    Silent unless the schema opts in (`@proxy` present). Values are never read or printed — this
    reports NAMES and MODES only, which is what makes it safe to run on every launch.
    """
    if schema_dir in _PROXY_WARNED or not _schema_declares_proxy(schema_dir):
        return
    _PROXY_WARNED.add(schema_dir)

    classified = _varlock_proxy_modes(schema_dir)
    if classified is None:
        _err.print(
            f"[yellow]warning:[/yellow] {schema_dir}/.env.schema declares @proxy, but "
            "`varlock proxy rules` could not be classified — so harnessed cannot tell you which "
            "secrets the proxy will carry. Check `varlock proxy rules` by hand; if its output "
            "looks fine, this parser needs updating for your varlock version."
        )
        return

    # Grouped by what actually goes wrong, because the fix differs. Anything unrecognised joins
    # `unusable`: a mode this version of harnessed has never heard of is not something to assume
    # is safe.
    unusable = sorted(k for k, v in classified.items()
                      if v not in _PROXY_MODES_OK and v != "omit")
    withheld = sorted(k for k, v in classified.items() if v == "omit")
    passthrough = sorted(k for k, v in classified.items() if v == "passthrough")

    if unusable:
        _err.print(
            f"[yellow]warning:[/yellow] {len(unusable)} secret(s) in {schema_dir}/.env.schema "
            "declare no @proxy route. Once harnessed brokers secrets (#388) each will reach "
            "neither the agent nor any upstream — a placeholder no API accepts, surfacing as an "
            "unexplained 401. They still arrive as real values today:"
        )
        for k in unusable:
            _err.print(f"  [yellow]·[/yellow] {k} [dim]({classified[k]})[/dim]")
        _err.print(
            "[dim]  Fix each one: @proxy(domain=…) ON THE ITEM to route it (in the header it "
            "declares a policy rule and injects nothing), @proxy=passthrough to send the real "
            "value into the container, or @sensitive=false if it is not a secret.[/dim]"
        )

    if withheld:
        # Worth printing even though `_varlock_resolve` also fails on this schema: its error names
        # the DIRECTORY, this names the ITEM. That is the difference between "varlock broke" and
        # "this one credential is gone".
        _err.print(
            f"[yellow]warning:[/yellow] {len(withheld)} secret(s) in {schema_dir}/.env.schema "
            "could not be resolved at all:"
        )
        for k in withheld:
            _err.print(f"  [yellow]·[/yellow] {k}")
        _err.print(
            "[dim]  Resolver failures, not routing mistakes — check the backing item exists and "
            "the secrets backend is reachable. Today this fails the whole schema; under the "
            "broker it would withhold just these.[/dim]"
        )

    if passthrough:
        # Not a defect — a declared decision. Reported because "which real secrets are still in
        # the container" is exactly the question the proxy exists to make answerable, and a
        # passthrough item keeps the full pre-proxy exposure.
        _err.print(
            f"[dim]note: {len(passthrough)} secret(s) are declared to keep passing through as "
            f"real values in the container: {', '.join(passthrough)}[/dim]"
        )


def proxy_schema_dirs(project_path: Path | None = None) -> list[Path]:
    """The composed schema dirs that opt into the proxy model, in --env-file order (global, then
    project). Empty when nothing opted in — which is every stack shipped today.

    This is the gate on starting a secrets broker at all (#437). It deliberately mirrors the dir
    selection in `_resolve_launch_secrets` rather than inventing its own: the broker must resolve
    the SAME set the --env-file path resolves, or #439 will hand the pod placeholders for items the
    broker never loaded.

    `_schema_declares_proxy` is a text test, so this costs two file reads and NO subprocess. That
    matters: `varlock proxy rules` resolves values and can sit on a 1Password unlock prompt, and a
    launch that opted into nothing must not buy one.
    """
    if not shutil.which("varlock"):
        return []
    dirs: list[Path] = []
    global_dir = Path.home() / ".config" / "harnessed"
    if (global_dir / ".env.schema").is_file() and _schema_declares_proxy(global_dir):
        dirs.append(global_dir)
    if project_path is not None:
        if (project_path / ".env.schema").is_file() and _schema_declares_proxy(project_path):
            dirs.append(project_path)
    return dirs


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
        _warn_unproxied_secrets(global_dir)
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
            _warn_unproxied_secrets(project_path)
            p = _varlock_resolve_env_file(project_path)
            if p:
                env_files.append(p)
                temp_files.append(p)
        elif proj_env.is_file():
            p = _normalize_plain_env_file(proj_env)
            env_files.append(p)
            temp_files.append(p)

    return env_files, temp_files


def _strip_var_from_env_files(var: str, env_files: list[Path]) -> None:
    """Delete every assignment of `var` from already-resolved env-files, in place.

    For `isolated_auth` stacks (see `_claude_isolated_auth_mount`). Suppressing the `-e` forward is
    not enough on its own: `--env-file` is handed to podman unconditionally, so a
    CLAUDE_CODE_OAUTH_TOKEN declared in the USER-GLOBAL `~/.config/harnessed/.env.schema` — the
    normal way to hold your own token — would still reach a stack whose entire purpose is to run as
    somebody else. Stripping the variable is what makes the isolation actually hold.

    Rewriting these files in place is safe precisely because none of them is the user's: every path
    `_resolve_launch_secrets` returns is a mode-0600 temp it generated (a plain `.env` is COPIED,
    never handed to podman directly) and the caller unlinks them after launch. Passing a
    non-generated path here would corrupt user data — do not.

    Preferred over `-e VAR=` (which does beat `--env-file`) because that would depend on the harness
    reading an empty token as "absent", which is unverified. Absent is unambiguous.
    """
    for f in env_files:
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        kept = [ln for ln in lines if (pair := _parse_plain_env_line(ln)) is None or pair[0] != var]
        if len(kept) != len(lines):
            f.write_text("".join(f"{ln}\n" for ln in kept))


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
        _warn_unproxied_secrets(global_dir)
        resolved = _varlock_resolve(global_dir)
        if resolved:
            values.update(resolved)
    elif global_env.is_file():
        values.update(_plain_env_values(global_env))

    if project_path is not None:
        proj_schema = project_path / ".env.schema"
        proj_env = project_path / ".env"
        if proj_schema.is_file() and have_varlock:
            _warn_unproxied_secrets(project_path)
            resolved = _varlock_resolve(project_path)
            if resolved:
                values.update(resolved)
        elif proj_env.is_file():
            values.update(_plain_env_values(proj_env))

    return values
