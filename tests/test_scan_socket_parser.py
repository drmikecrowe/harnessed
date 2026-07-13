"""`parse_socket` in catalog/base/harnessed-scan (bd main-9ol).

The parser is embedded in a bash heredoc, so it has no import surface — these tests exec the block
out of the script and call it directly, against fixtures captured from a REAL
`socket scan view <id> --json` response.

The trap this pins down: Socket's severity vocabulary is critical / high / **middle** / low. It is
"middle", not "medium". A parser that greps for "medium" silently reports zero mediums forever,
which reads exactly like a clean scan.
"""

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "catalog" / "base" / "harnessed-scan"


@pytest.fixture(scope="module")
def parsers():
    """Exec the summary heredoc's function defs (everything above its __main__ tail)."""
    src = SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", src[src.index("HARNESSED_SCAN_REPORT"):], re.S)
    assert match, "summary heredoc not found in harnessed-scan"
    block = match.group(1)
    ns: dict = {}
    exec(block.split("with open(sys.argv[1])")[0], ns)
    return ns


# Shape captured verbatim from `socket scan view --json` (lodash@4.17.15 + minimist@1.2.0).
REAL_VIEW = {
    "ok": True,
    "data": [
        {
            "id": "internal:100000",
            "type": "generic",
            "name": "Socket SBOM Resolver",
            "alerts": [{"type": "missingLockfile", "severity": "high", "category": "supplyChainRisk"}],
        },
        {
            "type": "npm",
            "name": "minimist",
            "version": "1.2.0",
            "alerts": [
                {"type": "criticalCVE", "severity": "critical", "category": "vulnerability"},
                {"type": "mediumCVE", "severity": "middle", "category": "vulnerability"},
            ],
        },
        {
            "type": "npm",
            "name": "lodash",
            "version": "4.17.15",
            "alerts": [
                {"type": "cve", "severity": "high", "category": "vulnerability"},
                {"type": "usesEval", "severity": "middle", "category": "supplyChainRisk"},
                {"type": "urlStrings", "severity": "low", "category": "supplyChainRisk"},
            ],
        },
    ],
}


class TestParseSocket:
    def test_criticals_and_highs_are_attributed_to_their_packages(self, parsers):
        items = parsers["parse_socket"](REAL_VIEW)
        assert ("critical", "minimist") in items
        assert ("high", "lodash") in items
        assert sum(1 for s, _ in items if s == "critical") == 1
        assert sum(1 for s, _ in items if s == "high") == 1   # lodash only — see missingLockfile below

    def test_missing_lockfile_alert_is_not_reported(self, parsers):
        """We synthesize the manifest, so there is never a lockfile beside it. Socket duly flags a
        HIGH `missingLockfile` — an artifact of our own scaffolding. Report it and every scan carries
        a phantom HIGH forever, which is exactly the kind of noise that trains people to ignore scans."""
        items = parsers["parse_socket"](REAL_VIEW)
        assert not any(pkg == "Socket SBOM Resolver" for _, pkg in items)

    def test_socket_middle_maps_to_medium(self, parsers):
        """The whole point: 'middle' must not be dropped on the floor."""
        items = parsers["parse_socket"](REAL_VIEW)
        assert ("medium", "minimist") in items
        assert ("medium", "lodash") in items
        assert not any(s == "middle" for s, _ in items)

    def test_a_failed_api_response_yields_no_findings(self, parsers):
        """`ok:false` (403, bad token, quota) must read as "no data", never as "no vulnerabilities"."""
        assert parsers["parse_socket"]({"ok": False, "message": "Socket API error"}) == []

    def test_a_clean_scan_yields_no_findings(self, parsers):
        assert parsers["parse_socket"]({"ok": True, "data": [{"name": "left-pad", "alerts": []}]}) == []
