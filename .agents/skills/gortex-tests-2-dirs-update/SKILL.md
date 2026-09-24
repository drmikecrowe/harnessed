---
name: gortex-tests-2-dirs-update
description: "Work in the tests +2 dirs · update area — 119 symbols across 14 files (78% cohesion)"
---

# tests +2 dirs · update

119 symbols | 14 files | 78% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/assemble.py`
- `src/harnessed/paths.py`
- `src/harnessed/staleness.py`
- `tests/test_aoe.py`
- `tests/test_host_run_recipes.py`
- `tests/test_launch_host.py`
- `tests/test_launch_secrets.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_no_strict_mcp_config.py`
- `tests/test_paths_generated_root.py`
- `tests/test_recipe_env.py`
- `tests/test_recipe_hash.py`
- `tests/test_staleness.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | update |
| `src/harnessed/assemble.py` | recipes, compute_recipe_hash, stack_yaml |
| `src/harnessed/paths.py` | list_catalog_stacks |
| `src/harnessed/staleness.py` | stack_name, _feed_dir, compute_stamp, root, root, ... |
| `tests/test_aoe.py` | fake_sync, group, no_strict_mcp, project_path, background, ... |
| `tests/test_host_run_recipes.py` | tmp_path, test_the_project_path_is_a_positional_in_the_recipe_form_too, monkeypatch |
| `tests/test_launch_host.py` | env, env, argv, argv, fake_execvpe, ... |
| `tests/test_launch_secrets.py` | file, env, argv, fake_execvpe |
| `tests/test_launcher_timeouts.py` | wait, a, __init__, kill, k, ... |
| `tests/test_no_strict_mcp_config.py` | env, file, fake_execvpe, argv |
| `tests/test_paths_generated_root.py` | tmp_path, monkeypatch, test_generated_stacks_are_enumerated |
| `tests/test_recipe_env.py` | argv, file, env, fake_execvpe |
| `tests/test_recipe_hash.py` | name, tmp_path, services, _write_recipe, tmp_path, ... |
| `tests/test_staleness.py` | built, test_stamp_deterministic |

## Entry Points

- `tests/test_recipe_hash.py::TestReconcileStacks.test_rebuilds_only_stale_or_missing_stacks`

## Connected Communities

- **tests +3 dirs · append** (10 cross-edges)
- **tests +3 dirs · get** (4 cross-edges)
- **harnessed +3 dirs** (3 cross-edges)
- **harnessed +2 dirs · declared_primitives** (2 cross-edges)
- **tests +2 dirs · InstallRef** (2 cross-edges)
- **tests +1 dirs · Recipe** (2 cross-edges)
- **tests +1 dirs · CompletedProcess** (1 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-42")
explore(operation:"context", task:"understand tests +2 dirs · update", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_recipe_hash.py::TestReconcileStacks.test_rebuilds_only_stale_or_missing_stacks"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
