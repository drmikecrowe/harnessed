---
name: gortex-tests-sync
description: "Work in the tests · _sync area — 103 symbols across 1 files (84% cohesion)"
---

# tests · _sync

103 symbols | 1 files | 84% cohesion

## When to Use

Use this skill when working on files in:
- `tests/test_aoe.py`

## Key Files

| File | Symbols |
|------|---------|
| `tests/test_aoe.py` | monkeypatch, _rec, tmp_path, _sync, proj, ... |

## Connected Communities

- **harnessed +1 dirs · sync_session** (12 cross-edges)
- **tests +3 dirs · append** (7 cross-edges)
- **tests +2 dirs · resolve_releases** (5 cross-edges)
- **tests +2 dirs · McpServer** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-112")
explore(operation:"context", task:"understand tests · _sync", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
