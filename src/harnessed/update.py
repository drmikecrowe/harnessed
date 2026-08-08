"""`harnessed update` — find flagged/outdated pins and offer to bump them (bd harnessed-tfm).

Every download in the catalog is pinned on purpose: `tools:` rejects a floating `@latest`, and a
recipe Dockerfile that fetches from a moving ref fails the build. The cost of that correctness is
maintenance — pins rot silently, and the only way to notice used to be a human reading Dockerfiles.

Three ideas carry the design.

RESOLVABLE vs OPAQUE
    A `tools:` entry is a mise spec, and a mise spec NAMES ITS BACKEND (`npm:`, `pipx:`,
    `github:`, or bare = mise-registered). That makes "what is the latest version" a registry
    lookup, so `tools:` is the first-class surface this command is built around.

    install.sh bodies, Dockerfiles, and `install.cache` are not that. They are shell and text, and
    a pin inside them can be a SHA, a tag, an archive URL, or a synthetic cache key. We find them
    BEST-EFFORT and report every one as UNRESOLVED. That reporting is not a nicety — a tool that
    silently drops what it cannot parse reads as "everything is current", which is precisely the
    false confidence this command exists to remove. (bd harnessed-1t4.3 is migrating tool installs
    out of install.sh onto `tools:`, which steadily widens the resolvable surface. Nothing here
    races it; discovery just sees fewer opaque pins as it lands.)

HELD (bd harnessed-c5t)
    `install.hold` / a `tools:` entry's `hold` mark a pin manual-upgrade-only. Held pins are LISTED
    with their newer ref — hiding the information would be its own failure — but never enter the
    bump set and never fail `--check`. The motivating case is skill content: a skill is agent
    instructions run with the agent's full tool permissions, so a compromised upgrade is prompt
    injection rather than a CVE, and no scanner in the osv/trivy/grype family detects it.

--check WRITES NOTHING
    Report building is side-effect free; only `apply` writes. A CI mode that mutated the tree it
    was validating would be a trap.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ruamel.yaml import YAML

from . import paths
from .schema import SchemaError, load_recipe, load_stack, parse_extra_tools

__all__ = [
    "Pin", "Finding", "Release", "Report", "ResolveError",
    "discover_pins", "discover_extra_tools_pins", "build_report", "apply", "resolve_releases",
    "version_key", "extra_tools_default_path", "EXTRA_TOOLS_LABEL",
    "mise_repo", "affected_stacks", "verify_commands",
    "DEFAULT_MINIMUM_RELEASE_AGE_MINUTES",
]

# Modelled on pnpm's `minimumReleaseAge`, including its unit: MINUTES. A compromised or broken
# publish is usually yanked within days, so declining to install anything younger costs nothing and
# closes that window. Our default is 7 days rather than pnpm's 1440 (1 day) — measured on
# 2026-07-25, ALL FIVE pins the command offered were younger than a week, two of them hours old.
#
# Like pnpm, and unlike a naive gate, a too-fresh newest release does not mean "no update": the
# newest version that IS old enough is offered instead (see `_select`). Refusing outright would
# leave a stale pin stale for a week even when a mature intermediate release exists.
DEFAULT_MINIMUM_RELEASE_AGE_MINUTES = 7 * 1440  # 10080


class ResolveError(RuntimeError):
    """Upstream could not be asked, or answered with something we do not understand."""


# A pin literal assigned to a shell/Dockerfile variable: `FOO_SHA=0283bed3...`, `ARG REF="v6.0.3"`.
# Deliberately narrow — see `_IMMUTABLE_LITERAL_RE`. This is the shape catalog scripts actually use
# (a pinned ref hoisted to a variable at the top of the file, consumed further down), which is why
# one hop is enough to find them without parsing shell.
_ASSIGN_RE = re.compile(
    r'^\s*(?:export\s+|ARG\s+|ENV\s+)?([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|\'[^\']*\'|\S+)\s*$',
    re.MULTILINE,
)
# A value that LOOKS like a pin: a 40-hex commit SHA, or a version-ish tag (v6.0.3, 1.2.3-rc.1).
# Fails closed: an unrecognised shape is not reported as a pin at all, because a false "here is a
# pin you should bump" on every `FOO=bar` would bury the real ones.
_IMMUTABLE_LITERAL_RE = re.compile(r'^(?:[0-9a-fA-F]{40}|v?\d+(?:\.\d+)+(?:[-+.][0-9A-Za-z.]+)?)$')
# Version comparison. Split into numeric and non-numeric runs so `1.10.0` outranks `1.9.0` (a
# lexicographic compare gets this backwards, which is the classic version-sort bug).
_NUM_RE = re.compile(r'(\d+)')


def version_key(v: str) -> tuple:
    """A sortable key for a version string.

    Handles the three shapes the catalog actually contains: plain `1.2.3`, a `v`-prefixed tag, and
    a prerelease suffix. A prerelease sorts BELOW its own release (`1.0.0-rc.1` < `1.0.0`) — PEP
    440 and semver agree on that, and getting it backwards would offer a downgrade as an upgrade.
    """
    s = v.strip().lstrip("vV")
    base, _, pre = s.partition("-")
    parts: list[int] = []
    for chunk in base.split("."):
        m = _NUM_RE.match(chunk)
        parts.append(int(m.group(1)) if m else 0)
    # A release has no prerelease suffix and must outrank one: (parts, 1) > (parts, 0, ...).
    if not pre:
        return (tuple(parts), 1)
    pre_parts = tuple(int(c) if c.isdigit() else c for c in re.split(r'[.+]', pre))
    return (tuple(parts), 0, pre_parts)


@dataclass(frozen=True)
class Pin:
    """One pinned reference found in the catalog.

    `backend` is the resolver to ask — or `"opaque"`, meaning "found, but nothing can be asked".
    An opaque pin is still a Pin on purpose: it must travel all the way into the report rather than
    being filtered out at discovery, where it would become invisible.
    """
    recipe: str
    file: Path
    spec: str            # the full text as written (`npm:x@1.0.0`, or the bare literal)
    name: str            # what to ask the backend about (`@scope/pkg`, `owner/repo`, `pulumi`)
    current: str         # the pinned version/ref
    backend: str         # npm | pipx | github | mise | opaque
    hold: str | None = None
    note: str = ""       # where an opaque pin came from, for the human reading the report

    @property
    def resolvable(self) -> bool:
        return self.backend != "opaque"


@dataclass(frozen=True)
class Release:
    """What a backend answered: the newest version, and when it was published.

    `published` is None only when a backend genuinely cannot say. That is not treated as "fine" —
    the cooldown cannot be honoured for an undated release, so it is withheld and reported.
    """
    version: str
    published: datetime | None = None


@dataclass
class Finding:
    pin: Pin
    latest: str | None = None
    error: str | None = None
    published: datetime | None = None
    age_days: float | None = None
    # Set when the release is newer but inside the cooldown. `apply` refuses these outright, so a
    # caller that hands it the wrong bucket still cannot write a too-fresh version.
    cooling: bool = False
    # A NEWER release than `latest` that was passed over for being too young. Offering 1.6.0 while
    # 1.6.1 exists is surprising unless the report says why, so this is carried for the renderer.
    skipped_newer: str | None = None
    skipped_newer_age_days: float | None = None

    @property
    def stale(self) -> bool:
        if self.latest is None:
            return False
        try:
            return version_key(self.latest) > version_key(self.pin.current)
        except (ValueError, AttributeError):
            return False


@dataclass
class Report:
    stale: list[Finding] = field(default_factory=list)
    held: list[Finding] = field(default_factory=list)
    current: list[Finding] = field(default_factory=list)
    unresolved: list[Finding] = field(default_factory=list)
    # Newer, but too young to trust yet. Its own bucket rather than a silent drop: the user is
    # entitled to know a release exists and is being waited out, not just see nothing.
    cooling: list[Finding] = field(default_factory=list)

    def check_exit_code(self) -> int:
        """`--check`: non-zero ONLY for a stale, unheld, resolvable, past-cooldown pin.

        Unresolved pins do not fail — every recipe with a Dockerfile has one, and a permanently-red
        check is one nobody reads. Cooling pins do not fail either: you cannot act on a release you
        are deliberately waiting for, so failing would keep CI red for a week through no fault of
        the repo.
        """
        return 1 if self.stale else 0


# --- discovery ------------------------------------------------------------------------------

def _split_spec(spec: str) -> tuple[str, str, str]:
    """`npm:@agentmemory/mcp@0.9.27` -> ('npm', '@agentmemory/mcp', '0.9.27').

    The version is after the LAST '@', not the first — a scoped npm package leads with one.
    """
    backend, sep, rest = spec.partition(":")
    if not sep:
        backend, rest = "mise", spec
    elif backend not in ("npm", "pipx", "github", "cargo", "go", "gem", "asdf", "ubi"):
        # An unknown prefix is not a backend — it is part of the name (mise accepts several
        # forms we do not resolve). Treat the whole thing as a mise-registered tool.
        backend, rest = "mise", spec
    name, _, version = rest.rpartition("@")
    if not name:  # no '@' at all — the schema rejects this, but never assume
        name, version = rest, ""
    return backend, name, version


def _opaque_pins_from_text(text: str, *, recipe: str, path: Path, note: str,
                           hold: str | None) -> list[Pin]:
    """Best-effort: pin-shaped literals assigned to a variable in a shell or Dockerfile body."""
    out: list[Pin] = []
    seen: set[str] = set()
    for m in _ASSIGN_RE.finditer(text):
        value = m.group(2).strip("\"'")
        if not _IMMUTABLE_LITERAL_RE.match(value) or value in seen:
            continue
        seen.add(value)
        out.append(Pin(
            recipe=recipe, file=path, spec=f"{m.group(1)}={value}", name=m.group(1),
            current=value, backend="opaque", hold=hold, note=note,
        ))
    return out


def discover_pins(recipe_dir: Path) -> list[Pin]:
    """Every pin in one recipe — resolvable ones first, then the best-effort opaque ones.

    Never raises for a recipe that fails strict validation: `update` runs across the WHOLE catalog,
    and one unloadable recipe must not blind the command to the other forty.
    """
    recipe_dir = Path(recipe_dir)
    try:
        recipe = load_recipe(recipe_dir)
    except (SchemaError, OSError):
        return []

    manifest = recipe_dir / "recipe.yaml"
    pins: list[Pin] = []

    for spec in recipe.tools:
        backend, name, current = _split_spec(spec)
        pins.append(Pin(
            recipe=recipe.name, file=manifest, spec=spec, name=name, current=current,
            backend=backend, hold=recipe.tools_hold.get(spec),
        ))

    # `install.hold` covers everything the install script fetches — the cache key and the literals
    # inside the script alike, since they are bumped as a unit after a human diff review.
    install_hold = recipe.install.hold if recipe.install else None

    if recipe.install and recipe.install.cache:
        pins.append(Pin(
            recipe=recipe.name, file=manifest, spec=recipe.install.cache,
            name="install.cache", current=recipe.install.cache, backend="opaque",
            hold=install_hold,
            note="install.cache is a synthetic content-cache key, not an upstream version",
        ))

    if recipe.install and recipe.install.script:
        script = recipe_dir / recipe.install.script
        if script.is_file():
            pins += _opaque_pins_from_text(
                script.read_text(encoding="utf-8", errors="replace"),
                recipe=recipe.name, path=script, hold=install_hold,
                note="literal pin in an install script — no backend to query",
            )

    dockerfile = recipe_dir / "Dockerfile"
    if dockerfile.is_file():
        pins += _opaque_pins_from_text(
            dockerfile.read_text(encoding="utf-8", errors="replace"),
            recipe=recipe.name, path=dockerfile, hold=None,
            note="literal pin in a Dockerfile — no backend to query",
        )

    return pins


# --- resolution -----------------------------------------------------------------------------

def _http_get(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "harnessed-update"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed https registries)
        return resp.read().decode("utf-8")


def _run_mise(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout


def _parse_ts(raw: str | None) -> datetime | None:
    """ISO-8601 as the registries emit it. npm uses a `Z` suffix that older stdlib will not take."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# `mise registry` row: `pulumi   aqua:pulumi/pulumi asdf:canha/asdf-pulumi`. Only these backends
# name the TOOL's own repo. `asdf:` names the asdf PLUGIN's repo (canha/asdf-pulumi), whose
# releases are the plugin's, not pulumi's — reading a version from it would be nonsense.
_REPO_BACKENDS = ("aqua:", "ubi:", "github:")


def mise_repo(tool: str, *, run: Callable[[list[str]], str] = _run_mise) -> str | None:
    """The GitHub `owner/repo` backing a mise-registered tool, via mise's own registry.

    This is what lets a bare `pulumi@3.251.0` obtain a publish DATE: `mise latest` returns a
    version and nothing else, but the repo it resolves to has dated releases. Deriving the mapping
    from mise means no hand-maintained tool->repo table to rot.
    """
    for line in run(["mise", "registry"]).splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != tool:   # exact name match: `pulumi` is not `kubespy`
            continue
        for token in parts[1:]:
            for prefix in _REPO_BACKENDS:
                if token.startswith(prefix):
                    repo = token[len(prefix):]
                    if repo.count("/") == 1:
                        return repo
    return None


def _github_releases(repo: str, fetch: Callable[[str], str]) -> list[Release]:
    """Published, non-draft, non-prerelease releases — newest first, as GitHub returns them.

    The LIST endpoint, not `/releases/latest`: the age gate has to be able to fall back to an
    older-but-mature release, which means seeing more than one. A prerelease or draft is not a
    shipped version, so offering one would bump the catalog onto an unreleased build.
    """
    data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=100"))
    return [
        Release(version=r["tag_name"], published=_parse_ts(r.get("published_at")))
        for r in data
        if not r.get("prerelease") and not r.get("draft")
    ]


def resolve_releases(backend: str, name: str, *,
                     fetch: Callable[[str], str] = _http_get,
                     run: Callable[[list[str]], str] = _run_mise) -> list[Release]:
    """Every known release of `name`, each WITH its publish date.

    Dates are not garnish — they are what the minimum-release-age gate is enforced on — and the
    full LIST (rather than just the newest) is what lets a too-fresh newest release fall back to a
    mature predecessor, the way pnpm does. Raises ResolveError if the backend cannot answer.

    Payload shapes verified against the live registries on 2026-07-25.
    """
    try:
        if backend == "npm":
            # The full packument, NOT `/latest`: only the packument carries `time`. The scope's '/'
            # is a real path separator here — percent-encoding it 404s.
            data = json.loads(fetch(f"https://registry.npmjs.org/{name}"))
            times = data.get("time", {})
            # Cross `versions` with `time`: `time` also holds `created`/`modified` (the only
            # non-version keys npm emits), and can retain entries for versions since unpublished.
            return [
                Release(version=v, published=_parse_ts(times.get(v)))
                for v in data.get("versions", {})
            ]
        if backend == "pipx":
            data = json.loads(fetch(f"https://pypi.org/pypi/{name}/json"))
            out: list[Release] = []
            for version, files in (data.get("releases") or {}).items():
                # A fully-yanked release keeps its key but loses its files: no date, not
                # installable, therefore not a candidate.
                if not files:
                    continue
                out.append(Release(
                    version=version,
                    published=_parse_ts(files[0].get("upload_time_iso_8601")),
                ))
            return out
        if backend == "github":
            return _github_releases(name, fetch)
        if backend == "mise":
            repo = mise_repo(name, run=run)
            if repo is None:
                # Falling back to an undated `mise latest` would offer a bump under a rule that
                # promises an age check we could not perform. Surface it instead.
                raise ResolveError(
                    f"mise registry names no aqua/ubi/github repo for {name!r}, so its release "
                    "date cannot be checked — bump it by hand after reading upstream's notes"
                )
            return _github_releases(repo, fetch)
    except ResolveError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ResolveError(f"{backend} returned an unusable payload for {name}: {exc}") from exc
    except subprocess.SubprocessError as exc:
        raise ResolveError(f"mise could not resolve {name}: {exc}") from exc
    except OSError as exc:
        raise ResolveError(f"could not reach {backend} for {name}: {exc}") from exc
    return []


def _select(pin: Pin, releases: list[Release], now: datetime, min_age_minutes: float):
    """Pick the version to offer for `pin`, pnpm-style.

    Returns (kind, finding). `kind` is the report bucket. The rule, in order:

      * only versions ABOVE the current pin are candidates — never offer a downgrade
      * with the gate off, the newest candidate wins outright
      * otherwise the newest candidate OLD ENOUGH wins, and any newer one it passed over is
        recorded so the report can explain the apparently-odd choice
      * if nothing is old enough, the newest candidate is reported as cooling — visible, not offered
      * an undated candidate is never selectable: we cannot honour the age guarantee for it
    """
    def age_days(r: Release) -> float | None:
        return None if r.published is None else (now - r.published).total_seconds() / 86400

    def finding(r: Release, **kw) -> Finding:
        # Normalise ONCE so the report shows exactly the string `apply` will write: a GitHub tag
        # arrives `v`-prefixed and the pin's own convention wins (see _match_v_prefix).
        return Finding(pin=pin, latest=_match_v_prefix(pin.current, r.version),
                       published=r.published, age_days=age_days(r), **kw)

    current_key = version_key(pin.current)
    candidates = []
    for r in releases:
        try:
            if version_key(r.version) > current_key:
                candidates.append(r)
        except (ValueError, AttributeError, TypeError):
            continue                      # an unparseable tag is not a candidate
    if not candidates:
        return "current", Finding(pin=pin, latest=pin.current)

    candidates.sort(key=lambda r: version_key(r.version))
    newest = candidates[-1]

    if min_age_minutes <= 0:
        return "stale", finding(newest)

    min_days = min_age_minutes / 1440
    safe = [r for r in candidates if (a := age_days(r)) is not None and a >= min_days]
    if safe:
        chosen = safe[-1]
        f = finding(chosen)
        if version_key(newest.version) > version_key(chosen.version):
            f.skipped_newer = _match_v_prefix(pin.current, newest.version)
            f.skipped_newer_age_days = age_days(newest)
        return "stale", f

    if all(r.published is None for r in candidates):
        return "unresolved", Finding(
            pin=pin, latest=_match_v_prefix(pin.current, newest.version),
            error=f"{newest.version} is newer, but {pin.backend} gave no publish date, so its "
                  f"release age cannot be checked against the {min_days:g}-day minimum — review "
                  "it by hand",
        )

    f = finding(newest)
    f.cooling = True
    return "cooling", f


# The `recipe` label for extra-tools pins. Not a real recipe — it is what the report prints next to
# a bump, so it has to say where the pin lives or the human cannot tell what a bump would touch.
EXTRA_TOOLS_LABEL = "base/extra-tools"


def extra_tools_default_path() -> Path:
    """The SHIPPED template that the sweep reads.

    Deliberately the tracked template, not `paths.extra_tools_path()` (the user's host file). A
    bump has to land as a reviewable diff in a PR, and pin-check.yml sweeps the catalog; the user's
    `~/.config/harnessed/extra-tools.txt` is host-local and is nobody's to rewrite.
    """
    return paths.harnessed_home() / "catalog" / "base" / "extra-tools.default.txt"


def discover_extra_tools_pins(path) -> list[Pin]:
    """Every pin in `catalog/base/extra-tools.default.txt`, as resolvable mise pins.

    Pinning this file (bd harnessed-2o9) stopped the build breaking and started it rotting: 15 pins
    that nothing was watching. This is what watches them, and it reuses `_split_spec` so a
    `dua@2.41.1` here resolves through exactly the same backend path as a recipe `tools:` entry.

    Never raises, matching `discover_pins`' own rule: `update` sweeps the whole catalog, and one
    missing or malformed file must not blind the command to every other pin. An UNPINNED entry is
    therefore skipped rather than fatal here — refusing it is the BUILD's job, where a human is
    holding the thing that broke; a crash in the sweep would just hide the recipes.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        specs = parse_extra_tools(text)
    except SchemaError:
        return []

    pins: list[Pin] = []
    for spec in specs:
        backend, name, current = _split_spec(spec)
        pins.append(Pin(
            recipe=EXTRA_TOOLS_LABEL, file=path, spec=spec, name=name,
            current=current, backend=backend,
        ))
    return pins


def build_report(recipe_dirs, *,
                 extra_tools: Path | None = None,
                 resolve: Callable[[str, str], list[Release]] | None = None,
                 now: datetime | None = None,
                 minimum_release_age_minutes: float = DEFAULT_MINIMUM_RELEASE_AGE_MINUTES
                 ) -> Report:
    """Classify every pin across `recipe_dirs`. Reads only — nothing here writes.

    `minimum_release_age_minutes` follows pnpm's `minimumReleaseAge`, unit included. Pass 0 to
    disable the gate (and with it the requirement that a release be dated at all).
    """
    if resolve is None:
        def resolve(backend, name):  # noqa: E306
            return resolve_releases(backend, name)
    now = now or datetime.now(timezone.utc)

    # The extra-tools pins ride the same classification path as recipe pins — same cooldown, same
    # hold semantics, same buckets. Anything less and `--check` would report them differently from
    # every other pin, which is how a check stops being believed.
    discovered = [pin for d in recipe_dirs for pin in discover_pins(Path(d))]
    if extra_tools is not None:
        discovered += discover_extra_tools_pins(extra_tools)

    report = Report()
    for pin in discovered:
        # Held first: a held pin is never something the user is being asked to act on, so it
        # must not also appear as unresolved noise.
        if not pin.resolvable:
            f = Finding(pin=pin, error=pin.note or "not machine-resolvable")
            (report.held if pin.hold else report.unresolved).append(f)
            continue
        try:
            releases = resolve(pin.backend, pin.name) or []
        except ResolveError as exc:
            report.unresolved.append(Finding(pin=pin, error=str(exc)))
            continue
        if not releases:
            report.unresolved.append(
                Finding(pin=pin, error=f"{pin.backend} knows no version for {pin.name}")
            )
            continue

        kind, f = _select(pin, releases, now, minimum_release_age_minutes)
        # The hold outranks the age gate: a held pin is never offered whatever its age, but it
        # is still LISTED with whatever newer version exists.
        if pin.hold and kind != "current":
            f.cooling = False
            report.held.append(f)
        else:
            getattr(report, kind).append(f)
    return report


# --- what to verify after a bump (bd harnessed-czo) -------------------------------------------

def affected_stacks(recipe_names) -> dict[str, list[str]]:
    """Stacks whose `recipes:` includes any of `recipe_names` → that stack's declared harnesses.

    "Rebuild the affected stacks" is only actionable if something names them, and a stack lists its
    recipes flatly, so this is a lookup rather than a guess.
    """
    wanted = set(recipe_names)
    out: dict[str, list[str]] = {}
    for root in paths.catalog_roots():
        stacks = root / "stacks"
        if not stacks.is_dir():
            continue
        for manifest in sorted(stacks.glob("*/stack.yaml")):
            if manifest.parent.name in out:      # user overlay wins, as everywhere else
                continue
            try:
                stack = load_stack(manifest.parent)
            except (SchemaError, OSError):
                continue
            if wanted.intersection(stack.recipes):
                out[stack.name] = list(stack.harnesses)
    return out


def verify_commands(stacks: dict[str, list[str]]) -> list[str]:
    """Literal command lines to rebuild + capability-test each affected stack.

    A stack with no declared `harnesses:` still gets a line, with a `<harness>` placeholder —
    dropping it would hide a real dependency of the bump.
    """
    lines: list[str] = []
    for stack, harnesses in stacks.items():
        for h in harnesses or ["<harness>"]:
            lines.append(f"harnessed build {stack} {h} && harnessed test {stack} {h}")
    return lines


# --- rewriting ------------------------------------------------------------------------------

def _match_v_prefix(current: str, latest: str) -> str:
    """Rewrite `latest` to use whatever `v`-prefix convention `current` already used.

    A GitHub release answers with its TAG, and tags usually carry a `v` — so `pulumi@3.251.0`
    resolves to `v3.254.0` and a naive substitution would write `pulumi@v3.254.0`, a shape that
    file never used and the tool backend may not accept. The pin's own convention is the one that
    is known to build, so it wins. (Ordering is unaffected: `version_key` strips the `v` already.)
    """
    has_v = latest[:1] in ("v", "V")
    wants_v = current[:1] in ("v", "V")
    if has_v and not wants_v:
        return latest[1:]
    if wants_v and not has_v:
        return current[0] + latest
    return latest


def _rewrite_tools_entry(manifest: Path, old_spec: str, new_spec: str) -> bool:
    """Swap one `tools:` entry, preserving comments, key order, and the mapping form.

    Round-trip mode is mandatory: catalog recipes carry more comment than YAML, and the comments
    are where the WHY lives. A safe-load/dump cycle would silently delete all of it.
    """
    yaml = YAML()  # round-trip
    yaml.preserve_quotes = True
    # Two non-obvious settings, both found by running the command against the real catalog and
    # reading the diff — a bump must produce a ONE-LINE change or a reviewer cannot see it:
    #   width   ruamel re-wraps scalars at 80 cols by default, which reflowed every long
    #           `description:` in the file. Effectively disable wrapping.
    #   indent  the catalog writes list items as `  - item` (dash at col 2). ruamel's default
    #           emits `- item` at col 0, silently re-indenting every list in the file.
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    with manifest.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    tools = data.get("tools") if isinstance(data, dict) else None
    if not tools:
        return False
    changed = False
    for i, entry in enumerate(tools):
        if isinstance(entry, dict):
            if entry.get("spec") == old_spec:
                entry["spec"] = new_spec   # in place: `hold` and its comments stay put
                changed = True
        elif entry == old_spec:
            tools[i] = new_spec
            changed = True
    if not changed:
        return False
    with manifest.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
    return True


def _rewrite_extra_tools_entry(path: Path, old_spec: str, new_spec: str) -> bool:
    """Swap one entry in the plain-text extra-tools list, preserving everything else on the line.

    A separate rewriter from `_rewrite_tools_entry` because that one is a ruamel round-tripper:
    handing it a text file would fail or corrupt it. Same motive though — the trailing
    `# du replacement` comments are where the WHY lives, so only the FIRST FIELD is replaced and
    the remainder of the line is copied verbatim.

    Matching is on the whole first field, never a substring: a substring swap would rewrite the
    `dua` inside a neighbouring `dua-cli@1.0.0` and silently corrupt a pin nobody asked to bump.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split()[0] != old_spec:
            continue
        lines[i] = line.replace(old_spec, new_spec, 1)
        changed = True
    if not changed:
        return False
    path.write_text("".join(lines), encoding="utf-8")
    return True


def apply(findings) -> list[Finding]:
    """Write the accepted bumps. Returns the findings actually rewritten.

    An opaque pin is skipped: there is no safe automated rewrite for a ref buried in shell, and
    guessing at one risks corrupting a build script. Refusing, visibly, is the correct answer.

    A cooling pin is skipped too, so the cooldown holds even if a caller passes the wrong bucket.
    """
    done: list[Finding] = []
    for f in findings:
        if not f.pin.resolvable or not f.latest or f.cooling:
            continue
        new_spec = f.pin.spec.replace(f"@{f.pin.current}", f"@{_match_v_prefix(f.pin.current, f.latest)}")
        if new_spec == f.pin.spec:
            continue
        # Dispatch on the file being written, not on the pin's label: `_rewrite_tools_entry` is a
        # YAML round-tripper and the extra-tools list is plain text. Sending one to the other is
        # not a near miss, it is a corrupted catalog file.
        rewrite = (_rewrite_tools_entry if f.pin.file.suffix in (".yaml", ".yml")
                   else _rewrite_extra_tools_entry)
        if rewrite(f.pin.file, f.pin.spec, new_spec):
            done.append(f)
    return done
