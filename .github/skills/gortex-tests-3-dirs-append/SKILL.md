---
name: gortex-tests-3-dirs-append
description: "Work in the tests +3 dirs · append area — 309 symbols across 50 files (59% cohesion)"
---

# tests +3 dirs · append

309 symbols | 50 files | 59% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/capability.py`
- `src/harnessed/catalogseed.py`
- `src/harnessed/dynstack.py`
- `src/harnessed/emit.py`
- `src/harnessed/launchenv.py`
- `src/harnessed/mounts.py`
- `src/harnessed/paths.py`
- `src/harnessed/prose.py`
- `src/harnessed/report.py`
- `src/harnessed/schema.py`
- `src/harnessed/setupenv.py`
- `tests/conftest.py`
- `tests/test_adhoc_launch_is_not_persisted.py`
- `tests/test_aoe.py`
- `tests/test_backend_seam.py`
- `tests/test_broker_launch_gate.py`
- `tests/test_build_cache_mounts.py`
- `tests/test_capability_mcp_poll.py`
- `tests/test_catalog_local_restored.py`
- `tests/test_ctrquery_timeouts.py`
- `tests/test_docker_userns.py`
- `tests/test_dynstack.py`
- `tests/test_emit.py`
- `tests/test_exec_verbs.py`
- `tests/test_external_contracts_fixtures.py`
- `tests/test_hatago_npm_pin.py`
- `tests/test_host_run_recipes.py`
- `tests/test_install_migration_system.py`
- `tests/test_launch_secrets.py`
- `tests/test_launchenv.py`
- `tests/test_launcher_install.py`
- `tests/test_launcher_parallel_build.py`
- `tests/test_launcher_scan.py`
- `tests/test_launcher_shared_images.py`
- `tests/test_launcher_test_command.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_launchscript.py`
- `tests/test_mcp_remote_auth.py`
- `tests/test_mint_race.py`
- `tests/test_paths_generated_root.py`
- `tests/test_prose_lint.py`
- `tests/test_recipes_integration.py`
- `tests/test_rescan_credentialed.py`
- `tests/test_scan_corepack_removed.py`
- `tests/test_schema_thread_safety.py`
- `tests/test_setup_notice.py`
- `tests/test_tools_field_parity.py`
- `tools/mutants_391_svcstate.py`
- `tools/verify-move.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | append, unlink, fdopen, split, chmod, ... |
| `src/harnessed/capability.py` | build_report, stack_name, expected, mcp_miss_remediation, LiveCapabilities, ... |
| `src/harnessed/catalogseed.py` | _update_agent_dirs, _update_recipe_dirs |
| `src/harnessed/dynstack.py` | mint, extends, recipes, services |
| `src/harnessed/emit.py` | profile_dir, write_derived_dockerfile, stack_name, recipes, harness |
| `src/harnessed/launchenv.py` | project_path, _normalize_plain_env_file, schema_dir, src, _varlock_resolve_env_file, ... |
| `src/harnessed/mounts.py` | broker, _mcp_remote_pasta_net_args, _oauth_callback_ports, net, servers, ... |
| `src/harnessed/paths.py` | list_catalog, kind, generated_catalog_root, catalog_roots |
| `src/harnessed/prose.py` | lint_paths, _line_of, errors, text, targets, ... |
| `src/harnessed/report.py` | report, render_markdown, _status_cell, result |
| `src/harnessed/schema.py` | manifest, _parse_ssh_keys, raw_keys, text, text, ... |
| `src/harnessed/setupenv.py` | recipes, _pending_setup_scripts, project_path |
| `tests/conftest.py` | terminalreporter, _all_skips |
| `tests/test_adhoc_launch_is_not_persisted.py` | test_the_second_launch_of_one_recipe_set_is_still_adhoc, monkeypatch, monkeypatch, tmp_path, test_an_ordinary_stack_still_persists, ... |
| `tests/test_aoe.py` | tmp_path, monkeypatch, test_no_op_without_aoe, monkeypatch, test_sync_runs_nothing_when_unavailable |
| `tests/test_backend_seam.py` | test_attach_provisioning_does_not_need_the_home, tmp_path, monkeypatch |
| `tests/test_broker_launch_gate.py` | test_no_varlock_subprocess_runs_at_all, tmp_path, monkeypatch, no_global_schema |
| `tests/test_build_cache_mounts.py` | tmp_path, test_a_stack_with_no_recipes_emits_no_cache_mounts |
| `tests/test_capability_mcp_poll.py` | TestTheReportCarriesNoChildProcessOutput, test_a_missing_server_points_at_the_log_instead_of_quoting_it, test_nothing_reads_the_hub_log_into_the_process, _never_ready, _instance, ... |
| `tests/test_catalog_local_restored.py` | recording_symlink_to, target, kw, a |
| `tests/test_ctrquery_timeouts.py` | _fake_bounded, timeout, cmd, warn, kw |
| `tests/test_docker_userns.py` | a, k, _run, cmd, cmd, ... |
| `tests/test_dynstack.py` | monkeypatch, tmp_path, monkeypatch, monkeypatch, test_carries_explicit_services, ... |
| `tests/test_emit.py` | tmp_path, tmp_path, test_emits_the_from_line, test_no_scan_layer_is_emitted |
| `tests/test_exec_verbs.py` | argv, _never_returns, _f |
| `tests/test_external_contracts_fixtures.py` | kw, a, _fail_if_called |
| `tests/test_hatago_npm_pin.py` | test_derived_dockerfile_never_clones_or_builds_hatago, TestDerivedImageCarriesNoHatagoLayer, tmp_path, tmp_path, test_write_derived_dockerfile_no_longer_takes_a_hatago_override |
| `tests/test_host_run_recipes.py` | test_extends_names_the_baseline_that_runs, tmp_path, monkeypatch, monkeypatch, test_stack_and_recipe_are_mutually_exclusive, ... |
| `tests/test_install_migration_system.py` | TestHomeShimRecipesRewriteRecordedPaths, test_no_install_script_improvises_its_own_home_shim |
| `tests/test_launch_secrets.py` | monkeypatch, test_no_schema_no_project_returns_empty, monkeypatch, tmp_path, test_no_varlock_skips_global_schema, ... |
| `tests/test_launchenv.py` | tmp_path, a, kw, test_a_write_failure_leaves_no_temp_behind, tmp_path, ... |
| `tests/test_launcher_install.py` | rt, fake_active, inst |
| `tests/test_launcher_parallel_build.py` | root, root, kw, rt, fake_build_stack, ... |
| `tests/test_launcher_scan.py` | run_env, image, rt, fake_scan_image |
| `tests/test_launcher_shared_images.py` | kwargs, check, cmd, cmd, kwargs, ... |
| `tests/test_launcher_test_command.py` | delegated, test_an_unsupported_harness_is_rejected_before_anything_is_delegated, delegated, TestSurroundingBehaviourIsUnchanged, test_a_stack_that_is_not_built_is_assembled_first, ... |
| `tests/test_launcher_timeouts.py` | args, print, kwargs |
| `tests/test_launchscript.py` | limit, path, spy |
| `tests/test_mcp_remote_auth.py` | test_an_explicit_network_still_gets_no_pasta_option, test_publishing_a_port_also_asks_pasta_to_forward_to_the_pods_loopback, test_an_explicit_network_is_never_silently_rewritten, capsys, TestThePublishReachesALoopbackListener, ... |
| `tests/test_mint_race.py` | monkeypatch, test_exactly_one_owner_under_concurrent_launch, tmp_path |
| `tests/test_paths_generated_root.py` | monkeypatch, tmp_path, monkeypatch, test_generated_root_is_under_xdg_data, tmp_path, ... |
| `tests/test_prose_lint.py` | test_detached_punctuation_does_not_inflate_the_word_count, tmp_path, tmp_path, test_collect_paths_finds_only_rule_and_skill_files, test_explicit_file_target_is_linted_even_if_not_a_rule_or_skill, ... |
| `tests/test_recipes_integration.py` | tmp_path, monkeypatch, test_without_a_credentialed_report_the_baked_one_is_still_used |
| `tests/test_rescan_credentialed.py` | test_omitted_image_still_scans_every_labelled_image, no_archive_scan, podman, monkeypatch, podman, ... |
| `tests/test_scan_corepack_removed.py` | logical_lines, text |
| `tests/test_schema_thread_safety.py` | load |
| `tests/test_setup_notice.py` | kwargs, args, fake_prompt |
| `tests/test_tools_field_parity.py` | kwargs, run, fake_run, cmd, argv, ... |
| `tools/mutants_391_svcstate.py` | _dirty, main, _run_suite |
| `tools/verify-move.py` | source, origin, _defs, main |

## Entry Points

- `tests/test_adhoc_launch_is_not_persisted.py::TestHostRunLeavesNothingBehind.test_an_ordinary_stack_still_persists`
- `tests/test_mint_race.py::TestMintRace.test_exactly_one_owner_under_concurrent_launch`

## Connected Communities

- **harnessed +3 dirs** (23 cross-edges)
- **tests +2 dirs · strip** (11 cross-edges)
- **tests +3 dirs · get** (6 cross-edges)
- **tests +3 dirs · startswith** (6 cross-edges)
- **tests +3 dirs · split** (6 cross-edges)
- **tests +2 dirs · harnessed.launcher** (4 cross-edges)
- **harnessed +2 dirs · declared_primitives** (4 cross-edges)
- **tests +2 dirs · extend** (4 cross-edges)
- **tests +2 dirs · run** (4 cross-edges)
- **. +2 dirs · write** (3 cross-edges)
- **tests +2 dirs · validate_agent_pin** (3 cross-edges)
- **tests +1 dirs · find** (2 cross-edges)
- **harnessed +1 dirs · derive_name** (2 cross-edges)
- **harnessed +1 dirs · _spec** (2 cross-edges)
- **harnessed +2 dirs · _write** (2 cross-edges)
- **tests +2 dirs · index** (2 cross-edges)
- **harnessed +2 dirs · _broker_start_for** (2 cross-edges)
- **. +1 dirs · test_concurrent_mint_content_ma…** (2 cross-edges)
- **harnessed +1 dirs · _schema** (2 cross-edges)
- **tests +3 dirs · Path** (2 cross-edges)
- **harnessed +1 dirs · _mcp_remote_callback_port** (1 cross-edges)
- **harnessed +1 dirs · normalize** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **tests +1 dirs · resolve_recipe_env** (1 cross-edges)
- **harnessed +1 dirs · normalize_extra_tools** (1 cross-edges)
- **harnessed +1 dirs · parse_extra_tools** (1 cross-edges)
- **harnessed +2 dirs · forget_stack** (1 cross-edges)
- **tests +2 dirs · endswith** (1 cross-edges)
- **tools +1 dirs · main** (1 cross-edges)
- **. +1 dirs · test_recipes_load_correctly_und…** (1 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)
- **harnessed +1 dirs · _mcp_auth_store_mount** (1 cross-edges)
- **tools +1 dirs · check_output** (1 cross-edges)
- **tests +2 dirs · walk** (1 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (1 cross-edges)
- **harnessed +1 dirs · is_adhoc** (1 cross-edges)
- **harnessed +1 dirs · sync_session** (1 cross-edges)
- **tools +2 dirs** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-54")
explore(operation:"context", task:"understand tests +3 dirs · append", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_adhoc_launch_is_not_persisted.py::TestHostRunLeavesNothingBehind.test_an_ordinary_stack_still_persists"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
