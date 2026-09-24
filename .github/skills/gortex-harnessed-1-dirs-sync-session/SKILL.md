---
name: gortex-harnessed-1-dirs-sync-session
description: "Work in the harnessed +1 dirs · sync_session area — 228 symbols across 2 files (85% cohesion)"
---

# harnessed +1 dirs · sync_session

228 symbols | 2 files | 85% cohesion

## When to Use

Use this skill when working on files in:
- `src/harnessed/aoe.py`
- `tests/test_aoe.py`

## Key Files

| File | Symbols |
|------|---------|
| `src/harnessed/aoe.py` | background, no_strict_mcp, harness, _has_profile, on_drift, ... |
| `tests/test_aoe.py` | TestWriteDispatch, tmp_path, test_terminal_view_is_left_to_the_default, test_a_row_that_never_appeared_still_reports_failure, tmp_path, ... |

## Connected Communities

- **tests +3 dirs · append** (10 cross-edges)
- **tests +2 dirs · resolve_releases** (6 cross-edges)
- **tests +3 dirs · get** (5 cross-edges)
- **tests · _sync** (4 cross-edges)
- **tests +1 dirs · CompletedProcess** (3 cross-edges)
- **harnessed +1 dirs · title_for** (2 cross-edges)
- **harnessed +1 dirs · _ensure_stack_volumes** (2 cross-edges)
- **harnessed +1 dirs · _sessions** (2 cross-edges)
- **harnessed +2 dirs · forget_stack** (2 cross-edges)
- **harnessed +3 dirs** (1 cross-edges)
- **tests +2 dirs · index** (1 cross-edges)
- **tests +1 dirs · search** (1 cross-edges)
- **. +2 dirs · _managed_block_re** (1 cross-edges)
- **tests +2 dirs · extend** (1 cross-edges)
- **harnessed +1 dirs · _is_ours** (1 cross-edges)
- **tests +3 dirs · Path** (1 cross-edges)
- **harnessed +1 dirs · _spawn** (1 cross-edges)
- **. +2 dirs · _rows** (1 cross-edges)
- **harnessed +1 dirs · group_for** (1 cross-edges)
- **harnessed +1 dirs · _bin** (1 cross-edges)
- **tests +3 dirs · startswith** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-116")
explore(operation:"context", task:"understand harnessed +1 dirs · sync_session", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
