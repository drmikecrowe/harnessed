"""Supply-chain scan gate — osv-scanner (source/image) + pip-audit, gated at CVSS >= HIGH.

Mirrors capability.py's structure: a structured result + pure severity functions + subprocess
invokers. The crux (RESEARCH Pattern 2 / Pitfall 3): osv-scanner `scan` exits 1 on ANY finding
with no severity flag — so the HIGH threshold is pure Python over `--format json`, never the
scanner exit code. Exit codes: 0 clean, 1 any-finding, 127 error, 128 no-packages.

ONLINE RE-SCAN: run_image_scan_online is driven HOST-side by `harnessed rescan` (the SEC-04
nightly systemd timer) against a `podman save` archive — it contacts osv.dev for advisories
disclosed after build time (no daemon-in-container, no API socket — design §15 / D-12).

Severity gate (RESEARCH A3, verified against real findings 2026-06-15): osv-scanner's
`severity[].score` is a CVSS *vector string* (e.g. "CVSS:3.1/AV:N/..."), not a number. We parse
the CVSS v3 base score from the vector; findings whose record carries only a qualitative
database_specific.severity label fall back to that label's band. A HIGH (CVSS >= 7.0) finding
aborts the build; low/medium findings surface as warnings and never red-line it.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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


def run_image_scan_online(archive_tar: Path | str) -> ScanResult:
    """Scan a saved image archive ONLINE via osv-scanner (SEC-04 nightly re-scan).

    Drops the offline build-time DB flags so osv-scanner contacts
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
        warnings = ["osv-scanner found no packages in image archive (exit 128 — investigate)"]
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
