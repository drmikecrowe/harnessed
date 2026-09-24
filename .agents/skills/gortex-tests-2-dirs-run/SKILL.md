---
name: gortex-tests-2-dirs-run
description: "Work in the tests +2 dirs · run area — 151 symbols across 19 files (71% cohesion)"
---

# tests +2 dirs · run

151 symbols | 19 files | 71% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::dep:harnessed.launcher._runtime`
- `src/harnessed/broker.py`
- `src/harnessed/catalogseed.py`
- `src/harnessed/ctrquery.py`
- `src/harnessed/paths.py`
- `src/harnessed/update.py`
- `src/harnessed/volumes.py`
- `tests/test_build_cache_mounts.py`
- `tests/test_conftest_container_config.py`
- `tests/test_docker_userns.py`
- `tests/test_ensure_docs_wiki_clone.py`
- `tests/test_external_contracts_live.py`
- `tests/test_launcher_install.py`
- `tests/test_live_verification_debt.py`
- `tests/test_paths.py`
- `tests/test_project_scoped_services.py`
- `tests/test_recipe_tests_on_install.py`
- `tests/test_recipes_integration.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | strip, split, subprocess, run |
| `external-call::dep:harnessed.launcher._runtime` | harnessed.launcher._runtime |
| `src/harnessed/broker.py` | _status, _run, argv |
| `src/harnessed/catalogseed.py` | _ensure_docs_wiki_clone |
| `src/harnessed/ctrquery.py` | _runtime |
| `src/harnessed/paths.py` | project_path, bare_worktree_container |
| `src/harnessed/update.py` | cmd, _run_mise |
| `src/harnessed/volumes.py` | recipes, _container_stack_fingerprint, rt, image, stack |
| `tests/test_build_cache_mounts.py` | _base_image_present |
| `tests/test_conftest_container_config.py` | test_the_isolated_home_does_not_move_the_graphroot |
| `tests/test_docker_userns.py` | TestOneRuntimeDetector, capsys, test_the_two_entry_points_agree, test_the_456_repro_still_fails_the_old_way, test_ctrquery_exits_with_a_readable_error, ... |
| `tests/test_ensure_docs_wiki_clone.py` | content, test_ignores_unrelated_repo_in_cwd, tmp_path, monkeypatch, monkeypatch, ... |
| `tests/test_external_contracts_live.py` | test_parser_extracts_stack_and_harness_from_labeled_image, test_without_the_flag_node_goes_straight_to_the_upstream, running_container, labeled_image, test_the_flag_makes_node_honour_the_proxy, ... |
| `tests/test_launcher_install.py` | args, cwd, git, tmp_path, test_none_does_not_widen_for_ordinary_repo, ... |
| `tests/test_live_verification_debt.py` | TestSidecarRevival, name, tmp_path, stopped_container, test_no_scan_containers_are_left_behind, ... |
| `tests/test_paths.py` | TestBareWorktreeContainer, tmp_path, tmp_path, test_normal_repo_returns_itself, TestPrimaryWorktree, ... |
| `tests/test_project_scoped_services.py` | test_a_linked_worktree_sees_its_siblings, tmp_path |
| `tests/test_recipe_tests_on_install.py` | tmp_path, test_cavemans_shipped_test_passes_under_a_host_install |
| `tests/test_recipes_integration.py` | test_the_per_launch_profile_copy_does_not_stomp_install_written_settings, settings, tag, tmp_path, test_merge_baked_settings_reads_the_VOLUME_not_the_image, ... |

## Entry Points

- `tests/test_paths.py::TestPrimaryWorktree.test_bare_layout_resolves_non_main_worktree_to_default_branch_worktree`
- `tests/test_recipes_integration.py::test_the_per_launch_profile_copy_does_not_stomp_install_written_settings`

## Connected Communities

- **tests +2 dirs · harnessed.launcher** (16 cross-edges)
- **harnessed +3 dirs** (11 cross-edges)
- **tests +2 dirs · resolve_releases** (7 cross-edges)
- **harnessed +2 dirs · _make_entry** (6 cross-edges)
- **tests +2 dirs · McpServer** (5 cross-edges)
- **tests +2 dirs · strip** (4 cross-edges)
- **tests +3 dirs · Path** (4 cross-edges)
- **tests +3 dirs · get** (3 cross-edges)
- **harnessed +1 dirs · warn_duplicate_hooks** (3 cross-edges)
- **tests +3 dirs · startswith** (2 cross-edges)
- **harnessed +1 dirs · _top** (2 cross-edges)
- **tests +2 dirs · validate_agent_pin** (2 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)
- **harnessed +1 dirs · source_checkout** (1 cross-edges)
- **harnessed +1 dirs · _ensure_stack_volumes** (1 cross-edges)
- **tests +2 dirs · patch** (1 cross-edges)
- **tests +2 dirs · introspect_mcp** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **. +1 dirs · _recipe · . · test_launcher_init** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-371")
explore(operation:"context", task:"understand tests +2 dirs · run", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_paths.py::TestPrimaryWorktree.test_bare_layout_resolves_non_main_worktree_to_default_branch_worktree"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
