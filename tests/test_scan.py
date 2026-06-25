"""Tests for CVSS scoring and scan gate (C1 — security-critical code)."""

import pytest

from harnessed.scan import HIGH, _cvss3_base, _roundup, gate


class TestCvss3Base:
    def test_perfect_10(self):
        # CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H = 10.0
        score = _cvss3_base("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H")
        assert score == 10.0

    def test_medium_vector(self):
        # CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:N/A:N = 4.3
        score = _cvss3_base("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:N/A:N")
        assert score is not None
        assert 4.0 <= score <= 5.0

    def test_high_network_exploitable(self):
        # CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
        score = _cvss3_base("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert score is not None
        assert score >= HIGH

    def test_zero_impact(self):
        # CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N — zero impact
        score = _cvss3_base("CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N")
        assert score == 0.0

    def test_none_on_unparseable(self):
        assert _cvss3_base("not-a-cvss-vector") is None

    def test_none_on_empty(self):
        assert _cvss3_base("") is None

    def test_cvss2_returns_none(self):
        # CVSS v2 vectors start with "CVSS:2.0" — we only handle v3.
        assert _cvss3_base("CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P") is None


class TestRoundup:
    def test_already_rounded(self):
        assert _roundup(7.0) == 7.0

    def test_rounds_up(self):
        assert _roundup(7.0001) == 7.1

    def test_zero(self):
        assert _roundup(0.0) == 0.0


class TestGate:
    """gate(osv_json) returns list of HIGH+ ids; empty = pass."""

    def _make_osv(self, cve_id: str, cvss_vector: str) -> dict:
        return {
            "results": [{
                "packages": [{
                    "vulnerabilities": [{
                        "id": cve_id,
                        "severity": [{"type": "CVSS_V3", "score": cvss_vector}],
                    }]
                }]
            }]
        }

    def test_empty_osv_passes(self):
        assert gate({}) == []

    def test_empty_results_passes(self):
        assert gate({"results": []}) == []

    def test_high_finding_returned(self):
        # 9.8 = HIGH+ → returned in the list
        osv = self._make_osv("CVE-2024-9999", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        highs = gate(osv)
        assert "CVE-2024-9999" in highs

    def test_medium_finding_not_returned(self):
        # 4.3 = MEDIUM → not HIGH
        osv = self._make_osv("CVE-2024-8888", "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:N/A:N")
        assert gate(osv) == []

    def test_multiple_highs_all_returned(self):
        osv = {
            "results": [{
                "packages": [{
                    "vulnerabilities": [
                        {"id": "CVE-A", "severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]},
                        {"id": "CVE-B", "severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"}]},
                    ]
                }]
            }]
        }
        highs = gate(osv)
        assert "CVE-A" in highs
        assert "CVE-B" in highs

    def test_qualitative_high_label_returned(self):
        # No CVSS vector — only qualitative HIGH label → should trip the gate.
        osv = {
            "results": [{
                "packages": [{
                    "vulnerabilities": [{
                        "id": "GHSA-HIGH",
                        "database_specific": {"severity": "HIGH"},
                    }]
                }]
            }]
        }
        highs = gate(osv)
        assert "GHSA-HIGH" in highs

    def test_qualitative_low_label_not_returned(self):
        osv = {
            "results": [{
                "packages": [{
                    "vulnerabilities": [{
                        "id": "GHSA-LOW",
                        "database_specific": {"severity": "LOW"},
                    }]
                }]
            }]
        }
        assert gate(osv) == []
