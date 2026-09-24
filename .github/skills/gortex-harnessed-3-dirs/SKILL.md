---
name: gortex-harnessed-3-dirs
description: "Work in the harnessed +3 dirs area — 810 symbols across 50 files (73% cohesion)"
---

# harnessed +3 dirs

810 symbols | 50 files | 73% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `catalog/recipes/mikes-universal-setup/hooks/block-dangerous-find.py`
- `external-call::dep:rich.table.Table`
- `external-call::stdlib:fcntl`
- `external-call::stdlib:typer`
- `src/harnessed/assemble.py`
- `src/harnessed/attachcmd.py`
- `src/harnessed/backend.py`
- `src/harnessed/broker.py`
- `src/harnessed/capability.py`
- `src/harnessed/catalogseed.py`
- `src/harnessed/cli.py`
- `src/harnessed/console.py`
- `src/harnessed/credmounts.py`
- `src/harnessed/ctrquery.py`
- `src/harnessed/emit.py`
- `src/harnessed/hosthome.py`
- `src/harnessed/hostrun.py`
- `src/harnessed/launchenv.py`
- `src/harnessed/launcher.py`
- `src/harnessed/layout.py`
- `src/harnessed/mounts.py`
- `src/harnessed/paths.py`
- `src/harnessed/proc.py`
- `src/harnessed/prose.py`
- `src/harnessed/schema.py`
- `src/harnessed/setupenv.py`
- `src/harnessed/svcguards.py`
- `src/harnessed/svcstate.py`
- `src/harnessed/volumes.py`
- `tests/conftest.py`
- `tests/test_aoe.py`
- `tests/test_broker_launch_gate.py`
- `tests/test_conftest_container_config.py`
- `tests/test_docker_userns.py`
- `tests/test_exec_verbs.py`
- `tests/test_external_contracts_live.py`
- `tests/test_host_mise_trust.py`
- `tests/test_install_script.py`
- `tests/test_launchenv.py`
- `tests/test_launcher_parallel_build.py`
- `tests/test_launcher_shared_images.py`
- `tests/test_launcher_warn_ack.py`
- `tests/test_mint_race.py`
- `tests/test_overlay_shadow_warning.py`
- `tests/test_project_scoped_services.py`
- `tests/test_suite_isolation.py`
- `tests/test_tools_field_parity.py`
- `tests/test_userns_mapping.py`
- `tests/test_wheel_packaging.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | TemporaryDirectory, split, token_hex, strip, strftime, ... |
| `catalog/recipes/mikes-universal-setup/hooks/block-dangerous-find.py` | token, is_find |
| `external-call::dep:rich.table.Table` | rich.table.Table |
| `external-call::stdlib:fcntl` | fcntl |
| `external-call::stdlib:typer` | typer |
| `src/harnessed/assemble.py` | _merge_servers, _validate_direct_servers, servers, harness, recipes |
| `src/harnessed/attachcmd.py` | _resolve_mount_path, project_path, agent_start_folder, _resolve_start_dir, project_path, ... |
| `src/harnessed/backend.py` | LaunchSpec |
| `src/harnessed/broker.py` | _kill, all_instances, pid, state_dir |
| `src/harnessed/capability.py` | explicit, _harnessed_bin, _runtime |
| `src/harnessed/catalogseed.py` | _seed_user_default_recipe, _ensure_local_catalog_links |
| `src/harnessed/cli.py` | err, _run_persist_list, err, _run_scan_image_online, args, ... |
| `src/harnessed/console.py` | kwargs, args, set_exec_mode, kwargs, on, ... |
| `src/harnessed/credmounts.py` | stack, home, _stack_from_overlay, rt, _ssh_agent_args, ... |
| `src/harnessed/ctrquery.py` | name, rt, _rt_uses_pods, rt, image, ... |
| `src/harnessed/emit.py` | msg, _stderr_warn |
| `src/harnessed/hosthome.py` | stack, home, harness, _host_home_lock, _migrate_legacy_host_homes, ... |
| `src/harnessed/hostrun.py` | project_path, stack, stack, harness, _host_native_mcp, ... |
| `src/harnessed/launchenv.py` | env_files, schema_dir, var, _fmt, project_path, ... |
| `src/harnessed/launcher.py` | stop, no_firewall, container_run, _merge_baked_opencode, path, ... |
| `src/harnessed/layout.py` | _derived_image, stack, harness, _agent_image, harness |
| `src/harnessed/mounts.py` | harness, _claude_config_seed_mount, _claude_isolated_auth_mount, harness, _aws_sso_ecs_forward_args, ... |
| `src/harnessed/paths.py` | kind, recipe_name, active_runtime, xdg_config_home, cache_key, ... |
| `src/harnessed/proc.py` | _say, timeout, _bounded, warn, cmd, ... |
| `src/harnessed/prose.py` | format |
| `src/harnessed/schema.py` | stack_name, _warn_overlay_shadowed_recipes, raw, strict, load_stack_with_recipes, ... |
| `src/harnessed/setupenv.py` | recipe, recipes, no_strict_mcp, mount_path, harness, ... |
| `src/harnessed/svcguards.py` | _assert_service_running, rt, cname, svc, _assert_placement_unchanged, ... |
| `src/harnessed/svcstate.py` | stack, stack, mode, project_path, _svc_project_key, ... |
| `src/harnessed/volumes.py` | install_args, tools_vol, recipes, _warn, recipe, ... |
| `tests/conftest.py` | home, tmp_path_factory, _isolated_home, _expose_container_storage |
| `tests/test_aoe.py` | test_every_launch_verb_accepts_the_flags, verb, verb, flag, test_every_launch_verb_accepts_the_flag |
| `tests/test_broker_launch_gate.py` | capsys, test_an_instance_with_no_broker_is_not_reported |
| `tests/test_conftest_container_config.py` | test_the_user_catalog_overlay_is_still_hidden, test_the_isolated_root_is_not_the_real_one, monkeypatch, TestHermeticityIsUnchanged, TestTestsThatOptOutStillWin, ... |
| `tests/test_docker_userns.py` | test_it_raises_rather_than_naming_a_runtime_that_is_not_installed, test_the_variable_name_is_the_behaviour, monkeypatch, test_it_returns_what_the_single_detector_returns, monkeypatch, ... |
| `tests/test_exec_verbs.py` | monkeypatch, monkeypatch, TestExecModeNeverBlocksOnAQuestion, test_a_tty_alone_no_longer_licenses_a_prompt, test_no_tty_still_never_prompts, ... |
| `tests/test_external_contracts_live.py` | test_varlock_returns_none_on_missing_schema, test_varlock_is_on_path, TestVarlockJsonOutput, port_container, tmp_path, ... |
| `tests/test_host_mise_trust.py` | monkeypatch, test_the_state_root_is_not_the_real_one, tmp_path, TestTheSuiteWritesNoStateIntoTheDevelopersHome, test_writing_a_project_env_stays_inside_the_tmp_root |
| `tests/test_install_script.py` | monkeypatch, tmp_path, test_bumping_the_pin_yields_a_fresh_cache_dir, tmp_path, test_cache_lives_under_xdg_cache_home_keyed_by_recipe_and_ref, ... |
| `tests/test_launchenv.py` | test_the_timeout_result_is_cached_like_any_other_failure, monkeypatch, test_later_lines_win, TestPlainEnvValues, tmp_path, ... |
| `tests/test_launcher_parallel_build.py` | quiet, test_builds_once_and_serializes_concurrent_callers, TestBuildSharedOnce |
| `tests/test_launcher_shared_images.py` | test_base_image_built_once_per_process, podman, podman, test_agent_image_built_once_per_harness |
| `tests/test_launcher_warn_ack.py` | test_both_exec_paths_acknowledge_before_handing_over_the_terminal |
| `tests/test_mint_race.py` | test_lock_file_survives_rmtree, monkeypatch, test_sequential_second_call_returns_none, test_lock_file_survives_build_failure_rmtree, test_lock_file_survives_exception_path_rmtree, ... |
| `tests/test_overlay_shadow_warning.py` | tmp_path, capsys, monkeypatch, test_second_resolve_of_same_name_does_not_rewarn |
| `tests/test_project_scoped_services.py` | svc, test_a_dead_container_still_takes_the_dead_path, monkeypatch |
| `tests/test_suite_isolation.py` | test_oauth_token_absent_from_ambient_env, TestSuiteIsolation, test_isolated_home_contains_no_harnessed_schema, test_home_is_isolated_from_real_developer_home, test_isolated_home_contains_no_dot_claude |
| `tests/test_tools_field_parity.py` | Result, __init__ |
| `tests/test_userns_mapping.py` | tmp_path, test_the_member_wiring_really_strips_it |
| `tests/test_wheel_packaging.py` | tmp_path, TestTheBuildTreeIsHermetic, test_mise_config_is_excluded_from_the_build_copy, test_the_real_checkout_carries_the_config_being_excluded |

## Entry Points

- `src/harnessed/launcher.py::container_run`
- `src/harnessed/launcher.py::host_gc`
- `src/harnessed/launcher.py::update_pins`
- `src/harnessed/launcher.py::build_L4400`
- `src/harnessed/launcher.py::volume_gc`

## Connected Communities

- **tests +3 dirs · Path** (44 cross-edges)
- **tests +3 dirs · append** (38 cross-edges)
- **tests +2 dirs · strip** (31 cross-edges)
- **tests +2 dirs · run** (23 cross-edges)
- **harnessed +1 dirs · _ensure_stack_volumes** (20 cross-edges)
- **tests +3 dirs · get** (19 cross-edges)
- **tests +2 dirs · update** (17 cross-edges)
- **harnessed +2 dirs · profile_dir** (17 cross-edges)
- **tests +2 dirs · McpServer** (14 cross-edges)
- **harnessed +2 dirs · _make_entry** (10 cross-edges)
- **tests +3 dirs · startswith** (10 cross-edges)
- **tests +2 dirs · patch_all** (9 cross-edges)
- **tests +2 dirs · resolve_releases** (8 cross-edges)
- **harnessed +2 dirs · _staged_build_context** (7 cross-edges)
- **tests +2 dirs · fold_test_result** (6 cross-edges)
- **. +2 dirs · monotonic** (6 cross-edges)
- **tests +2 dirs · validate_agent_pin** (6 cross-edges)
- **harnessed +2 dirs · _prompt_setup_notices** (5 cross-edges)
- **. +1 dirs · _recipe · . · test_launcher_init** (5 cross-edges)
- **tests +3 dirs · split** (5 cross-edges)
- **tests +1 dirs · _write** (5 cross-edges)
- **harnessed +2 dirs · declared_primitives** (4 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (4 cross-edges)
- **tests +2 dirs · _pin** (3 cross-edges)
- **. +2 dirs · write** (3 cross-edges)
- **tests +1 dirs · write_mcp_json** (3 cross-edges)
- **harnessed +2 dirs · opencode_agent_name** (3 cross-edges)
- **harnessed +1 dirs · host_home** (3 cross-edges)
- **harnessed +1 dirs · warn_duplicate_hooks** (3 cross-edges)
- **harnessed +1 dirs · _git_identity_config_mount** (3 cross-edges)
- **tests +2 dirs · introspect_mcp** (3 cross-edges)
- **tests +2 dirs · _varlock_cache_clear** (3 cross-edges)
- **tests +2 dirs · endswith** (3 cross-edges)
- **tests +1 dirs · _typed_invocation** (2 cross-edges)
- **harnessed +1 dirs · _schema** (2 cross-edges)
- **tests +1 dirs · install_env** (2 cross-edges)
- **harnessed +1 dirs · required_settings** (2 cross-edges)
- **harnessed +1 dirs · project_env_path** (2 cross-edges)
- **harnessed · _resolve_parent_stack_dir** (2 cross-edges)
- **. +2 dirs · affected_stacks** (2 cross-edges)
- **harnessed · _levenshtein** (2 cross-edges)
- **. +2 dirs · _restore_user_mise_env** (2 cross-edges)
- **tests +2 dirs · InstallRef** (2 cross-edges)
- **tests +1 dirs · _entry** (2 cross-edges)
- **harnessed +1 dirs · _mcp_remote_pending_auth** (2 cross-edges)
- **tests +1 dirs · search** (2 cross-edges)
- **tests +2 dirs · extend** (2 cross-edges)
- **tests +1 dirs · catalog_relpath** (2 cross-edges)
- **harnessed +2 dirs · guard_ownership** (2 cross-edges)
- **harnessed +1 dirs · _ssh_dir_mounts** (2 cross-edges)
- **harnessed +1 dirs · _harness_config_env** (2 cross-edges)
- **. +2 dirs · _apply_host_tool_path** (2 cross-edges)
- **. +2 dirs · reconcile** (2 cross-edges)
- **. +2 dirs · _managed_block_re** (2 cross-edges)
- **harnessed +2 dirs · _write** (2 cross-edges)
- **tests +1 dirs · resolve_recipe_env** (2 cross-edges)
- **harnessed +2 dirs · _broker_start_for** (2 cross-edges)
- **harnessed +1 dirs · _home_with_agent** (2 cross-edges)
- **tests +2 dirs · build_report** (2 cross-edges)
- **tests +2 dirs · index** (2 cross-edges)
- **harnessed · _resolve_setup_config** (2 cross-edges)
- **tests +1 dirs · Recipe** (2 cross-edges)
- **tests +2 dirs · harnessed.launcher** (2 cross-edges)
- **. +1 dirs · test_concurrent_mint_content_ma…** (2 cross-edges)
- **harnessed +1 dirs · stack_lock_body** (2 cross-edges)
- **harnessed +1 dirs · _trusted_ssh_keys** (2 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **harnessed +1 dirs · container_hostname** (1 cross-edges)
- **harnessed +1 dirs · write_opencode_persona** (1 cross-edges)
- **harnessed · run_image_scan_online** (1 cross-edges)
- **harnessed +1 dirs · group_for** (1 cross-edges)
- **harnessed · _container_label** (1 cross-edges)
- **tests +1 dirs · _mcp_remote_pod_args** (1 cross-edges)
- **harnessed +1 dirs · list_entries** (1 cross-edges)
- **harnessed +1 dirs · instance_name** (1 cross-edges)
- **harnessed +1 dirs · test_defaults_to_constant** (1 cross-edges)
- **harnessed +1 dirs · source_checkout** (1 cross-edges)
- **tests +1 dirs · err** (1 cross-edges)
- **harnessed +1 dirs · sync_session** (1 cross-edges)
- **. +2 dirs · _setup_xdg** (1 cross-edges)
- **harnessed +1 dirs · _mcp_auth_store_mount** (1 cross-edges)
- **harnessed +1 dirs · _recipe** (1 cross-edges)
- **harnessed · _relink** (1 cross-edges)
- **harnessed +1 dirs · _mcp_auth_store_dir** (1 cross-edges)
- **harnessed +1 dirs · _plan_host_omp** (1 cross-edges)
- **harnessed +1 dirs · _token_is_complete** (1 cross-edges)
- **tests · _health** (1 cross-edges)
- **. +2 dirs · _make_completed** (1 cross-edges)
- **harnessed +1 dirs · is_adhoc** (1 cross-edges)
- **tests +1 dirs · CompletedProcess** (1 cross-edges)
- **tests · _install · test_overlay_shadow_warning** (1 cross-edges)
- **harnessed +1 dirs · urlopen** (1 cross-edges)
- **harnessed +1 dirs · _stamp_host_home** (1 cross-edges)
- **harnessed +1 dirs · overlay_shadowed_repo_path** (1 cross-edges)
- **harnessed +1 dirs · host_home_shim** (1 cross-edges)
- **harnessed +1 dirs · test_the_launch_points_claude_c…** (1 cross-edges)
- **harnessed +1 dirs · _built_image_hash** (1 cross-edges)
- **. +1 dirs · harness_stubs** (1 cross-edges)
- **harnessed +1 dirs · stop** (1 cross-edges)
- **harnessed +1 dirs · _gnupg_mounts** (1 cross-edges)
- **harnessed +2 dirs · forget_stack** (1 cross-edges)
- **. +2 dirs · merge_opencode_config** (1 cross-edges)
- **harnessed +1 dirs · _agent_placement_args** (1 cross-edges)
- **tests +1 dirs · _parse** (1 cross-edges)
- **harnessed +1 dirs · title_for** (1 cross-edges)
- **harnessed +1 dirs · _host_omp_source** (1 cross-edges)
- **harnessed +1 dirs · _gh_hosts_missing_plaintext_tok…** (1 cross-edges)
- **. +1 dirs · _gate** (1 cross-edges)
- **. +2 dirs · api_endpoint_egress_hosts** (1 cross-edges)
- **harnessed +1 dirs · _netns_anchor** (1 cross-edges)
- **harnessed +1 dirs · _build_derived_image** (1 cross-edges)
- **. +1 dirs · test_recipes_load_correctly_und…** (1 cross-edges)
- **harnessed · _svc_drift_reason** (1 cross-edges)
- **harnessed +1 dirs · _fmt_size** (1 cross-edges)
- **harnessed +1 dirs · _mcp_remote_token_file** (1 cross-edges)
- **harnessed +1 dirs · write_stack_lock** (1 cross-edges)
- **harnessed +1 dirs · _top** (1 cross-edges)
- **harnessed +1 dirs · derive_name** (1 cross-edges)
- **harnessed +2 dirs · _port_free** (1 cross-edges)
- **. +2 dirs · Popen** (1 cross-edges)
- **harnessed +1 dirs · test_path_outside_home_uses_bas…** (1 cross-edges)
- **tests +1 dirs · _without_userns** (1 cross-edges)
- **tests +2 dirs · patch** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-57")
explore(operation:"context", task:"understand harnessed +3 dirs", format:"gcx")
relations(operation:"usages", target:{symbol:"src/harnessed/launcher.py::container_run"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
