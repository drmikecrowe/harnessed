"""The relocation contract of `tools/openwiki-drift.py`, the wiki's staleness gate.

openwiki does NOT rewrite an evidence URI when the block it cites moves. On the changed-and-moved
path `resolveLineRangeEvidence` calls `createLineRangeEvidence(input.resource, lines, changedSpan)`
— a version computed from the NEW span, carrying the OLD `repo://path#Lx-Ly` string. So the URI's
span and the payload's `selectedLineCount` legitimately disagree, and the count is the one that
describes the digest.

The script used to assert they were equal and exit 2 ("This script is parsing the resource range
wrong") on the first disagreement. That invariant was never promised, and it held only while no
cited code had moved far enough to change. Regenerating this repo's wiki across 75 commits produced
24 such anchors and took the gate from usable to dead — exit 2 is "the Claims are malformed", which
is not what had happened.

Getting the length wrong is not merely cosmetic: the window scan that separates `moved` from
`changed` scans for windows of `anchor.length`. Scan at the URI's length and the block is never
found at any offset, so every relocated Claim is reported as genuinely changed — the false-positive
flood the module docstring says makes a gate get ignored.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

# The SHIPPED script, loaded by path because its filename contains a dash and is not importable as a
# module (same reasoning as test_lint_findings.py).
_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "openwiki-drift.py"


def _load():
    spec = importlib.util.spec_from_file_location("openwiki_drift", _SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: `Anchor` is a frozen dataclass, and @dataclass resolves annotations
    # through `sys.modules[cls.__module__]`. Absent that entry it dereferences None and the import
    # dies at collection.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


drift = _load()


def _version(lines: list[str], selected_line_count: int) -> str:
    """A `repo-lines-v1` version string over `lines`, declaring `selected_line_count`.

    The count is a separate argument on purpose: the whole point is the case where it does not
    match the URI's span.
    """
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    payload = base64.b64encode(
        json.dumps({"selectedLineCount": selected_line_count}).encode("utf-8")
    ).decode("ascii")
    return f"repo-lines-v1:sha256:{digest}:{payload}"


def _claims_dir(tmp_path: Path, resource: str, version: str) -> Path:
    claims = tmp_path / "openwiki" / ".claims"
    claims.mkdir(parents=True)
    (claims / "page.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "claim_x",
                        "statement": "s",
                        "evidence": [
                            {"resource": resource, "version": version},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return claims


def test_recorded_count_wins_over_the_uri_span() -> None:
    """`length` describes the digest, so it follows `selectedLineCount`, not `#Lx-Ly`."""
    anchor = drift.Anchor(
        page="p",
        claim_id="c",
        statement="s",
        path="f.py",
        start=10,
        end=19,
        digest="d",
        recorded_length=42,
    )
    assert anchor.length == 42
    assert anchor.uri_is_stale


def test_length_falls_back_to_the_uri_span_when_no_count_is_recorded() -> None:
    """Older evidence carries no payload; the span is then all there is, and is not "stale"."""
    anchor = drift.Anchor(
        page="p",
        claim_id="c",
        statement="s",
        path="f.py",
        start=10,
        end=19,
        digest="d",
        recorded_length=None,
    )
    assert anchor.length == 10
    assert not anchor.uri_is_stale


def test_relocated_evidence_with_a_stale_uri_is_moved_not_changed(tmp_path: Path) -> None:
    """The regression that killed the gate: a real block, cited at line numbers it outgrew.

    The file holds a 5-line block at lines 21-25. The Claim cites `#L1-L3` — a stale 3-line span
    left over from before the block moved and grew — while its payload correctly records 5. Reading
    the span instead of the count scans for 3-line windows, finds nothing, and calls this `changed`.
    """
    block = ["alpha", "beta", "gamma", "delta", "epsilon"]
    source = ["pad"] * 20 + block + ["pad"] * 20
    (tmp_path / "f.py").write_text("\n".join(source) + "\n", encoding="utf-8")

    claims = _claims_dir(tmp_path, "repo://f.py#L1-L3", _version(block, len(block)))
    anchors, _, _ = drift.collect_anchors(claims)
    assert len(anchors) == 1 and anchors[0].uri_is_stale

    buckets = drift.classify(anchors, drift.Tree(tmp_path, None), strict_lines=False)
    assert [a.claim_id for a in buckets["moved"]] == ["claim_x"]
    assert buckets["changed"] == []


def test_a_disagreeing_count_no_longer_aborts_the_run(tmp_path: Path) -> None:
    """Exit 2 means "unreadable Claims". A relocated anchor must never reach that path."""
    block = ["alpha", "beta", "gamma", "delta", "epsilon"]
    (tmp_path / "f.py").write_text("\n".join(block) + "\n", encoding="utf-8")
    claims = _claims_dir(tmp_path, "repo://f.py#L1-L3", _version(block, len(block)))

    # collect_anchors used to raise SystemExit(2) here rather than return.
    anchors, _, _ = drift.collect_anchors(claims)
    assert len(anchors) == 1


def test_evidence_still_at_its_cited_lines_is_exact(tmp_path: Path) -> None:
    """The ordinary case keeps working: URI and count agree, block has not moved."""
    block = ["alpha", "beta", "gamma"]
    (tmp_path / "f.py").write_text("\n".join(block) + "\n", encoding="utf-8")
    claims = _claims_dir(tmp_path, "repo://f.py#L1-L3", _version(block, len(block)))

    anchors, _, _ = drift.collect_anchors(claims)
    assert not anchors[0].uri_is_stale
    buckets = drift.classify(anchors, drift.Tree(tmp_path, None), strict_lines=False)
    assert [a.claim_id for a in buckets["exact"]] == ["claim_x"]


def test_genuinely_changed_evidence_is_still_reported(tmp_path: Path) -> None:
    """Trusting the recorded count must not make the gate go quietly green."""
    (tmp_path / "f.py").write_text("alpha\nbeta\nREWRITTEN\n", encoding="utf-8")
    claims = _claims_dir(tmp_path, "repo://f.py#L1-L3", _version(["alpha", "beta", "gamma"], 3))

    anchors, _, _ = drift.collect_anchors(claims)
    buckets = drift.classify(anchors, drift.Tree(tmp_path, None), strict_lines=False)
    assert [a.claim_id for a in buckets["changed"]] == ["claim_x"]
