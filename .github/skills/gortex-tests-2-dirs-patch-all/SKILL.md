---
name: gortex-tests-2-dirs-patch-all
description: "Work in the tests +2 dirs · patch_all area — 325 symbols across 19 files (75% cohesion)"
---

# tests +2 dirs · patch_all

325 symbols | 19 files | 75% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/credmounts.py`
- `src/harnessed/paths.py`
- `src/harnessed/schema.py`
- `tests/support.py`
- `tests/test_credmounts.py`
- `tests/test_folder_env_contract.py`
- `tests/test_git_lookup_failure.py`
- `tests/test_launch_host.py`
- `tests/test_launch_passthrough.py`
- `tests/test_launcher_install.py`
- `tests/test_launcher_parallel_build.py`
- `tests/test_launcher_shared_images.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_no_strict_mcp_config.py`
- `tests/test_project_scoped_services.py`
- `tests/test_run_command.py`
- `tests/test_setup_notice.py`
- `tests/test_stable_port.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | startswith, values, sys |
| `src/harnessed/credmounts.py` | _op_agent_socket, _host_os, home |
| `src/harnessed/paths.py` | persist_in_repo_dir, name, project_path |
| `src/harnessed/schema.py` | root, load_service, name |
| `tests/support.py` | monkeypatch, value, name, patch_all |
| `tests/test_credmounts.py` | tmp_path, os_name, TestHostOsGatedBuilders, monkeypatch, monkeypatch, ... |
| `tests/test_folder_env_contract.py` | _no_socket_resolution, monkeypatch |
| `tests/test_git_lookup_failure.py` | capsys, monkeypatch, repo, test_a_launch_survives_and_says_so |
| `tests/test_launch_host.py` | test_host_run_needs_no_runtime_when_the_stack_has_no_services, tmp_path, test_host_run_brings_up_the_stacks_sidecars, monkeypatch, tmp_path, ... |
| `tests/test_launch_passthrough.py` | fake_execvp, captured, argv, rt, monkeypatch |
| `tests/test_launcher_install.py` | test_opencode_without_persona_no_config_mount, test_antigravity_without_identity_no_gemini_mount, tmp_path, monkeypatch, cred_home, ... |
| `tests/test_launcher_parallel_build.py` | monkeypatch, quiet |
| `tests/test_launcher_shared_images.py` | test_build_images_cmd_passes_the_agent_pins_the_dockerfile_demands, harness, test_build_images_cmd_registers_what_it_built, fake_run, test_an_unpinnable_agent_contributes_no_build_arg, ... |
| `tests/test_launcher_timeouts.py` | monkeypatch, _state, tmp_path |
| `tests/test_no_strict_mcp_config.py` | monkeypatch, captured, fake_execvp, argv, rt |
| `tests/test_project_scoped_services.py` | tmp_path, tmp_path, test_the_stamped_hash_is_the_hash_of_the_argv_that_created_it, tmp_path, tmp_path, ... |
| `tests/test_run_command.py` | monkeypatch, tmp_path, test_neither_stack_nor_recipe_runs_the_extends_baseline, monkeypatch, test_failed_build_removes_a_manifest_this_run_created, ... |
| `tests/test_setup_notice.py` | monkeypatch, _no_socket_resolution |
| `tests/test_stable_port.py` | tmp_path, test_stable_is_accepted, tmp_path, tmp_path, TestSchema, ... |

## Entry Points

- `tests/test_launch_host.py::TestHostCliRouting.test_host_run_runs_recipe_init`
- `tests/test_launch_host.py::TestHostCliRouting.test_host_run_brings_up_the_stacks_sidecars`
- `tests/test_project_scoped_services.py::TestServiceConfigHashDetectsStaleContainers.test_building_the_argv_creates_nothing_on_disk`

## Connected Communities

- **tests +2 dirs · harnessed.launcher** (36 cross-edges)
- **tests +2 dirs · validate_agent_pin** (18 cross-edges)
- **harnessed +3 dirs** (16 cross-edges)
- **tests +3 dirs · get** (10 cross-edges)
- **tests +3 dirs · append** (9 cross-edges)
- **tests +3 dirs · Path** (7 cross-edges)
- **tests +2 dirs · strip** (5 cross-edges)
- **tests +3 dirs · startswith** (5 cross-edges)
- **tests +1 dirs · _write** (5 cross-edges)
- **tests +2 dirs · index** (3 cross-edges)
- **tests +1 dirs · CompletedProcess** (3 cross-edges)
- **. +2 dirs · Popen** (2 cross-edges)
- **harnessed +2 dirs · _make_entry** (2 cross-edges)
- **. +2 dirs · _managed_block_re** (2 cross-edges)
- **harnessed +2 dirs · _write** (2 cross-edges)
- **tests +1 dirs · resolve_recipe_env** (2 cross-edges)
- **harnessed +1 dirs · _svc** (2 cross-edges)
- **tests +3 dirs · split** (2 cross-edges)
- **tests +2 dirs · update** (1 cross-edges)
- **harnessed +1 dirs · test_it_propagates_the_failure** (1 cross-edges)
- **. +1 dirs · TestTheBaseImageStillProvidesPn…** (1 cross-edges)
- **harnessed · _resolve_parent_stack_dir** (1 cross-edges)
- **tests +1 dirs · search** (1 cross-edges)
- **. +2 dirs · _make_completed** (1 cross-edges)
- **tests +1 dirs · Recipe** (1 cross-edges)
- **harnessed +2 dirs · _prompt_setup_notices** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-355")
explore(operation:"context", task:"understand tests +2 dirs · patch_all", format:"gcx")
relations(operation:"usages", target:{symbol:"tests/test_launch_host.py::TestHostCliRouting.test_host_run_runs_recipe_init"}, format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
