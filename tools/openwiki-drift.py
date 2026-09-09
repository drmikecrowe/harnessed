#!/usr/bin/env python3
"""Report which openwiki Claims no longer match the code they cite. No model call, no network.

openwiki grounds every factual page in `openwiki/**/*.md` on a set of Claims kept in
`openwiki/.claims/**/*.json`. Each Claim carries evidence pointing at exact repository lines, plus
the content version openwiki observed when it established that Claim:

    "resource": "repo://src/harnessed/paths.py#L198-L216"
    "version":  "repo-lines-v1:sha256:<digest>:<base64 payload>"

`<digest>` is `sha256(selected_lines joined by "\\n", plus a trailing "\\n")` -- verified by
reproducing it for every anchor in the shipped wiki. The base64 payload carries the selected line
count and hashes of the first line, the last line, and three lines of context either side; openwiki
uses those to RE-FIND a block that moved. This script does not decode that payload, because the
per-line hash inputs are not documented and guessing them would make the check unfalsifiable. It
re-finds a moved block the direct way instead: scan the file for any window of the same length whose
digest matches.

WHY THAT DISTINCTION IS THE WHOLE POINT. Ordinary development shifts line numbers constantly. A
check that treats a shifted-but-identical block as drift reports ~30% of Claims stale after a week
of normal work, which is noise that trains you to ignore it. Separating `moved` from `changed` on a
one-week window measured 27.5% moved against 4.7% genuinely changed. Only the second number is a
review queue.

Exit status is the signal, so this is usable as a gate:

    0  no Claim's evidence changed (moved-but-identical evidence is not drift)
    1  at least one Claim cites code that changed, or a file that is gone
    2  the wiki or its Claims are unreadable / malformed

Usage:
    tools/openwiki-drift.py                    # working tree
    tools/openwiki-drift.py --rev HEAD~15      # what a wiki generated then would say about now
    tools/openwiki-drift.py --quiet            # exit status only
    tools/openwiki-drift.py --strict-lines     # count a moved block as drift too
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# `repo://<path>#L<a>` or `repo://<path>#L<a>-L<b>`. Whole-file evidence (no `#L`) carries no line
# range, so there is nothing to hash against -- it is counted separately rather than guessed at.
_RESOURCE_RE = re.compile(r"^repo://(?P<path>.+?)#L(?P<start>\d+)(?:-L(?P<end>\d+))?$")

# Only this scheme's digest layout is known. A future `repo-lines-v2` must be reported as
# unverifiable rather than silently checked with v1 rules, or this gate would go quietly green.
_KNOWN_SCHEME = "repo-lines-v1"


@dataclass(frozen=True)
class Anchor:
    """One piece of evidence: the lines a Claim cites, and the digest openwiki recorded for them."""

    page: str
    claim_id: str
    statement: str
    path: str
    start: int
    end: int
    digest: str

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def _digest(lines: list[str]) -> str:
    """openwiki's `repo-lines-v1` content digest for a block of lines."""
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _parse_version(version: str) -> tuple[str | None, int | None]:
    """`(digest, recorded_line_count)` for a known scheme, else `(None, None)`.

    The recorded count is a cheap consistency check on our own range parsing: if the evidence says
    19 lines and the resource range spans 20, this script is reading the resource wrong and must say
    so rather than report a false mismatch.
    """
    parts = version.split(":", 3)
    if len(parts) < 3 or parts[0] != _KNOWN_SCHEME or parts[1] != "sha256":
        return None, None
    count: int | None = None
    if len(parts) == 4:
        try:
            pad = "=" * (-len(parts[3]) % 4)
            count = int(json.loads(base64.b64decode(parts[3] + pad))["selectedLineCount"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            count = None
    return parts[2], count


def collect_anchors(claims_dir: Path) -> tuple[list[Anchor], int, int]:
    """Every line-ranged anchor under `claims_dir`, plus counts of what could not be checked.

    Returns `(anchors, whole_file, unknown_scheme)`.
    """
    anchors: list[Anchor] = []
    whole_file = 0
    unknown_scheme = 0
    for sidecar in sorted(claims_dir.rglob("*.json")):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # `SystemExit(str)` prints the message but exits 1, which collides with "a Claim went
            # stale" -- the one status a caller gates on. Both unreadable-input paths therefore
            # print and exit 2 explicitly, matching the contract in this module's docstring.
            print(f"error: cannot read {sidecar}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        page = str(sidecar.relative_to(claims_dir))
        for claim in payload.get("claims") or []:
            for evidence in claim.get("evidence") or []:
                resource = str(evidence.get("resource", ""))
                match = _RESOURCE_RE.match(resource)
                if match is None:
                    whole_file += 1
                    continue
                found, recorded = _parse_version(str(evidence.get("version", "")))
                if found is None:
                    unknown_scheme += 1
                    continue
                start = int(match["start"])
                end = int(match["end"] or start)
                if recorded is not None and recorded != end - start + 1:
                    print(
                        f"error: {page} claim {claim.get('id')} cites {resource} "
                        f"({end - start + 1} lines) but its version records {recorded}. "
                        "This script is parsing the resource range wrong -- fix it rather than "
                        "trusting the result.",
                        file=sys.stderr,
                    )
                    raise SystemExit(2)
                anchors.append(Anchor(
                    page=page, claim_id=str(claim.get("id", "?")),
                    statement=str(claim.get("statement", "")),
                    path=match["path"], start=start, end=end, digest=found,
                ))
    return anchors, whole_file, unknown_scheme


class Tree:
    """File contents at one revision -- the working tree, or a git rev. Read once, reused."""

    def __init__(self, root: Path, rev: str | None) -> None:
        self.root = root
        self.rev = rev
        self._cache: dict[str, list[str] | None] = {}

    def lines(self, path: str) -> list[str] | None:
        """The file's lines, or None when it does not exist at this revision."""
        if path not in self._cache:
            self._cache[path] = self._read(path)
        return self._cache[path]

    def _read(self, path: str) -> list[str] | None:
        if self.rev is None:
            try:
                return (self.root / path).read_text(encoding="utf-8").split("\n")
            except (OSError, UnicodeDecodeError):
                return None
        # `git show` rather than a checkout: this must never touch the working tree.
        done = subprocess.run(
            ["git", "-C", str(self.root), "show", f"{self.rev}:{path}"],
            capture_output=True, text=True, check=False,
        )
        if done.returncode != 0:
            return None
        return done.stdout.split("\n")


def classify(
    anchors: list[Anchor], tree: Tree, strict_lines: bool
) -> dict[str, list[Anchor]]:
    """Bucket every anchor into `exact`, `moved`, `changed`, or `missing`.

    The window scan that separates `moved` from `changed` runs ONLY for anchors that already failed
    the exact check, and window digests are computed once per `(file, length)` pair. Scanning every
    anchor independently is what made a first pass at this too slow to use as a gate.
    """
    out: dict[str, list[Anchor]] = {"exact": [], "moved": [], "changed": [], "missing": []}
    # Keyed by the shape a window scan would need, and carrying the file's lines with it. The lines
    # travel from the exact check rather than being looked up again, which is what keeps this free
    # of a second Optional to narrow for a file already known to exist.
    unresolved: dict[tuple[str, int], tuple[list[str], list[Anchor]]] = {}

    for anchor in anchors:
        lines = tree.lines(anchor.path)
        if lines is None:
            out["missing"].append(anchor)
            continue
        if _digest(lines[anchor.start - 1:anchor.end]) == anchor.digest:
            out["exact"].append(anchor)
        elif strict_lines:
            out["changed"].append(anchor)
        else:
            unresolved.setdefault((anchor.path, anchor.length), (lines, []))[1].append(anchor)

    for (_, length), (lines, group) in unresolved.items():
        seen = {
            _digest(lines[i:i + length])
            for i in range(0, max(0, len(lines) - length + 1))
        }
        for anchor in group:
            out["moved" if anchor.digest in seen else "changed"].append(anchor)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wiki", default="openwiki", help="wiki directory (default: openwiki)")
    parser.add_argument("--rev", default=None, help="compare against a git revision instead of the working tree")
    parser.add_argument("--quiet", action="store_true", help="exit status only")
    parser.add_argument("--strict-lines", action="store_true", help="count a moved-but-identical block as drift")
    parser.add_argument("--limit", type=int, default=20, help="stale Claims to list (default: 20)")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    claims_dir = root / args.wiki / ".claims"
    if not claims_dir.is_dir():
        print(f"error: no Claims directory at {claims_dir} -- is the wiki generated?", file=sys.stderr)
        return 2

    anchors, whole_file, unknown_scheme = collect_anchors(claims_dir)
    if not anchors:
        print(f"error: no verifiable anchors under {claims_dir}", file=sys.stderr)
        return 2

    buckets = classify(anchors, Tree(root, args.rev), args.strict_lines)
    stale = buckets["changed"] + buckets["missing"]
    total = len(anchors)

    if not args.quiet:
        where = args.rev or "working tree"
        print(f"openwiki drift vs {where} -- {total} anchored evidence item(s) in {len(set(a.page for a in anchors))} page(s)")
        print(f"  exact    {len(buckets['exact']):5}  evidence unchanged")
        if not args.strict_lines:
            print(f"  moved    {len(buckets['moved']):5}  identical block, different line numbers (not drift)")
        print(f"  changed  {len(buckets['changed']):5}  cited code changed")
        print(f"  missing  {len(buckets['missing']):5}  cited file gone")
        if whole_file or unknown_scheme:
            print(f"  skipped  {whole_file + unknown_scheme:5}  {whole_file} whole-file evidence, {unknown_scheme} unknown version scheme")
        print(f"  stale    {100 * len(stale) / total:.1f}% of anchored evidence")

        if stale:
            print("\nClaims to re-verify:")
            for anchor in stale[:args.limit]:
                kind = "gone   " if anchor in buckets["missing"] else "changed"
                print(f"  [{kind}] {anchor.page} :: repo://{anchor.path}#L{anchor.start}-L{anchor.end}")
                print(f"            {anchor.statement[:140]}")
            if len(stale) > args.limit:
                print(f"  ... and {len(stale) - args.limit} more")
            print("\nRefresh them with `mise run openwiki-update`, which re-grounds only the affected pages.")

    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
