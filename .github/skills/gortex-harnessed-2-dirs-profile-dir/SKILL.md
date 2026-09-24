---
name: gortex-harnessed-2-dirs-profile-dir
description: "Work in the harnessed +2 dirs · profile_dir area — 110 symbols across 10 files (73% cohesion)"
---

# harnessed +2 dirs · profile_dir

110 symbols | 10 files | 73% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/emit.py`
- `src/harnessed/launcher.py`
- `src/harnessed/layout.py`
- `src/harnessed/paths.py`
- `src/harnessed/staleness.py`
- `tests/test_emit.py`
- `tests/test_launch_host.py`
- `tests/test_paths.py`
- `tests/test_staleness.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | json, get |
| `src/harnessed/emit.py` | _default_omp_agent_dir, managed_block_names, path, omp_agent_dir |
| `src/harnessed/launcher.py` | harness, _prune_unlaunchable_omp_blocks, recipes, harness, stack, ... |
| `src/harnessed/layout.py` | harness, stack, _ensure_profile_dir |
| `src/harnessed/paths.py` | is_built, harness, stack, profile_dir, profiles_root, ... |
| `src/harnessed/staleness.py` | harness, root, stack_name, strict, stack_resolves, ... |
| `tests/test_emit.py` | test_managed_block_names_on_missing_file, tmp_path |
| `tests/test_launch_host.py` | TestHostAssembleIntegration, monkeypatch, monkeypatch, monkeypatch, monkeypatch, ... |
| `tests/test_paths.py` | monkeypatch, TestProfileDir, monkeypatch, monkeypatch, tmp_path, ... |
| `tests/test_staleness.py` | test_stack_resolves_false_for_an_unknown_stack, built, test_edited_recipe_is_stale, built, built, ... |

## Entry Points

- `tests/test_launch_host.py::TestSettingsPropagateWithoutARebuild.test_install_written_keys_survive_the_propagation`
- `tests/test_launch_host.py::TestSettingsPropagateWithoutARebuild.test_the_profile_still_wins_on_keys_it_defines`
- `tests/test_launch_host.py::TestSettingsPropagateWithoutARebuild.test_content_is_still_gated`
- `tests/test_launch_host.py::TestSettingsPropagateWithoutARebuild.test_settings_reach_the_home_even_when_the_stack_is_unchanged`

## Connected Communities

- **tests +2 dirs · McpServer** (10 cross-edges)
- **harnessed +3 dirs** (8 cross-edges)
- **tests · _fake_profile** (6 cross-edges)
- **tests +2 dirs · harnessed.launcher** (4 cross-edges)
- **tests +2 dirs · patch_all** (4 cross-edges)
- **tests +2 dirs · validate_agent_pin** (4 cross-edges)
- **harnessed +1 dirs · _plan_host_omp** (3 cross-edges)
- **harnessed +1 dirs · host_home** (3 cross-edges)
- **harnessed +1 dirs · test_the_launch_points_claude_c…** (2 cross-edges)
- **tests +3 dirs · get** (2 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (1 cross-edges)
- **tests +2 dirs · update** (1 cross-edges)
- **harnessed +1 dirs · _rule** (1 cross-edges)
- **tests +2 dirs · resolve_releases** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-254")
explore(operation:"context", task:"understand harnessed +2 dirs · profile_dir", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_launch_host.py::TestSettingsPropagateWithoutARebuild.test_install_written_keys_survive_the_propagation"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
