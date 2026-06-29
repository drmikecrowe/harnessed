# Unify the post-build `podman create`/`cp`/`rm` passes

**Status:** deferred follow-up · **Area:** build / launch · **Files:** `src/harnessed/launcher.py`
**Surfaced by:** plan-eng-review of TIER 0 (2026-06-27), performance section.

**What.** The post-build stage in `build()` (`launcher.py:~243-248`) creates a throwaway
container from the derived image more than once:

- `_merge_baked_extensions` (`launcher.py:278`) — `create` → `cp` `.claude/{skills,…}` → `rm`
- `_surface_scan_report` (`launcher.py:306`) — `create` → `cp` `scan-report.json` → `rm`
- (incoming, TIER 0 #1) settings.json extraction — another `create` → `cp` → `rm`

Each `podman create` + `rm` is ~hundreds of ms. Three passes over the **same image** is
~2x that cost wasted on every `harnessed build`.

**Why.** Pure perf/DRY. One `create`, several `cp`, one `rm` does the same work. No behavior
change. Not urgent — build is not a hot loop — but it is low-risk cleanup that compounds as
more post-build artifacts get extracted.

**Direction.** Introduce one `_with_image_container(rt, image, fn)` helper (create cid → run a
callback that does all the `cp` calls → `rm` in a `finally`), and route extensions + scan-report
+ settings through it. Keep the per-artifact functions as thin callbacks so their
single-responsibility stays readable.

**Depends on / blocked by.** Land TIER 0 #1 (settings.json merge) first — it adds the third
`cp`; unify after, so this change is a pure refactor over a known-good 3-pass baseline.

**Note.** CONCERNS.md already tracks "temp-container create/rm (minor perf)" under accept/track-only;
this is the concrete write-up of that item.
