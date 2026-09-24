---
name: gortex-tests-2-dirs-harnessed-launcher
description: "Work in the tests +2 dirs · harnessed.launcher area — 570 symbols across 24 files (74% cohesion)"
---

# tests +2 dirs · harnessed.launcher

570 symbols | 24 files | 74% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::dep:harnessed.launcher`
- `src/harnessed/mounts.py`
- `tests/test_antigravity_keyring.py`
- `tests/test_claude_container_auth.py`
- `tests/test_ensure_docs_wiki_clone.py`
- `tests/test_ensure_local_catalog_links.py`
- `tests/test_folder_env_contract.py`
- `tests/test_host_run_recipes.py`
- `tests/test_host_setup.py`
- `tests/test_install_script.py`
- `tests/test_launch_host.py`
- `tests/test_launch_secrets.py`
- `tests/test_launcher_install.py`
- `tests/test_launcher_test_command.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_launcher_warn_ack.py`
- `tests/test_live_verification_debt.py`
- `tests/test_omp_config_seed.py`
- `tests/test_omp_mcp_seed.py`
- `tests/test_project_scoped_services.py`
- `tests/test_rescan_credentialed.py`
- `tests/test_tools_field_parity.py`
- `tests/test_update_cli.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | SimpleNamespace, timedelta, datetime.datetime, types.SimpleNamespace, timestamp, ... |
| `external-call::dep:harnessed.launcher` | harnessed.launcher |
| `src/harnessed/mounts.py` | creds, _claude_creds_expired |
| `tests/test_antigravity_keyring.py` | TestKeyringStateMount, tmp_path, monkeypatch, monkeypatch, test_non_antigravity_gets_no_mount, ... |
| `tests/test_claude_container_auth.py` | tmp_path, test_a_name_that_merely_contains_the_var_is_left_alone, test_no_token_emits_nothing, test_malformed_copy_is_replaced, tmp_path, ... |
| `tests/test_ensure_docs_wiki_clone.py` | tmp_path, test_not_a_source_checkout_is_noop, monkeypatch |
| `tests/test_ensure_local_catalog_links.py` | test_idempotent, tmp_path, test_never_overwrites_an_existing_default, tmp_path, monkeypatch, ... |
| `tests/test_folder_env_contract.py` | tmp_path, test_recipe_dir_is_the_catalog_dir_on_host_and_the_mount_in_container, monkeypatch, tmp_path, tmp_path, ... |
| `tests/test_host_run_recipes.py` | _k, _k, _a, registered_and_stop, _a, ... |
| `tests/test_host_setup.py` | TestSubst, test_substitutes_known_leaves_unknown, TestNativeMcp, test_stdio_server_emitted_natively, test_no_mcp_stack_returns_none |
| `tests/test_install_script.py` | monkeypatch, test_no_cache_declared_hands_the_script_an_empty_string, test_materialize_wipes_whatever_preceded_it, TestCache, tmp_path, ... |
| `tests/test_launch_host.py` | test_no_fingerprint_keeps_unconditional_rebuild, test_a_live_terminal_resume_pointer_survives_the_rebuild, TestShareOmpState, monkeypatch, test_settings_reach_the_bridge_even_when_the_stack_is_unchanged, ... |
| `tests/test_launch_secrets.py` | test_plain_env_is_normalized, tmp_path, monkeypatch |
| `tests/test_launcher_install.py` | test_docker_has_no_pod_concept, test_auto_forward_omits_gh_token_and_private_keys, test_macos_relay_returns_none_on_failed_forward, test_declared_private_key_mounted_ro, boom, ... |
| `tests/test_launcher_test_command.py` | stale, k, a |
| `tests/test_launcher_timeouts.py` | err, test_an_unconfinable_container_is_torn_down_not_left_running, monkeypatch, test_any_failure_tears_the_pod_down_not_just_a_clean_exit, monkeypatch, ... |
| `tests/test_launcher_warn_ack.py` | capsys, capsys, test_the_message_itself_is_unchanged, test_ordinary_output_does_not_increment, capsys, ... |
| `tests/test_live_verification_debt.py` | test_scan_report_is_copied_out_before_the_container_is_removed, tmp_path |
| `tests/test_omp_config_seed.py` | home, home, _load_yaml, home, home, ... |
| `tests/test_omp_mcp_seed.py` | home, test_non_omp_harness_is_noop |
| `tests/test_project_scoped_services.py` | test_password_is_stable_across_calls_and_never_empty, test_switching_placement_aborts, test_autostart_interlock_is_exported, wired, wired, ... |
| `tests/test_rescan_credentialed.py` | test_bare_global_env_is_normalized_into_an_env_file, tmp_path, monkeypatch, monkeypatch, monkeypatch, ... |
| `tests/test_tools_field_parity.py` | test_the_snapshot_covers_every_variable_the_redirect_touches |
| `tests/test_update_cli.py` | fresh, with_agent, test_the_window_can_be_overridden_on_the_command_line, test_a_fresh_harness_bump_is_named_with_its_age, test_a_fresh_release_does_not_fail_check, ... |

## Entry Points

- `tests/test_install_script.py::TestCache.test_miss_then_hit_across_launches`
- `tests/test_launch_host.py::TestShareClaudeState.test_symlinks_session_state_and_live_auth`
- `tests/test_launch_host.py::TestOmpHooksBridgeSurface.test_settings_reach_the_bridge_even_when_the_stack_is_unchanged`

## Connected Communities

- **tests +2 dirs · patch_all** (22 cross-edges)
- **tests +3 dirs · Path** (12 cross-edges)
- **tests +2 dirs · validate_agent_pin** (9 cross-edges)
- **harnessed +3 dirs** (8 cross-edges)
- **tests · _home · test_claude_container_auth** (5 cross-edges)
- **tests +2 dirs · McpServer** (5 cross-edges)
- **. +2 dirs · _setup_xdg** (5 cross-edges)
- **tests +3 dirs · get** (4 cross-edges)
- **tests +2 dirs · endswith** (4 cross-edges)
- **. +1 dirs · _recipe · . · test_install_script** (4 cross-edges)
- **tests +3 dirs · split** (4 cross-edges)
- **tests +2 dirs · build_report** (4 cross-edges)
- **tests +3 dirs · append** (3 cross-edges)
- **tests · resolve** (3 cross-edges)
- **harnessed +1 dirs · host_home** (2 cross-edges)
- **tests · _fake_profile** (2 cross-edges)
- **tests +2 dirs · strip** (2 cross-edges)
- **tests · _svc · test_project_scoped_services (21)** (2 cross-edges)
- **tests · _state_home · test_antigravity_keyring** (2 cross-edges)
- **tests · _plain** (1 cross-edges)
- **harnessed +2 dirs · _port_free** (1 cross-edges)
- **. +1 dirs · _gate** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **tools +3 dirs** (1 cross-edges)
- **harnessed +1 dirs · test_the_launch_points_claude_c…** (1 cross-edges)
- **tests +2 dirs · _pin** (1 cross-edges)
- **tests +3 dirs · startswith** (1 cross-edges)
- **tests +2 dirs · resolve_releases** (1 cross-edges)
- **harnessed +2 dirs · profile_dir** (1 cross-edges)
- **harnessed +1 dirs · _plan_host_omp** (1 cross-edges)
- **tests · _recipe · test_folder_env_contract** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-249")
explore(operation:"context", task:"understand tests +2 dirs · harnessed.launcher", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_install_script.py::TestCache.test_miss_then_hit_across_launches"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
