# Roadmap & triage — immediate.md + CONCERNS.md

**Date:** 2026-06-27 · **Source:** office-hours + plan-ceo-review of
[immediate.md](immediate.md) and [../codebase/CONCERNS.md](../codebase/CONCERNS.md)

This sequences the confirmed work in `immediate.md` together with a triage of
`CONCERNS.md`, **anchored to the actual near-term goal**: author context-management
tool recipes (context-mode, agentmemory, …), combine them into stacks, and test
each stack with `harnessed test`. The ordering below serves that loop. hindsight /
multi-container services are explicitly the bottom priority.

> **Strategy (CEO review, 2026-06-27):** capability-first / dogfood. The goal is *not*
> outside adoption yet (no PyPI / install-script / remote is fine for now). The dogfood
> loop is **author recipe → compose stack → `harnessed test`**. The roadmap is ranked by
> "does this serve that loop," not by immediate.md's original numbering.

---

## What the audit found (grounding)

- **99 tests pass** (`uv run --extra dev pytest` → 99 passed, 4 skipped). CONCERNS'
  "launcher.py has zero direct unit tests" is overstated — `test_launcher_install.py`
  + 7 others exist. The real gap is that **99 passing tests aren't gated by CI**, which
  makes "add CI" a ~25-line YAML, not a write-tests-first project.
- **No context-mgmt recipes exist yet** (`catalog/recipes/` = greet, gstack, ping, time,
  floating-recipe). The next feature is *authoring* them.
- **No recipe currently writes `settings.json`** — but the ones about to be authored
  (context-mode, agentmemory, hyperpowers) do, via hooks. That makes item #1 a
  prerequisite, not a cleanup. (See Reframe 1.)
- `test_scan.py` tests the dead `scan.py`; deleting the scan subsystem removes its test too.

## Three reframes that drove the ranking

1. **immediate.md #1 (settings.json clobber) is a hard prerequisite for the next feature,
   not a cheap win.** `immediate.md:18` names hyperpowers / context-mode / agentmemory as
   the recipes that lose their installer-written `settings.json` at runtime (`launcher.py:408`).
   Those are exactly the context tools being authored next, and they install hooks by writing
   `settings.json`. Author one into a stack before fixing #1 and the hook silently never fires —
   a recipe that "installs fine" but doesn't work. **Fix #1 before authoring the first context recipe.**
2. **Two CONCERNS items rise from "track-only" to real, because the loop is author→test:**
   - *Schema tolerates unknown fields silently* (`schema.py`) — a swallowed `skkills:` typo
     fails closed with no error while hand-authoring N recipes. `--strict` author mode pays off by recipe #2.
   - *`capability.py` parses instance name from stdout via regex* (`capability.py:237`) — that's
     the `harnessed test` oracle, run per stack. Harden the tool you live in.
3. **`persist` (#2) outranks `secrets` (#4) for this goal.** Memory/context tools *are*
   persistence; out-of-project state is wiped on `--fresh`, making the tool worthless across
   sessions. Secrets (#4) is *conditional* — only if a specific context MCP needs an API key
   (many are local). The office-hours "secrets→compose spine" served hindsight, not this goal.

---

## Re-ranked roadmap

### TIER 0 — before you author the first context recipe
| Item | Why now |
|------|---------|
| **#1 settings.json merge** (immediate #1) | Prerequisite: context-mode/agentmemory/hyperpowers write `settings.json` hooks; without the merge fix (`launcher.py:408`) those hooks are silently dropped at runtime. |
| **CI** (CONCERNS: no-CI) | ~25-line workflow running `uv run --extra dev pytest`. Gates 99 already-passing tests during active authoring. Cheapest high-leverage item in the list. |

### TIER 1 — harden the author → test loop
| Item | Why |
|------|-----|
| **schema `--strict` author mode** (CONCERNS: tolerant of unknown fields) | A misspelled recipe field is currently swallowed silently. With many hand-authored recipes incoming, this is a time-sink trap. |
| **`capability.py` oracle de-fragilize** (CONCERNS: regex stdout parse `capability.py:237`) | The `harnessed test <stack>` instance-name parse. Export via a machine-readable channel instead of scraping stdout. |
| **#2 persist** (immediate #2) | Context/memory tools persist state; if out-of-project it dies on `--fresh`. **Blocked on the scope-key decision** (per-project hash vs global) before code — see Decisions. |

### TIER 2 — conditional / as-needed
| Item | Trigger |
|------|---------|
| **#4 secrets injection** (immediate #4, gives #5 free) | Only when a context MCP you're wiring actually needs an env-var key. When it lands, `secrets.md` (#5) becomes accurate for free. |

### TIER 3 — background hygiene, no urgency
- **Scan-subsystem cleanup** (CONCERNS: dead scan.py, legacy harnessed-tools, "advisory never gates",
  advisory-only supply chain) — four concerns, **one decision** (see Decisions). Mostly deletion;
  tracked in `2026-06-26-remove-pre-restructure-scan-py.md`.
- **HATAGO_PORT consolidation** (CONCERNS: port-in-3-places) — `emit.py`/`capability.py` import from
  `paths.py`. Prerequisite that de-risks the Apple-container endpoint fix.
- **`_service_refs` bug + test** (CONCERNS: catalog-root bug `launcher.py:525` + missing test) — fix and test together.

### BOTTOM — explicitly deprioritized
- **#3 compose-backed multi-container services** (immediate #3) — serves the hindsight recipe, which is
  the user's lowest priority. Needs its own design doc and a new `podman compose` host dep. Revisit when
  hindsight comes back up.

---

## CONCERNS.md disposition (all 16)

**Stale — retire:** ~~hatago-mcp-hub via `pnpm dlx` (latest)~~ is **wrong**. `Dockerfile.hatago:35`
already pins `@himorishige/hatago-mcp-hub@${HATAGO_VERSION}` (`=0.0.16`, line 24). Delete the entry.
**Also correct:** CONCERNS' "launcher.py has zero direct unit tests" — overstated; 99 tests pass.

**Folded into the ranking:** scan ×4 → TIER 3 · no-CI → TIER 0 · schema tolerance → TIER 1 ·
capability.py regex → TIER 1 · HATAGO_PORT → TIER 3 · `_service_refs` bug+test → TIER 3.

**Decide (not yet scheduled):** omp agent dir rw-mounted with full host credential access
(`launcher.py:489`) — copy-on-start or ro auth files, or accept the documented trade-off.

**Accept / track-only:** ruamel pin, single hatago port (intentional), base-image rebuild (intentional),
temp-container create/rm (minor perf). Trivial: delete the stray repo-root `profiles/` dir. Web-site
drift, no-PyPI, no-install-script: real but a **separate adoption track** — and adoption is explicitly
*not* the current goal, so these stay parked with their existing todos.

---

## Decisions needed

1. **Scan (gates TIER 3 cleanup):** keep `run_image_scan_online` (nightly rescan) or not? No → delete
   the gating scanner + `harnessed-tools` CLI + `test_scan.py`. Separately: add opt-in `--strict-scans`?
2. **`persist` scope key (gates #2 / TIER 1):** per-folder, does the host target key on
   `sha1(project_path)` (project-scoped index/cache) or live at `~/.local/share/harnessed/<stack>/<name>/`
   (global personal state like a brain)? Settle the declaration shape before coding. **This is the one to
   resolve next — it gates the persist work that context/memory recipes need.**
3. **omp rw mount:** accept the trade-off, or copy-on-start / ro auth files?

## The assignment

Do **TIER 0 first** — `#1` settings.json merge and CI — *before* you author the first context-management
recipe. #1 is the difference between a context recipe that works and one that silently drops its hooks;
CI is 25 lines that protect the 99-test suite you'll be leaning on while authoring. Then resolve the
**persist scope-key decision** (#2 in Decisions), since persist is what makes a memory tool actually
remember across `--fresh`.
