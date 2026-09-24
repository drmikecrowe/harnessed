---
name: gortex-harnessed-launcher
description: "Work in the . · harnessed.launcher area — 100 symbols across 1 files (100% cohesion)"
---

# . · harnessed.launcher

100 symbols | 1 files | 100% cohesion

## When to Use

Use this skill when working on files in:
- ``

## Key Files

| File | Symbols |
|------|---------|
| `` | split, _svc_stacks_from_instances, _say, _catalog_base, _script_env, ... |

## How to Explore

```
analyze(operation:"communities", id:"community-18")
explore(operation:"context", task:"understand . · harnessed.launcher", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
