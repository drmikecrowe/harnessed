#!/usr/bin/env bash
# Capture tests/fixtures/claude_mcp_list_output.json — the ONE thing blocking
# test_real_fixture_is_parsed_correctly (issue #250 / PR #416, B2).
#
# WHY A SCRIPT AND NOT A DOCUMENTED COMMAND: the test asserts an EXACT server-name set, so the
# capture and the assertion have to agree on which servers were reachable. Letting a human
# improvise the --mcp-config means the fixture's contents depend on whatever that machine had
# configured, and the expected set becomes unknowable. This script pins the config to exactly one
# network-free, credential-free server (`time`, the same pins as catalog/recipes/time/recipe.yaml),
# so the answer is deterministic: {"time"}. Keep _EXPECTED_SERVERS in
# tests/test_external_contracts_fixtures.py in sync with _SERVER_NAME below.
#
# *** THIS SCRIPT COSTS MONEY. NEVER WIRE IT INTO CI. ***
# `claude -p` is a real, BILLED API call. It is meant to be run BY HAND, ONCE, by a human whose
# `claude` is logged in. Its whole output is committed as tests/fixtures/claude_mcp_list_output.json,
# and every test then reads that file — so the billed call happens once in the life of the fixture
# and never again, not per-run and not per-contributor. Re-run it only when the envelope format
# actually changes. No workflow in .github/workflows/ invokes this script; keep it that way.
# (lint.yml does `shellcheck $(git ls-files '*.sh')`, which reads this file but never executes it.)
#
# It also cannot run unattended: an unauthenticated binary returns
# {"result": "Not logged in · Please run /login"} with is_error=true, which parses to an empty set
# and would silently produce a useless fixture. The guard below is what stops that from landing.
#
#   Usage:  tools/capture-claude-mcp-fixture.sh
set -euo pipefail

_SERVER_NAME="time"
_MCP_PIN="mcp==1.29.0"
_TIME_PIN="mcp-server-time@2026.7.10"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${repo_root}/tests/fixtures/claude_mcp_list_output.json"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

# ENFORCEMENT, not documentation. The header comment above says "never run this in CI"; this is the
# part that makes it true. `CI` is set by GitHub Actions and by essentially every other runner, so
# an accidental wiring-up fails loudly at the top instead of silently spending money per build.
# HARNESSED_ALLOW_BILLED_CAPTURE=1 is the deliberate override for a human who really means it.
if [[ -n "${CI:-}${GITHUB_ACTIONS:-}" && "${HARNESSED_ALLOW_BILLED_CAPTURE:-}" != "1" ]]; then
    echo "error: refusing to run under CI — 'claude -p' is a BILLED API call." >&2
    echo "       This fixture is captured once by hand and committed; CI reads the file." >&2
    exit 1
fi

command -v claude >/dev/null || { echo "error: claude not on PATH" >&2; exit 1; }

cat > "${workdir}/.mcp.json" <<EOF
{
  "mcpServers": {
    "${_SERVER_NAME}": {
      "command": "uvx",
      "args": ["--with", "${_MCP_PIN}", "${_TIME_PIN}"],
      "type": "stdio"
    }
  }
}
EOF

# The prompt is copied VERBATIM from capability._mcp_from_llm. A fixture captured with a different
# prompt would not be evidence about the format that function actually receives.
prompt='List the MCP servers currently connected (including any provided through the hatago hub). Respond with ONLY a JSON array of server name strings, e.g. ["time"]. No prose.'

echo "capturing with --strict-mcp-config (servers: ${_SERVER_NAME}) ..." >&2
# --strict-mcp-config is load-bearing: without it claude also loads the user's own MCP config and
# the captured array stops matching _EXPECTED_SERVERS.
# `|| true`: an unauthenticated claude exits 1 but still writes a well-formed envelope whose
# `result` names the problem. Let the guard below read it and say so, rather than dying on set -e
# with a bare exit code.
claude -p "${prompt}" \
  --output-format json \
  --mcp-config "${workdir}/.mcp.json" \
  --strict-mcp-config \
  < /dev/null > "${workdir}/raw.json" || true

[[ -s "${workdir}/raw.json" ]] || { echo "error: claude produced no output" >&2; exit 1; }

python3 - "${workdir}/raw.json" "${dest}" "${_SERVER_NAME}" <<'PY'
import json, subprocess, sys, datetime

raw_path, dest, server = sys.argv[1], sys.argv[2], sys.argv[3]
envelope = json.loads(open(raw_path).read())

if envelope.get("is_error"):
    sys.exit(f"error: claude returned is_error — {envelope.get('result')!r}. Run `claude /login`.")

# Parse with the PRODUCTION parser, so a fixture can never land that the code under test cannot
# read. Importing it here is the point: this is the same function the test asserts against.
sys.path.insert(0, "src")
from harnessed.capability import _names_from_llm_json  # noqa: E402

names = _names_from_llm_json(open(raw_path).read())
if names != {server}:
    sys.exit(f"error: parsed {names!r}, expected {{{server!r}}}. Fixture NOT written.")

envelope["_provenance"] = {
    "captured": datetime.date.today().isoformat(),
    "coverage_type": "real capture from an authenticated `claude` binary",
    "claude_version": subprocess.run(
        ["claude", "--version"], capture_output=True, text=True
    ).stdout.strip(),
    "command": "tools/capture-claude-mcp-fixture.sh",
    "expected_servers": [server],
    "note": "--strict-mcp-config pinned the config to one stdio server, so the set is deterministic.",
}
open(dest, "w").write(json.dumps(envelope, indent=2) + "\n")
print(f"wrote {dest} (parsed: {sorted(names)})")
PY
