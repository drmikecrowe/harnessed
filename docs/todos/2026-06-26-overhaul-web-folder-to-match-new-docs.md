---
created: 2026-06-26T00:00:00.000Z
title: Overhaul the web/ site to match the new docs
area: web
status: pending
files:
  - web/src
  - web/astro.config.mjs
  - docs/harnessed-design.md
  - README.md
---

## Problem

The `web/` Astro site has drifted from the current documentation. The docs have since
settled the core vocabulary and model (agent / recipe / service / stack / catalog, the
host-native Python CLI driving podman directly, the layered image model, the
capability-test oracle), but the site still reflects an earlier shape and no longer
matches `docs/` + `README.md`.

Canonical sources the site must align with:
- `ARCHITECTURE.md` — repo layout + vocabulary + build/launch model.
- `docs/harnessed-design.md` — the rationale (the *why*).
- `README.md` — install / build / run (the *how*).

## Solution

- Audit `web/src` against the canonical docs and list every page/section that contradicts
  or omits the current model.
- Re-derive the site's content from the docs so it can't drift again (ideally pull copy
  from the markdown sources rather than hand-maintaining a parallel copy).
- Update vocabulary, the image-layer/runtime diagrams, the CLI command table, and the
  install instructions to match `README.md`.
- Verify: build the site (`pnpm --filter ./web build`) and spot-check that the rendered
  pages agree with `ARCHITECTURE.md` / `README.md`.

Scope/decisions to settle during implementation:
- Whether the site renders directly from the repo markdown (single source of truth) or
  keeps curated landing copy that references it.
- How the install section should track the forthcoming install script (see
  [2026-06-26-plan-user-install-script]).
