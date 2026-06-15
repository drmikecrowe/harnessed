"""Rich markdown capability report — the test output as a user artifact (design §18 / D-11).

Takes the single structured `CapabilityReport` from `capability.py` and renders a per-capability
markdown table (`capability | kind | status`) via `rich`. The SAME structured result drives the
process exit code (0 when every expected capability is present/connected, non-zero otherwise) — one
mechanism, two audiences: the user sees how healthy the build is, CI sees green/red.

`--json` emits the structured result (`CapabilityReport.to_dict`) for CI consumption. The output
carries capability NAMES + STATUS only — never config values / tokens (threat T-02-07).
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown

from .capability import MCP, CapabilityReport, CapabilityResult


def _status_cell(result: CapabilityResult) -> str:
    """The status column for one capability — names + status only, no config values."""
    if result.present:
        return "✓ connected" if result.kind == MCP else "✓ present"
    reason = result.detail or "missing"
    return f"✗ missing ({reason})"


def render_markdown(report: CapabilityReport) -> str:
    """Render the structured result as a markdown capability table (design §18 shape)."""
    lines = [
        f"## {report.stack} — capability report",
        "",
        "| capability | kind | status |",
        "|------------|------|--------|",
    ]
    for result in report.results:
        lines.append(f"| {result.name} | {result.kind} | {_status_cell(result)} |")
    if not report.results:
        lines.append("| _(none)_ | | the manifest declares no capabilities |")
    return "\n".join(lines)


def print_report(report: CapabilityReport, console: Console | None = None) -> None:
    """Print the markdown table to the terminal via rich."""
    (console or Console()).print(Markdown(render_markdown(report)))


def report_json(report: CapabilityReport) -> str:
    """The structured result as JSON (for CI consumption via --json)."""
    return json.dumps(report.to_dict(), indent=2)


def emit(
    report: CapabilityReport,
    *,
    as_json: bool = False,
    console: Console | None = None,
) -> int:
    """Render the report and return the exit code derived from the SAME structured result.

    `--json` prints the raw structured result (clean stdout for CI); otherwise the rich markdown
    table. The return value is `report.exit_code` (0 all-green, non-zero on any missing capability).
    """
    if as_json:
        # Plain stdout (no rich styling) so CI consumes a clean JSON document.
        print(report_json(report))
    else:
        print_report(report, console)
    return report.exit_code
