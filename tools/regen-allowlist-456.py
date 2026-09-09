"""Regenerate tools/mutation-allowlist-456.txt from a mutmut run log's survivors.

The allowlist must describe the PRESENT run, because `mutation-verdict-456.sh` fails on a stale
entry as well as on an unlisted survivor. Regenerating it by hand after every test change is how it
drifts; this makes it mechanical.

It only ever RECORDS what survived -- it never decides that a survivor is acceptable. The reason
text below is the classification, and it is narrow on purpose: message-string mutations only. A
survivor of any other shape must be fixed with a test, and will show up here as an entry whose
reason does not fit, which is the point at which a human should notice.

Usage: python3 tools/regen-allowlist-456.py <mutmut-run-log>
"""

from __future__ import annotations

import pathlib
import re
import sys

ALLOWLIST = pathlib.Path(__file__).parent / "mutation-allowlist-456.txt"

REASONS = {
    "harnessed.persist.x_guard_ownership":
        "error-message text only; path/cause/uid/subuid/both remediations and the bare-mapping "
        "quoting are asserted",
    "harnessed.launcher.x__preflight_runtime":
        "error-message text only; cause/uid/subuid/both remediations and exit code 1 are asserted",
    "harnessed.ctrquery.x__runtime":
        "error-message text only; the named runtimes and exit code 1 are asserted",
}


def main() -> int:
    log = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    survivors = sorted(set(re.findall(r"🙁 (harnessed\.[a-z]+\.x_[a-z_]+__mutmut_\d+)", log)))
    if not survivors:
        print("no survivors in the log -- refusing to write an empty allowlist", file=sys.stderr)
        return 1

    groups: dict[str, list[str]] = {}
    for name in survivors:
        groups.setdefault(re.sub(r"__mutmut_\d+$", "", name), []).append(name)

    unknown = sorted(set(groups) - set(REASONS))
    if unknown:
        # A new function with survivors is a CLASSIFICATION DECISION, not a regeneration. Refusing
        # here keeps this script from silently widening the allowlist to cover code nobody judged.
        print(f"unclassified function(s) with survivors: {unknown}", file=sys.stderr)
        print("add a reason to REASONS only after checking the survivors are message text only",
              file=sys.stderr)
        return 1

    header = ALLOWLIST.read_text(encoding="utf-8").split("\n#\n# Regenerate")[0]
    out = [header, "\n#\n# Regenerate: python3 tools/regen-allowlist-456.py <mutmut-run-log>\n"]
    for fn in sorted(groups):
        out.append(f"\n# {fn}: {REASONS[fn]}")
        out.extend(sorted(groups[fn], key=lambda x: int(x.rsplit("_", 1)[1])))
    ALLOWLIST.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(survivors)} classified across {len(groups)} functions -> {ALLOWLIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
