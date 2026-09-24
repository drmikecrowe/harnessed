---
name: gortex-2-dirs-write
description: "Work in the . +2 dirs · write area — 175 symbols across 4 files (86% cohesion)"
---

# . +2 dirs · write

175 symbols | 4 files | 86% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::dep:harnessed.launchscript`
- `src/harnessed/launchscript.py`
- `tests/test_launchscript.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | S_IMODE, stat, mkfifo |
| `external-call::dep:harnessed.launchscript` | harnessed.launchscript |
| `src/harnessed/launchscript.py` | no_strict_mcp, limit, write, harness, verb, ... |
| `tests/test_launchscript.py` | proj, proj, TestTheExcludeSurfaceGrowsPerStack, test_strict_mcp_is_the_default, test_an_untracked_sentinel_file_in_a_real_repo_is_rewritten, ... |

## Connected Communities

- **tests +3 dirs · startswith** (8 cross-edges)
- **tests +3 dirs · write_omp_identity** (5 cross-edges)
- **tests +3 dirs · split** (4 cross-edges)
- **tests +3 dirs · Path** (3 cross-edges)
- **tests +2 dirs · run** (2 cross-edges)
- **tests +3 dirs · append** (2 cross-edges)
- **tests +2 dirs · endswith** (2 cross-edges)
- **harnessed +1 dirs · _git** (2 cross-edges)
- **. +2 dirs · reconcile** (1 cross-edges)
- **harnessed +2 dirs · _make_entry** (1 cross-edges)
- **harnessed +1 dirs · script_name** (1 cross-edges)
- **tests · run_script** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-291")
explore(operation:"context", task:"understand . +2 dirs · write", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
