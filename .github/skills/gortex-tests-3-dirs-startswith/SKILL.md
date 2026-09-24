---
name: gortex-tests-3-dirs-startswith
description: "Work in the tests +3 dirs · startswith area — 113 symbols across 21 files (56% cohesion)"
---

# tests +3 dirs · startswith

113 symbols | 21 files | 56% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `catalog/recipes/mikes-universal-setup/hooks/block-dangerous-find.py`
- `src/harnessed/launchenv.py`
- `src/harnessed/launcher.py`
- `src/harnessed/schema.py`
- `src/harnessed/setupenv.py`
- `tests/test_agent_pin_lint.py`
- `tests/test_build_cache_mounts.py`
- `tests/test_docker_userns.py`
- `tests/test_dynstack.py`
- `tests/test_exec_verbs.py`
- `tests/test_install_migration_content.py`
- `tests/test_install_migration_system.py`
- `tests/test_install_script.py`
- `tests/test_launchenv.py`
- `tests/test_project_scoped_services.py`
- `tests/test_recipe_tests_on_install.py`
- `tests/test_scan_corepack_removed.py`
- `tests/test_schema.py`
- `tests/test_subprocess_timeout_audit.py`
- `tests/test_userns_properties.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | lstrip, finditer, upper, splitlines, sub, ... |
| `catalog/recipes/mikes-universal-setup/hooks/block-dangerous-find.py` | find_index, token, starting_paths_after, tokens, is_command_boundary |
| `src/harnessed/launchenv.py` | raw, _parse_plain_env_line |
| `src/harnessed/launcher.py` | known_harnesses, repos, parse_built_pairs |
| `src/harnessed/schema.py` | validate_dockerfile_not_dependent_on_install, validate_no_claude_writes, dockerfile_body, dockerfile_body, recipe, ... |
| `src/harnessed/setupenv.py` | mode, project_path, recipe, stack, bin_dir, ... |
| `tests/test_agent_pin_lint.py` | _omp_acquire_command, _codex_install_command |
| `tests/test_build_cache_mounts.py` | _base_body, TestThePnpmStoreIsNeverCached, body, _instructions, TestEveryCacheMountRestoresWhatItTook, ... |
| `tests/test_docker_userns.py` | TestTheFirewallRunnerSharesTheAgentsMapping, test_docker_runner_carries_the_same_mapping_as_the_agent, test_podman_runner_carries_none_because_the_pod_owns_it |
| `tests/test_dynstack.py` | test_manifest_is_marked_generated_in_a_comment_not_a_field, tmp_path, monkeypatch |
| `tests/test_exec_verbs.py` | test_no_launch_blocking_prompt_still_gates_on_a_bare_isatty |
| `tests/test_install_migration_content.py` | test_the_root_step_stays_in_the_dockerfile, path, test_no_migrated_dockerfile_still_writes_into_the_agent_config_dir, test_no_install_cache_can_ship_in_the_image, test_the_content_step_moved_out_of_the_dockerfile, ... |
| `tests/test_install_migration_system.py` | test_every_global_pnpm_install_carries_a_pnpm_home_redirect, test_every_recipe_with_a_root_dockerfile_step_declares_it, TestGlobalPnpmInstallsStayInsideHarnessedDirs, test_the_whole_catalog_passes |
| `tests/test_install_script.py` | TestMikesUniversalSetupMigrated, test_the_mashed_cache_key_is_gone_and_the_key_is_derived, test_an_absent_ref_aborts_before_it_fetches_anything, test_passes_the_install_lint, test_no_copy_of_any_pin_exists_to_drift, ... |
| `tests/test_launchenv.py` | TestParsePlainEnvLine, test_values_are_parsed, test_nothing_to_set_returns_none, expected, raw, ... |
| `tests/test_project_scoped_services.py` | test_new_container_is_stamped_with_its_config_hash, monkeypatch, tmp_path |
| `tests/test_recipe_tests_on_install.py` | test_no_shipped_recipe_test_reads_a_container_only_variable, test_caveman_no_longer_depends_on_a_container_only_variable |
| `tests/test_scan_corepack_removed.py` | text, strip_comments |
| `tests/test_schema.py` | test_sse_raises_with_no_manifest_prefix_when_called_directly |
| `tests/test_subprocess_timeout_audit.py` | lines, lineno, _has_marker |
| `tests/test_userns_properties.py` | args, test_without_userns_removes_every_userns_and_nothing_else |

## Connected Communities

- **harnessed +3 dirs** (17 cross-edges)
- **tests +2 dirs · strip** (15 cross-edges)
- **tests +3 dirs · append** (10 cross-edges)
- **tests +3 dirs · get** (6 cross-edges)
- **tests +2 dirs · validate_agent_pin** (4 cross-edges)
- **tests +2 dirs · _pin** (2 cross-edges)
- **tests · _recipe · test_install_migration_content** (2 cross-edges)
- **harnessed +1 dirs · _firewall_runner_argv** (2 cross-edges)
- **tests +3 dirs · split** (2 cross-edges)
- **tests +2 dirs · index** (2 cross-edges)
- **tests +2 dirs · run** (1 cross-edges)
- **tests +2 dirs · build_report** (1 cross-edges)
- **. +1 dirs · TestTheBaseImageStillProvidesPn…** (1 cross-edges)
- **tests +1 dirs · search** (1 cross-edges)
- **tests +2 dirs · InstallRef** (1 cross-edges)
- **tests +2 dirs · endswith** (1 cross-edges)
- **harnessed +1 dirs · _agent_placement_args** (1 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)
- **tests +1 dirs · validate_install_script** (1 cross-edges)
- **tests +1 dirs · _without_userns** (1 cross-edges)
- **. +1 dirs · _recipe · . · test_install_script** (1 cross-edges)
- **tests +1 dirs · install_env** (1 cross-edges)
- **tests +1 dirs · getsource** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-101")
explore(operation:"context", task:"understand tests +3 dirs · startswith", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
