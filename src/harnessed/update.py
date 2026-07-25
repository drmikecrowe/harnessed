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
from .schema import SchemaError, load_recipe, load_stack

__all__ = [
    "Pin", "Finding", "Release", "Report", "ResolveError",
    "discover_pins", "build_report", "apply", "resolve_latest", "version_key",
    "mise_repo", "affected_stacks", "verify_commands", "DEFAULT_COOLDOWN_DAYS",
]

# A release younger than this is never offered. A compromised or broken publish is usually yanked
# within days, so waiting a week costs nothing and closes that window (Renovate: minimumReleaseAge).
# Measured on 2026-07-25, this would have withheld 2 of the 5 bumps the command then offered —
# pulumi 3.254.0 at 2 days old, and ccstatusline 2.2.26 published the same day.
DEFAULT_COOLDOWN_DAYS = 7


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


def _github_release(repo: str, fetch: Callable[[str], str]) -> Release:
    data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
    return Release(version=data["tag_name"], published=_parse_ts(data.get("published_at")))


def resolve_latest(backend: str, name: str, *,
                   fetch: Callable[[str], str] = _http_get,
                   run: Callable[[list[str]], str] = _run_mise) -> Release | None:
    """Ask `backend` for the newest release of `name`, WITH its publish date.

    The date is not optional garnish — it is what the cooldown is enforced on, so each backend uses
    the endpoint that carries one. Raises ResolveError if the backend cannot answer.
    """
    try:
        if backend == "npm":
            # The full packument, NOT `/latest`: only the packument carries the `time` map. The
            # scope's '/' is a real path separator here — percent-encoding it 404s.
            data = json.loads(fetch(f"https://registry.npmjs.org/{name}"))
            version = data["dist-tags"]["latest"]
            return Release(version=version, published=_parse_ts(data.get("time", {}).get(version)))
        if backend == "pipx":
            data = json.loads(fetch(f"https://pypi.org/pypi/{name}/json"))
            urls = data.get("urls") or []
            return Release(
                version=data["info"]["version"],
                published=_parse_ts(urls[0].get("upload_time_iso_8601") if urls else None),
            )
        if backend == "github":
            return _github_release(name, fetch)
        if backend == "mise":
            repo = mise_repo(name, run=run)
            if repo is None:
                # Falling back to an undated `mise latest` would offer a bump under a rule that
                # promises a 7-day age check we could not perform. Surface it instead.
                raise ResolveError(
                    f"mise registry names no aqua/ubi/github repo for {name!r}, so its release "
                    "date cannot be checked — bump it by hand after reading upstream's notes"
                )
            return _github_release(repo, fetch)
    except ResolveError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        raise ResolveError(f"{backend} returned an unusable payload for {name}: {exc}") from exc
    except subprocess.SubprocessError as exc:
        raise ResolveError(f"mise could not resolve {name}: {exc}") from exc
    except OSError as exc:
        raise ResolveError(f"could not reach {backend} for {name}: {exc}") from exc
    return None


def build_report(recipe_dirs, *,
                 resolve: Callable[[str, str], "Release | None"] | None = None,
                 now: datetime | None = None,
                 cooldown_days: float = DEFAULT_COOLDOWN_DAYS) -> Report:
    """Classify every pin across `recipe_dirs`. Reads only — nothing here writes.

    `cooldown_days` is the minimum release age: anything newer lands in `cooling` rather than
    `stale`. Pass 0 to disable it (and with it the requirement that a release be dated at all).
    """
    if resolve is None:
        def resolve(backend, name):  # noqa: E306
            return resolve_latest(backend, name)
    now = now or datetime.now(timezone.utc)

    report = Report()
    for d in recipe_dirs:
        for pin in discover_pins(Path(d)):
            # Held first: a held pin is never something the user is being asked to act on, so it
            # must not also appear as unresolved noise.
            if not pin.resolvable:
                f = Finding(pin=pin, error=pin.note or "not machine-resolvable")
                (report.held if pin.hold else report.unresolved).append(f)
                continue
            try:
                rel = resolve(pin.backend, pin.name)
            except ResolveError as exc:
                report.unresolved.append(Finding(pin=pin, error=str(exc)))
                continue
            if rel is None:
                report.unresolved.append(
                    Finding(pin=pin, error=f"{pin.backend} knows no version for {pin.name}")
                )
                continue

            age = None if rel.published is None else (now - rel.published).total_seconds() / 86400
            # Normalise ONCE, here, so the report shows exactly the string `apply` will write. A
            # GitHub tag arrives `v`-prefixed; the pin's own convention wins (see _match_v_prefix).
            latest = _match_v_prefix(pin.current, rel.version)
            f = Finding(pin=pin, latest=latest, published=rel.published, age_days=age)

            # The hold outranks everything: a held pin is never offered whatever its age.
            if pin.hold:
                report.held.append(f)
            elif not f.stale:
                report.current.append(f)
            elif cooldown_days <= 0:
                report.stale.append(f)
            elif age is None:
                # Undated + a cooldown in force = a promise we cannot keep. Do not offer it.
                report.unresolved.append(Finding(
                    pin=pin, latest=rel.version,
                    error=f"{rel.version} is newer, but {pin.backend} gave no publish date, so "
                          f"its release age cannot be checked against the {cooldown_days:g}-day "
                          "cooldown — review it by hand",
                ))
            elif age < cooldown_days:
                f.cooling = True
                report.cooling.append(f)
            else:
                report.stale.append(f)
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
        if _rewrite_tools_entry(f.pin.file, f.pin.spec, new_spec):
            done.append(f)
    return done
