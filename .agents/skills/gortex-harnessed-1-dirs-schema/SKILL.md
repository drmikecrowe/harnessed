---
name: gortex-harnessed-1-dirs-schema
description: "Work in the harnessed +1 dirs · _schema area — 108 symbols across 2 files (88% cohesion)"
---

# harnessed +1 dirs · _schema

108 symbols | 2 files | 88% cohesion

## When to Use

Use this skill when working on files in:
- `src/harnessed/launchenv.py`
- `tests/test_unproxied_secrets_warning.py`

## Key Files

| File | Symbols |
|------|---------|
| `src/harnessed/launchenv.py` | _warn_unproxied_secrets, _varlock_proxy_modes, schema_dir, schema_dir |
| `tests/test_unproxied_secrets_warning.py` | tmp_path, monkeypatch, monkeypatch, tmp_path, monkeypatch, ... |

## Connected Communities

- **harnessed +3 dirs** (11 cross-edges)
- **tests +2 dirs · strip** (4 cross-edges)
- **tests +3 dirs · append** (3 cross-edges)
- **tests +3 dirs · get** (2 cross-edges)
- **tests +3 dirs · split** (2 cross-edges)
- **tests +2 dirs · index** (1 cross-edges)
- **tests +2 dirs · _varlock_cache_clear** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **harnessed +2 dirs · declared_primitives** (1 cross-edges)
- **tests +1 dirs · CompletedProcess** (1 cross-edges)
- **tests +2 dirs · run** (1 cross-edges)
- **harnessed +2 dirs · _write** (1 cross-edges)
- **tests +3 dirs · startswith** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-431")
explore(operation:"context", task:"understand harnessed +1 dirs · _schema", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
