#!/usr/bin/env bash
# Real-execution layer for the supply-chain scan noise fixes.
#
# Runs the ACTUAL catalog/base/harnessed-scan against a fake $HOME and stub scanners, and asserts
# on the summary an operator would read. A green suite says the code does what the tests say; this
# says what the build prints. On this change it is the layer that settles the whole question,
# because the user's complaint was about the printed summary, not about a return value.
#
# Stubs rather than real scanners on purpose: snyk and socket need live credentials and network,
# which a reproducible evidence command must not require.
#
# Usage: tools/scan-real-run.sh [workdir]
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
SCAN="$PWD/catalog/base/harnessed-scan"

# ABSOLUTE, always. harnessed-scan runs each scanner from inside a mktemp'd manifest dir
# (`cd "$tmp" && bounded snyk …`), so a relative entry on PATH stops resolving the moment it does.
# Passed a relative logdir, the snyk stub silently became unfindable, the scan reported "0
# reporting sources", and every assertion below failed for a reason that had nothing to do with
# the code under test.
#
# FAIL CLOSED on a bad argument. There is no `set -e` here, so a failing `cd` inside the command
# substitution yields an EMPTY string, `WORK` becomes "/real-run", and the script proceeds to
# `rm -r` and `mkdir -p` at the filesystem root before failing every assertion for an unrelated
# reason. Check the directory first and refuse.
BASE="${1:-$(mktemp -d)}"
if [[ ! -d "$BASE" ]]; then
    echo "refusing to run: workdir does not exist or is not a directory: $BASE" >&2
    exit 2
fi
BASE="$(cd "$BASE" && pwd)" || exit 2
WORK="$BASE/real-run"
rm -r "$WORK" 2>/dev/null
mkdir -p "$WORK/home/.claude/skills/md-only" "$WORK/bin"
echo "# a skill with no lockfile — the normal case" >"$WORK/home/.claude/skills/md-only/SKILL.md"

# osv-scanner: exit 128 "No package sources found" — the case that used to print a ⚠ every build.
cat >"$WORK/bin/osv-scanner" <<'EOF'
#!/usr/bin/env bash
echo "No package sources found, --help for usage information." >&2
exit 128
EOF

# snyk: reports exactly the two brace-expansion advisories every published npm still bundles.
cat >"$WORK/bin/snyk" <<'EOF'
#!/usr/bin/env bash
cat <<'JSON'
{"vulnerabilities":[
 {"id":"SNYK-JS-BRACEEXPANSION-1","packageName":"brace-expansion","severity":"high",
  "identifiers":{"CVE":["CVE-2026-14257"]}},
 {"id":"SNYK-JS-BRACEEXPANSION-2","packageName":"brace-expansion","severity":"high",
  "identifiers":{"CVE":["CVE-2026-69152"]}}]}
JSON
EOF
chmod +x "$WORK/bin/osv-scanner" "$WORK/bin/snyk"

# A node globals tree for snyk to be pointed at.
NM="$WORK/home/.local/share/mise/installs/node/22/lib/node_modules/npm"
mkdir -p "$NM"
echo '{"name":"npm","version":"11.18.0"}' >"$NM/package.json"

cat >"$WORK/run.sh" <<EOF
#!/usr/bin/env bash
export HOME="$WORK/home"
export SNYK_TOKEN=stub
export PATH="$WORK/bin:/usr/bin:/bin"
unset SOCKET_CLI_API_TOKEN SOCKET_SECURITY_API_KEY
exec bash "$SCAN"
EOF

OUT="$WORK/summary.txt"
bash "$WORK/run.sh" >"$OUT" 2>&1
RC=$?
echo "--- exit=$RC"
cat "$OUT"
echo "---"

FAILED=0
check() {  # check <description> <expected-present|absent> <pattern>
    local desc="$1" mode="$2" pat="$3" found=0
    grep -qF -- "$pat" "$OUT" && found=1
    if [[ "$mode" == present && $found -eq 1 ]] || [[ "$mode" == absent && $found -eq 0 ]]; then
        echo "  ok    $desc"
    else
        echo "  FAIL  $desc (expected $mode: '$pat')"
        FAILED=$((FAILED + 1))
    fi
}

# The scan is advisory and must never gate a build, whatever it finds.
[[ $RC -eq 0 ]] || { echo "  FAIL  scan exited $RC, must always be 0"; FAILED=$((FAILED + 1)); }

# The user's original complaint, gone.
check "no spurious 'produced NO parseable output' warning" absent "produced NO parseable output"
# osv is still accounted for — silently dropping it would be the wrong fix.
check "osv reported as a reasoned skip" present "no package sources found under skills/ or commands/"
# The two unfixable advisories are excluded from the totals but named.
check "acknowledged block printed" present "acknowledged"
check "first advisory named" present "CVE-2026-14257"
check "second advisory named" present "CVE-2026-69152"
check "acknowledged package named" present "brace-expansion"
check "totals exclude them" present "0 critical · 0 high"
check "still advisory" present "0 gating"
check "all-clear line reached" present "no high/critical advisories"

# The report on disk must agree with what was printed.
python3 - "$WORK/home/.harnessed/scan-report.json" <<'PY' || FAILED=$((FAILED + 1))
import json, sys
r = json.load(open(sys.argv[1]))
assert r["totals"] == {"critical": 0, "high": 0}, r["totals"]
assert r["gating"] == 0
assert [a["id"] for a in r["acknowledged"]] == ["CVE-2026-14257", "CVE-2026-69152"], r["acknowledged"]
assert "osv" not in r["coverage"]["no_output"], r["coverage"]
print("  ok    scan-report.json agrees with the printed summary")
PY

echo
if [[ $FAILED -eq 0 ]]; then
    echo "real run: all checks passed"
else
    echo "real run: $FAILED check(s) FAILED"
fi
exit "$FAILED"
