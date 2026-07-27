#!/usr/bin/env python3
"""Rewrite docs/ markdown links into URLs that actually resolve on the GitHub wiki.

`docs/` is a live clone of the project's GitHub wiki, not a normal docs directory, and the wiki
serves pages under a FLAT namespace: `guides/beads.md` on disk is published at
`/wiki/beads` -- the directory is not part of the page name. A relative link therefore breaks in
two distinct ways once rendered on the wiki:

  1. `[x](guides/beads.md)` -- the wiki resolves an in-page relative path against
     raw.githubusercontent.com, so the reader gets a raw file (or a 404), not the wiki page.
  2. `[x](../../src/harnessed/launcher.py)` -- points at repo source that does not exist in the
     wiki repo at all, so it can never resolve.

Both are invisible locally, because on disk (and in a plain GitHub file view) the relative paths
are correct. They only break on the published wiki, which is the surface readers actually use.

The fix is mechanical, so it is a script rather than a documented habit:
  - a relative `.md` target inside docs/  -> WIKI_BASE/<basename without .md>
  - any other relative target (repo source, a non-.md file) -> BLOB_BASE/<path from repo root>
  - absolute URLs, bare `#anchors`, and mailto: are left alone

Anchors are preserved (`../foo.md#section` -> WIKI_BASE/foo#section).

Also checks that every guide on disk is listed in _Sidebar.md, since a new guide that nothing links
to is effectively invisible.

Usage:
    tools/wiki-links.py            # fix in place
    tools/wiki-links.py --check    # report only, exit 1 if anything would change (CI / pre-push)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WIKI_BASE = "https://github.com/drmikecrowe/harnessed/wiki"
BLOB_BASE = "https://github.com/drmikecrowe/harnessed/blob/main"
TREE_BASE = "https://github.com/drmikecrowe/harnessed/tree/main"

# Inline markdown links: [text](target). Excludes image embeds (![...]) since the wiki serves those
# from its own asset path, and a rewrite would break them.
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")

SKIP_PREFIXES = ("http://", "https://", "#", "mailto:", "<")

# Relative targets that point outside docs/ at something no longer in the repo. Collected rather
# than rewritten, and reported at the end so a stale path gets fixed by a human who knows the
# intent instead of being laundered into a tidy-looking 404.
DEAD: list[tuple[str, str]] = []


def classify(target: str, source: Path, docs: Path, repo: Path) -> str | None:
    """Return the rewritten URL for a relative link target, or None to leave it alone."""
    if target.startswith(SKIP_PREFIXES):
        return None

    path_part, _, anchor = target.partition("#")
    if not path_part:  # bare "#anchor" -- same-page link
        return None
    suffix = f"#{anchor}" if anchor else ""

    resolved = (source.parent / path_part).resolve()

    try:
        inside_docs = resolved.relative_to(docs)
    except ValueError:
        inside_docs = None

    if inside_docs is not None:
        # A directory inside docs/ has no wiki equivalent -- the wiki has no directory listing.
        # Report it rather than inventing a URL that 404s.
        if not path_part.endswith(".md"):
            return None
        return f"{WIKI_BASE}/{resolved.stem}{suffix}"

    # Outside docs/ -- this is repo content, so point at GitHub's view of it on main. A directory
    # needs /tree/ (a /blob/ URL 404s for one), so the two cases are distinguished by what is
    # actually on disk. A target that exists on neither path is reported, not rewritten: turning a
    # stale relative path into a stale absolute URL would only make the 404 harder to notice.
    try:
        rel = resolved.relative_to(repo)
    except ValueError:
        return None  # escapes the repo entirely; not ours to rewrite
    if resolved.is_dir():
        return f"{TREE_BASE}/{rel.as_posix()}{suffix}"
    if not resolved.exists():
        DEAD.append((source.name, target))
        return None
    return f"{BLOB_BASE}/{rel.as_posix()}{suffix}"


def rewrite(text: str, source: Path, docs: Path, repo: Path) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def sub(m: re.Match[str]) -> str:
        label, target = m.group(1), m.group(2)
        new = classify(target, source, docs, repo)
        if new is None or new == target:
            return m.group(0)
        changes.append((target, new))
        return f"[{label}]({new})"

    return LINK_RE.sub(sub, text), changes


def check_sidebar(docs: Path) -> list[str]:
    """Guides on disk that _Sidebar.md never links to."""
    sidebar = docs / "_Sidebar.md"
    if not sidebar.exists():
        return []
    text = sidebar.read_text()
    missing = []
    for guide in sorted((docs / "guides").glob("*.md")):
        if guide.stem not in text:
            missing.append(f"guides/{guide.name}")
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if changes are needed")
    ap.add_argument("--docs", type=Path, default=None, help="path to the wiki clone (default: <repo>/docs)")
    args = ap.parse_args()

    docs = (args.docs or Path(__file__).resolve().parent.parent / "docs").resolve()
    # The wiki clone always sits at <repo>/docs, so the repo root follows from it. Deriving it from
    # __file__ instead would be wrong whenever --docs points at a different checkout than the one
    # the script was run from (repo-source links would silently fail to rewrite).
    repo = docs.parent
    if not docs.is_dir():
        print(f"error: no docs/ wiki clone at {docs}", file=sys.stderr)
        print("hint: it is gitignored and exists only in the main checkout -- see CLAUDE.md", file=sys.stderr)
        return 2

    total = 0
    touched = 0
    for md in sorted(docs.rglob("*.md")):
        original = md.read_text()
        new_text, changes = rewrite(original, md, docs, repo)
        if not changes:
            continue
        touched += 1
        total += len(changes)
        rel = md.relative_to(docs)
        print(f"{rel}: {len(changes)} link(s)")
        for old, new in changes:
            print(f"    {old}  ->  {new}")
        if not args.check:
            md.write_text(new_text)

    missing = check_sidebar(docs)
    for m in missing:
        print(f"_Sidebar.md: no link to {m}")
    for src, target in DEAD:
        print(f"{src}: target no longer exists, left as-is -- {target}")

    verb = "would fix" if args.check else "fixed"
    print(
        f"\n{verb} {total} link(s) across {touched} file(s); "
        f"{len(missing)} guide(s) missing from the sidebar; {len(DEAD)} dead target(s)"
    )

    if args.check and total:
        return 1
    return 1 if (missing or DEAD) else 0


if __name__ == "__main__":
    raise SystemExit(main())
