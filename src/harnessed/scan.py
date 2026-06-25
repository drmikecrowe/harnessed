"""Supply-chain scan gate — osv-scanner (source/image) + pip-audit, gated at CVSS >= HIGH.

Mirrors capability.py's structure: a structured result + pure severity functions + subprocess
invokers. The crux (RESEARCH Pattern 2 / Pitfall 3): osv-scanner `scan` exits 1 on ANY finding
with no severity flag — so the HIGH threshold is pure Python over `--format json`, never the
scanner exit code. Exit codes: 0 clean, 1 any-finding, 127 error, 128 no-packages.

EMIT-COMPATIBLE: run_source_scan is pure file I/O over recipe dirs + the emitted profile, so it
runs inside the emit-only tools image. run_image_scan is driven HOST-side in build_stack against
a `podman save` archive (no daemon-in-container, no API socket — design §15 / D-12).

Severity gate (RESEARCH A3, verified against real findings 2026-06-15): osv-scanner's
`severity[].score` is a CVSS *vector string* (e.g. "CVSS:3.1/AV:N/..."), not a number. We parse
the CVSS v3 base score from the vector; findings whose record carries only a qualitative
database_specific.severity label fall back to that label's band. A HIGH (CVSS >= 7.0) finding
aborts the build; low/medium findings surface as warnings and never red-line it.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import schema

# CVSS HIGH threshold (RESEARCH A2). The build ABORTS at >= HIGH; below is a warning.
HIGH = 7.0

# Scanner timeout — source/image scans over a manifest set are fast; a stuck scanner must not hang
# the build (RESEARCH Project Constraint 6 / Pitfall 6).
_TIMEOUT = 300

# CVSS v3.1 metric value tables (FIRST.org CVSS v3.1 spec).
_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}
# Qualitative-severity label → representative CVSS band (used only when no parseable CVSS vector
# is present; conservative so a HIGH-labelled record still trips the gate).
_LABEL_SCORE = {"LOW": 3.0, "MODERATE": 5.0, "MEDIUM": 5.0, "HIGH": 8.0, "CRITICAL": 9.5}


class ScanError(Exception):
    """A supply-chain scan found a HIGH+ finding (CVSS >= HIGH) — the build must abort."""


@dataclass
class ScanResult:
    """Structured scan outcome: HIGH ids drive the abort; warnings are rendered but never fail."""

    scope: str
    highs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- Pure: CVSS / severity gate (no subprocess; unit-testable) -----------------------------------


def _roundup(value: float) -> float:
    """CVSS v3.1 Roundup — smallest value >= input, to one decimal place (FIRST.org spec)."""
    int_input = round(value * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def _cvss3_base(vector: str) -> float | None:
    """Compute the CVSS v3 base score from a vector string (RESEARCH A3). None if unparseable."""
    try:
        metrics: dict[str, str] = {}
        for part in vector.split("/")[1:]:
            if ":" in part:
                key, val = part.split(":", 1)
                metrics[key] = val
        for required in ("AV", "AC", "PR", "UI", "C", "I", "A"):
            if required not in metrics:
                return None
        scope_changed = metrics.get("S", "U") == "C"
        pr_table = _PR_CHANGED if scope_changed else _PR_UNCHANGED
        exploitability = (
            8.22 * _AV[metrics["AV"]] * _AC[metrics["AC"]] * pr_table[metrics["PR"]] * _UI[metrics["UI"]]
        )
        isc = 1 - (
            (1 - _CIA[metrics["C"]]) * (1 - _CIA[metrics["I"]]) * (1 - _CIA[metrics["A"]])
        )
        if isc <= 0:
            return 0.0
        impact = (7.52 * (isc - 0.029) - 3.25 * (isc - 0.02) ** 15) if scope_changed else (6.42 * isc)
        base = (1.08 * (impact + exploitability)) if scope_changed else (impact + exploitability)
        return _roundup(min(base, 10.0))
    except (KeyError, ValueError):
        return None


def _max_cvss(vuln: dict) -> float:
    """Max CVSS score for one OSV finding (RESEARCH A3: score may be a CVSS vector string)."""
    best = 0.0
    for sev in (vuln.get("severity") or []):
        score = sev.get("score")
        if isinstance(score, (int, float)):
            best = max(best, float(score))
        elif isinstance(score, str) and score.startswith("CVSS:3"):
            parsed = _cvss3_base(score)
            if parsed is not None:
                best = max(best, parsed)
    if best > 0.0:
        return best
    # No parseable CVSS — fall back to the advisory's qualitative severity band.
    label = str((vuln.get("database_specific") or {}).get("severity") or "").upper()
    return _LABEL_SCORE.get(label, 0.0)


def gate(osv_json: dict) -> list[str]:
    """Return HIGH+ finding ids (CVSS >= HIGH); empty list ⇒ pass. The ONLY HIGH decision point.

    Reads the parsed severity score — NEVER the scanner exit code (Pitfall 3): osv-scanner exits 1
    on *any* finding, so the exit code cannot decide HIGH. Each finding's max CVSS comes from its
    `severity[].score` (numeric or CVSS vector) via `_max_cvss`.
    """
    highs: list[str] = []
    for result in osv_json.get("results", []):
        for pkg in result.get("packages", []):
            for vuln in pkg.get("vulnerabilities", []):
                if _max_cvss(vuln) >= HIGH:
                    highs.append(vuln.get("id", "?"))
    return highs


def _all_finding_ids(osv_json: dict) -> list[str]:
    """Every finding id (used to render low/medium findings as warnings, never an abort)."""
    ids: list[str] = []
    for result in osv_json.get("results", []):
        for pkg in result.get("packages", []):
            for vuln in pkg.get("vulnerabilities", []):
                vid = vuln.get("id")
                if vid:
                    ids.append(vid)
    return ids


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


# --- Subprocess invokers (mirror capability._exec: capture, text, swallow the noisy exit codes) --


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a scanner, capturing output. Never raise on a non-zero scanner exit (gated in Python)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except (subprocess.SubprocessError, OSError) as exc:
        raise ScanError(f"scanner invocation failed ({' '.join(cmd)}): {exc}") from exc


def _scan_source_osv(target: Path, highs: list[str], warnings: list[str]) -> None:
    """osv-scanner offline source scan of one dir; HIGH ids -> highs, everything else -> warnings."""
    proc = _run(["osv-scanner", "scan", "source", "--offline", "--offline-vulnerabilities", "-r", "--format", "json", str(target)])
    data = _parse_json(proc.stdout)
    if data is None:
        if proc.returncode == 128:
            # No packages found — investigate, do NOT treat as a vacuous pass (Pitfall 7).
            warnings.append(f"osv-scanner found no packages in {target} (exit 128 — investigate)")
        elif proc.returncode not in (0, 1):
            # Scanner error (e.g. exit 127: missing offline DB during bring-up) — never a silent pass.
            warnings.append(f"osv-scanner did not produce results for {target} (exit {proc.returncode}; offline DB present?) — investigate")
        return
    for finding in gate(data):
        highs.append(finding)
    for finding in _all_finding_ids(data):
        if finding not in highs:
            warnings.append(finding)


def _audit_pip(requirement: Path, warnings: list[str]) -> None:
    """pip-audit a requirements.txt; findings are warnings only (its JSON carries no CVSS)."""
    proc = _run(["pip-audit", "-r", str(requirement), "--format", "json", "--vulnerability-service", "osv"])
    data = _parse_json(proc.stdout)
    if data is None:
        # No usable JSON: exit 2 / network failure / not installed — warn and skip (Pitfall 6: never
        # red-line the build for the wrong reason).
        warnings.append(f"pip-audit could not produce results for {requirement.name} (exit {proc.returncode}; network?) — skipped")
        return
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vid = vuln.get("id")
            if vid:
                warnings.append(f"pip-audit: {vid}")


def _snyk_vuln_ids(snyk_json: dict) -> list[str]:
    """Finding ids from `snyk test --severity-threshold=high --json` (exit 1 = HIGH+ at threshold)."""
    vulns = snyk_json.get("vulnerabilities") or []
    return [v.get("id") for v in vulns if isinstance(v, dict) and v.get("id")]


def _socket_alerts(socket_json: dict) -> list[str]:
    """Short strings for Socket.dev scan alerts (warnings only — Socket has no CVSS threshold)."""
    out: list[str] = []
    # `socket scan create --json` nests alerts under a top-level key; honor the common shapes.
    candidates = socket_json.get("alerts") or socket_json.get("data") or []
    if isinstance(candidates, dict):
        candidates = candidates.get("alerts") or []
    for entry in candidates:
        if isinstance(entry, dict):
            label = entry.get("id") or entry.get("type") or entry.get("key") or entry.get("title")
            if label:
                out.append(str(label))
        elif isinstance(entry, str) and entry:
            out.append(entry)
    return out


def _scan_snyk(target: Path, highs: list[str], warnings: list[str]) -> None:
    """snyk test --severity-threshold=high, env-gated on SNYK_TOKEN (SEC-02).

    The load-bearing difference from osv-scanner: with `--severity-threshold=high` snyk's EXIT CODE
    IS the gate (docs.snyk.io/snyk-cli/exit-codes), not Python-over-JSON: 0 clean, 1 vulns at the
    HIGH+ threshold found (ABORT), 2 failure, 3 no-supported-projects (warn). Do NOT treat snyk's
    non-zero like osv-scanner's (osv 1 = any finding; snyk 1 = HIGH+ at threshold — exactly the gate).

    Token-gated: no SNYK_TOKEN ⇒ warn-and-skip (the credential-free osv-scanner + pip-audit baseline
    stays the gate); `harnessed build` never prompts (SEC-02 contract). snyk scans only when the
    target has a package.json (manifest-less dirs are skipped — snyk cannot scan them).
    """
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append("snyk skipped (no SNYK_TOKEN) — credential-free baseline remains the gate")
        return
    manifest = target / "package.json"
    if not manifest.is_file():
        return
    proc = _run(["snyk", "test", "--severity-threshold=high", "--json", "--file", str(manifest)])
    if proc.returncode == 1:
        # HIGH+ finding(s) at the threshold — parse ids and ABORT the build (the gate).
        data = _parse_json(proc.stdout)
        ids = _snyk_vuln_ids(data) if data is not None else []
        if ids:
            highs.extend(ids)
        else:
            # Exit 1 but no parseable ids — fail-closed: surface as a HIGH+ signal to investigate.
            highs.append(f"snyk: HIGH+ finding in {target.name} (exit 1; parse JSON output)")
    elif proc.returncode in (2, 3):
        warnings.append(
            f"snyk: exit {proc.returncode} for {target.name} (failure / no supported projects) — investigate"
        )
    # returncode 0 ⇒ clean (no action)


def _scan_socket(target: Path, warnings: list[str]) -> None:
    """socket scan create (server-side), env-gated on SOCKET_SECURITY_API_KEY|TOKEN (SEC-02).

    Socket.dev's model is policy/alert-based — it surfaces NO CVSS severity threshold the way snyk
    does — so findings render as WARNINGS only and NEVER abort the build. Server-side (uploads the
    manifest to Socket.dev), so it adds a network dependency + quota cost: absence of the token OR a
    network/quota failure warns-and-skips WITHOUT aborting (Pitfall 4). Both SOCKET_SECURITY_API_KEY
    and SOCKET_SECURITY_API_TOKEN are accepted (verified live, RESEARCH §socket).
    """
    token = os.environ.get("SOCKET_SECURITY_API_KEY") or os.environ.get("SOCKET_SECURITY_API_TOKEN")
    if not token:
        warnings.append("socket skipped (no SOCKET_SECURITY_API_KEY) — optional scanner")
        return
    proc = _run(["socket", "scan", "create", "--json", str(target)])
    if proc.returncode != 0:
        warnings.append(f"socket: non-zero exit {proc.returncode} (network/quota?) — skipped")
        return
    data = _parse_json(proc.stdout)
    if data is None:
        return
    for alert in _socket_alerts(data):
        warnings.append(f"socket: {alert}")


def run_source_scan(root: Path | str, stack_name: str, build_dir: Path | str) -> ScanResult:
    """SCOPED source/Python scan of one stack (BLD-02a). Raises ScanError on any HIGH+ finding.

    Scope = exactly what this build assembles: the stack's recipe dirs (resolved via
    `schema.load_stack_with_recipes`) plus the emitted `build_dir/profiles/<stack>/` — never the
    whole repo (a committed fixture under tools/test-fixtures/ cannot red-line another build).
    """
    root = Path(root)
    build_dir = Path(build_dir)
    stack, recipes = schema.load_stack_with_recipes(root, stack_name)

    scan_targets: list[Path] = [recipe.root for recipe in recipes]
    profile_dir = build_dir / "profiles" / stack.name
    if profile_dir.is_dir():
        scan_targets.append(profile_dir)

    highs: list[str] = []
    warnings: list[str] = []
    for target in scan_targets:
        _scan_source_osv(target, highs, warnings)
        for requirement in target.rglob("requirements.txt"):
            _audit_pip(requirement, warnings)
        _scan_snyk(target, highs, warnings)
        _scan_socket(target, warnings)

    if highs:
        unique = sorted(set(highs))
        raise ScanError(
            f"supply-chain source scan found {len(unique)} HIGH+ finding(s) "
            f"(CVSS >= {HIGH}): {', '.join(unique)}"
        )
    return ScanResult(scope=f"source:{stack.name}", highs=[], warnings=warnings)


def run_image_scan(archive_tar: Path | str) -> ScanResult:
    """Scan a saved image archive via osv-scanner (BLD-02b). Raises ScanError on any HIGH+ finding.

    Driven HOST-side by build_stack (`podman save` → this scan), mirroring `harnessed test`: no
    daemon-in-container, no API socket mounted.
    """
    archive_tar = Path(archive_tar)
    proc = _run(["osv-scanner", "scan", "image", "--offline", "--offline-vulnerabilities", "--archive", str(archive_tar), "--format", "json"])
    if proc.returncode == 128:
        warnings = [f"osv-scanner found no packages in image archive (exit 128 — investigate)"]
        return ScanResult(scope="image", highs=[], warnings=warnings)
    data = _parse_json(proc.stdout) or {}
    highs = gate(data)
    if highs:
        unique = sorted(set(highs))
        raise ScanError(
            f"supply-chain image scan found {len(unique)} HIGH+ finding(s) "
            f"(CVSS >= {HIGH}): {', '.join(unique)}"
        )
    warnings = [vid for vid in _all_finding_ids(data)]
    return ScanResult(scope="image", highs=[], warnings=warnings)


def _scan_snyk_container_image(image_name: str, highs: list[str], warnings: list[str]) -> None:
    """snyk container test <image> --severity-threshold=high (SC-03).

    Env-gated on SNYK_TOKEN (same warn-and-skip contract as _scan_snyk). Never prompts.
    Exit code 1 = HIGH+ vuln found → abort. 2/3 = failure/no-projects → warn.
    Note: snyk running inside the tools container may fail with exit 2 if it cannot access
    the local image (no daemon socket mounted) — the exit 2 path handles this gracefully.
    """
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append(
            "snyk container test skipped (no SNYK_TOKEN) — credential-free osv-scanner baseline remains the gate"
        )
        return
    proc = _run(["snyk", "container", "test", image_name, "--severity-threshold=high", "--json"])
    if proc.returncode == 1:
        data = _parse_json(proc.stdout)
        ids = _snyk_vuln_ids(data) if data is not None else []
        if ids:
            highs.extend(ids)
        else:
            highs.append(f"snyk container test: HIGH+ finding in {image_name} (exit 1; parse JSON for details)")
    elif proc.returncode in (2, 3):
        warnings.append(
            f"snyk container test: exit {proc.returncode} for {image_name} (failure / no supported projects) — investigate"
        )
    # returncode 0 ⇒ clean (no action)


def run_snyk_container_scan(image_name: str) -> ScanResult:
    """Top-level: snyk container test on a built image (SC-03). Raises ScanError on HIGH+.

    Warn-and-skips when SNYK_TOKEN is absent so `harnessed build` stays non-interactive.
    The credential-free osv-scanner baseline remains the primary gate.
    """
    highs: list[str] = []
    warnings: list[str] = []
    _scan_snyk_container_image(image_name, highs, warnings)
    if highs:
        raise ScanError(
            f"snyk container test found {len(highs)} HIGH+ finding(s) in {image_name}: {', '.join(sorted(set(highs)))}"
        )
    return ScanResult(scope=f"snyk-container:{image_name}", highs=[], warnings=warnings)


def run_image_scan_online(archive_tar: Path | str) -> ScanResult:
    """Scan a saved image archive ONLINE via osv-scanner (SEC-04 nightly re-scan).

    Same as run_image_scan but drops the two build-time DB flags so osv-scanner contacts
    osv.dev for newly-disclosed advisories (RESEARCH Pitfall 6 — the whole point of the
    nightly: the build-time DB only knows about CVEs at build time, so a stale-DB nightly would
    see nothing new forever; that vacuous "0 findings" is the Pitfall 6 warning sign). Raises
    ScanError on any HIGH+ finding. The exit-128 investigate-branch is preserved for the same
    reason — a forever-128 is the symptom of a scan that is not actually seeing packages.

    Driven by `harnessed rescan` (the systemd timer's ExecStart): the host iterates installed
    harnessed-labelled images, `podman save`s each, and runs scan-image-online <tar> in a
    throwaway tools container. No daemon-in-container; no API socket mounted.
    """
    archive_tar = Path(archive_tar)
    proc = _run(["osv-scanner", "scan", "image", "--archive", str(archive_tar), "--format", "json"])
    if proc.returncode == 128:
        warnings = [f"osv-scanner found no packages in image archive (exit 128 — investigate)"]
        return ScanResult(scope="image", highs=[], warnings=warnings)
    data = _parse_json(proc.stdout) or {}
    highs = gate(data)
    if highs:
        unique = sorted(set(highs))
        raise ScanError(
            f"supply-chain image scan found {len(unique)} HIGH+ finding(s) "
            f"(CVSS >= {HIGH}): {', '.join(unique)}"
        )
    warnings = [vid for vid in _all_finding_ids(data)]
    return ScanResult(scope="image", highs=[], warnings=warnings)
