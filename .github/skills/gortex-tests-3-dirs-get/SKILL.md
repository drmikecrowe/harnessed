---
name: gortex-tests-3-dirs-get
description: "Work in the tests +3 dirs · get area — 264 symbols across 30 files (60% cohesion)"
---

# tests +3 dirs · get

264 symbols | 30 files | 60% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::dep:ruamel.yaml.YAML`
- `src/harnessed/aoe.py`
- `src/harnessed/broker.py`
- `src/harnessed/capability.py`
- `src/harnessed/hosthome.py`
- `src/harnessed/hostrun.py`
- `src/harnessed/proc.py`
- `src/harnessed/scan.py`
- `src/harnessed/schema.py`
- `src/harnessed/update.py`
- `tests/test_capability_tests.py`
- `tests/test_ci_pin_check_workflow.py`
- `tests/test_direct_mcp_servers.py`
- `tests/test_docker_userns.py`
- `tests/test_dynstack.py`
- `tests/test_external_contracts_live.py`
- `tests/test_host_run_recipes.py`
- `tests/test_hub_transport.py`
- `tests/test_install_script.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_live_workflow.py`
- `tests/test_pin_hold_marker.py`
- `tests/test_recipe_env.py`
- `tests/test_scan.py`
- `tests/test_schema.py`
- `tests/test_schema_thread_safety.py`
- `tests/test_setup_confirm.py`
- `tests/test_tools_field_parity.py`
- `tools/openwiki-drift.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | get |
| `external-call::dep:ruamel.yaml.YAML` | ruamel.yaml.YAML |
| `src/harnessed/aoe.py` | stack, a, command, sessions, blocked, ... |
| `src/harnessed/broker.py` | port, _session_on_port, rows |
| `src/harnessed/capability.py` | _collect_server_names, _mcp_from_hatago, out, instance, node |
| `src/harnessed/hosthome.py` | path, _rescue_host_credentials, _credentials_are_usable |
| `src/harnessed/hostrun.py` | _snapshot_user_mise_env, env, _user_mise_config_file, env, env, ... |
| `src/harnessed/proc.py` | cmd, _run, check, kwargs |
| `src/harnessed/scan.py` | gate, osv_json, _all_finding_ids, _max_cvss, vuln, ... |
| `src/harnessed/schema.py` | root, raw_expect, Expect, entry, name, ... |
| `src/harnessed/update.py` | _rewrite_tools_entry, new_spec, new_ref, manifest, _rewrite_install_ref, ... |
| `tests/test_capability_tests.py` | test_discover_finds_shipped_demonstrators |
| `tests/test_ci_pin_check_workflow.py` | workflow, workflow, test_diff_triggered_events_are_absent, workflow, test_it_runs_on_a_schedule, ... |
| `tests/test_direct_mcp_servers.py` | test_direct_and_service_are_mutually_exclusive, test_a_server_is_hub_routed_unless_it_says_otherwise, test_direct_requires_somewhere_to_connect, test_a_port_the_pod_cannot_publish_is_refused, test_an_absent_oauth_block_is_fine, ... |
| `tests/test_docker_userns.py` | rt, tmp_path, monkeypatch, test_every_step_carries_exactly_its_runtimes_mapping, _argv, ... |
| `tests/test_dynstack.py` | test_the_default_recipe_ships_the_authoring_skill, _repo, TestTheDefaultBaselineShips, test_the_default_stack_composes_the_default_recipe, test_the_extends_default_names_a_stack_the_repo_ships |
| `tests/test_external_contracts_live.py` | test_varlock_resolves_non_secret_variable, tmp_path |
| `tests/test_host_run_recipes.py` | test_services_identity_is_part_of_the_derived_name, monkeypatch, tmp_path |
| `tests/test_hub_transport.py` | tmp_path, test_a_stack_yaml_that_omits_it_still_loads |
| `tests/test_install_script.py` | _recipe, name, script_body, extra, tmp_path, ... |
| `tests/test_launcher_timeouts.py` | test_untagged_path_reaches_subprocess_run, monkeypatch, test_tagged_path_reaches_run_tagged, TestRunPropagatesTheTimeout, monkeypatch |
| `tests/test_live_workflow.py` | _as_list, test_the_container_jobs_hang_off_the_changes_job, value, name, workflow |
| `tests/test_pin_hold_marker.py` | test_tools_accepts_both_the_string_and_the_mapping_form |
| `tests/test_recipe_env.py` | tmp_path, test_strict_mode_accepts_env_field |
| `tests/test_scan.py` | test_qualitative_high_label_returned, test_medium_finding_not_returned, TestGate, test_qualitative_low_label_not_returned, test_empty_osv_passes, ... |
| `tests/test_schema.py` | test_forward_git_credentials_defaults_false, tmp_path, tmp_path, tmp_path, tmp_path, ... |
| `tests/test_schema_thread_safety.py` | load, name |
| `tests/test_setup_confirm.py` | TestSchema, test_confirm_without_anything_to_gate_is_rejected, tmp_path, tmp_path, test_confirm_parses |
| `tests/test_tools_field_parity.py` | test_install_time_and_run_time_see_the_same_mise_instance, monkeypatch, tmp_path |
| `tools/openwiki-drift.py` | collect_anchors, claims_dir |

## Connected Communities

- **tests +2 dirs · validate_agent_pin** (21 cross-edges)
- **tests +2 dirs · strip** (21 cross-edges)
- **harnessed +3 dirs** (13 cross-edges)
- **tests +3 dirs · append** (11 cross-edges)
- **tests +3 dirs · Path** (9 cross-edges)
- **tests +2 dirs · McpServer** (4 cross-edges)
- **tests +3 dirs · startswith** (3 cross-edges)
- **tests +2 dirs · harnessed.launcher** (3 cross-edges)
- **tests · resolve** (2 cross-edges)
- **tests +3 dirs · split** (2 cross-edges)
- **harnessed +1 dirs · _ensure_stack_volumes** (2 cross-edges)
- **tests +1 dirs · harnessed.proc** (2 cross-edges)
- **. +2 dirs · _restore_user_mise_env** (1 cross-edges)
- **. +2 dirs · _run_tagged** (1 cross-edges)
- **tests +2 dirs · extend** (1 cross-edges)
- **harnessed +1 dirs · _plan_host_omp** (1 cross-edges)
- **harnessed +1 dirs · _host_omp_source** (1 cross-edges)
- **tests +2 dirs · endswith** (1 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)
- **harnessed +2 dirs · _write** (1 cross-edges)
- **tests +2 dirs · fold_test_result** (1 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (1 cross-edges)
- **tests +2 dirs · run** (1 cross-edges)
- **tests +2 dirs · _pin** (1 cross-edges)
- **tests +2 dirs · _varlock_cache_clear** (1 cross-edges)
- **harnessed · _resolve_parent_stack_dir** (1 cross-edges)
- **harnessed +1 dirs · _host_claude_source** (1 cross-edges)
- **harnessed · _relink** (1 cross-edges)
- **tests +1 dirs · Recipe** (1 cross-edges)
- **tests +1 dirs · launch_headless** (1 cross-edges)
- **harnessed +1 dirs · _parse_hub_transport** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-68")
explore(operation:"context", task:"understand tests +3 dirs · get", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
