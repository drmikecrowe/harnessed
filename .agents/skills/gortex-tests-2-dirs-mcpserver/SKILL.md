---
name: gortex-tests-2-dirs-mcpserver
description: "Work in the tests +2 dirs · McpServer area — 120 symbols across 13 files (63% cohesion)"
---

# tests +2 dirs · McpServer

120 symbols | 13 files | 63% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/assemble.py`
- `src/harnessed/emit.py`
- `src/harnessed/paths.py`
- `src/harnessed/schema.py`
- `tests/test_direct_mcp_servers.py`
- `tests/test_emit.py`
- `tests/test_launch_secrets.py`
- `tests/test_live_verification_debt.py`
- `tests/test_mcp_remote_auth.py`
- `tests/test_scan_ledger_reconciliation.py`
- `tests/test_schema.py`
- `tests/test_service_refs.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | loads |
| `src/harnessed/assemble.py` | AssembleResult, build_dir, strict, root, stack_name, ... |
| `src/harnessed/emit.py` | harness, write_hatago_config, profile_dir, recipes, permissions, ... |
| `src/harnessed/paths.py` | project_path, container_project_path |
| `src/harnessed/schema.py` | is_stdio_child, recipe, validate_no_raw_npm, McpServer, recipe_root, ... |
| `tests/test_direct_mcp_servers.py` | test_url_env_wins_when_both_are_set, tmp_path, tmp_path, test_url_env_emits_a_placeholder, tmp_path, ... |
| `tests/test_emit.py` | test_stdio_entry_has_no_cwd_without_project_path, tmp_path, tmp_path, tmp_path, kw, ... |
| `tests/test_launch_secrets.py` | test_url_env_placeholder_not_a_resolved_value, test_url_env_emits_placeholder, test_url_env_takes_precedence_over_url, TestHatagoEntryUrlEnv, test_url_without_url_env_unchanged |
| `tests/test_live_verification_debt.py` | tmp_path, test_the_copied_report_is_the_real_schema |
| `tests/test_mcp_remote_auth.py` | test_a_portless_server_does_not_stop_a_later_one_from_publishing, tmp_path, test_no_store_dir_is_created_for_an_unrelated_stack |
| `tests/test_scan_ledger_reconciliation.py` | test_a_snyk_timeout_orphans_no_temp_directory, TestATimedOutScanLeavesNothingBehind, tmp_path |
| `tests/test_schema.py` | TestValidateNoRawNpm, test_npmlog_package_name_does_not_raise, test_clean_recipe_passes, name, test_npm_in_arg_raises, ... |
| `tests/test_service_refs.py` | test_no_services_returns_empty, recipes, servers, _patch_recipes, test_stack_and_recipe_services_dedupe_recipe_first, ... |

## Entry Points

- `tests/test_scan_ledger_reconciliation.py::TestATimedOutScanLeavesNothingBehind.test_a_snyk_timeout_orphans_no_temp_directory`

## Connected Communities

- **tests +1 dirs · write_mcp_json** (9 cross-edges)
- **harnessed +3 dirs** (6 cross-edges)
- **tests +2 dirs · harnessed.launcher** (6 cross-edges)
- **tests +3 dirs · Path** (5 cross-edges)
- **tests +2 dirs · extend** (5 cross-edges)
- **tests +3 dirs · get** (4 cross-edges)
- **harnessed +1 dirs · required_settings** (4 cross-edges)
- **tests +2 dirs · Stack** (3 cross-edges)
- **tests +2 dirs · validate_agent_pin** (3 cross-edges)
- **tests +3 dirs · append** (3 cross-edges)
- **tests +2 dirs · update** (3 cross-edges)
- **tests +3 dirs · startswith** (3 cross-edges)
- **tests +2 dirs · patch_all** (2 cross-edges)
- **tests +1 dirs · Recipe** (2 cross-edges)
- **tests +2 dirs · resolve_releases** (2 cross-edges)
- **harnessed +1 dirs · LinkSyncer** (2 cross-edges)
- **tests +1 dirs · validate_setup_script** (1 cross-edges)
- **harnessed +1 dirs · _mcp_auth_store_mount** (1 cross-edges)
- **tests +2 dirs · endswith** (1 cross-edges)
- **harnessed +1 dirs · write_claude_md** (1 cross-edges)
- **tests +2 dirs · run** (1 cross-edges)
- **tests +3 dirs · write_omp_identity** (1 cross-edges)
- **harnessed +1 dirs · validate_container_only_declared** (1 cross-edges)
- **harnessed +1 dirs · _home_with_agent** (1 cross-edges)
- **harnessed +1 dirs · _mcp_remote_callback_publish_ar…** (1 cross-edges)
- **harnessed +1 dirs · validate_init_no_exit** (1 cross-edges)
- **harnessed +1 dirs · write_antigravity_identity** (1 cross-edges)
- **tests +1 dirs · validate_install_script** (1 cross-edges)
- **tests +1 dirs · validate_pin** (1 cross-edges)
- **harnessed +1 dirs · write_codex_agents_md** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-406")
explore(operation:"context", task:"understand tests +2 dirs · McpServer", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_scan_ledger_reconciliation.py::TestATimedOutScanLeavesNothingBehind.test_a_snyk_timeout_orphans_no_temp_directory"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
