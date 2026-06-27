# Remove the pre-restructure `scan.py` / `harnessed-tools` gating scanner

**Status:** deferred follow-up (not blocking the advisory in-image scan that shipped 2026-06-26).

## Context

The supply-chain scan is now an **advisory, in-image** layer (`catalog/base/harnessed-scan`,
emitted by `emit.write_derived_dockerfile`, surfaced by `launcher._surface_scan_report`). It never
gates the build.

A **separate, older** scan subsystem from before the host-native restructure still lives in the tree
and describes the abandoned *gating* model:

- `src/harnessed/scan.py` — `ScanError` ("the build must abort"), `run_source_scan`,
  `run_snyk_container_scan` (`snyk container test`), `run_image_scan`, Socket.dev handling,
  `--severity-threshold=high` exit-code gating.
- `src/harnessed/cli.py` — the `harnessed-tools` entrypoint (`pyproject.toml`
  `harnessed-tools = "harnessed.cli:main"`) imports/calls those functions.
- `src/harnessed/assemble.py` — `HARNESSED_NO_SCANS` / `with_scan` (this one still legitimately gates
  whether the in-image scan layer is emitted — keep that part).

It is **NOT wired into `harnessed build`** (`launcher.py` does not import `scan.py`).

## What to decide / do

1. Confirm whether anything still needs `run_image_scan_online` (the nightly online rescan) — if so,
   keep just that and drop the gating/container/source-scan + Socket.dev code.
2. Otherwise remove `scan.py`'s dead functions and the `harnessed-tools` scan subcommands.
3. Decide the fate of `harnessed-tools` itself (CLAUDE.md says "no tool container; assembly runs
   in-process" — the emit-only `cli.py` may be fully legacy).
4. Sweep remaining `Socket.dev` references kept as roadmap placeholders (`.env.schema.example`,
   `docs/guides/secrets.md`, `docs/harnessed-design.md`) — keep or remove with the decision above.

## Why deferred

Removing it is a separate, larger change with its own verification surface; the advisory model ships
correctly without touching it. The only risk it carries today is reader confusion (two scan systems,
one dead) — not incorrect behavior.
