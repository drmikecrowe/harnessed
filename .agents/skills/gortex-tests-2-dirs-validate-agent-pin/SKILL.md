---
name: gortex-tests-2-dirs-validate-agent-pin
description: "Work in the tests +2 dirs · validate_agent_pin area — 157 symbols across 13 files (48% cohesion)"
---

# tests +2 dirs · validate_agent_pin

157 symbols | 13 files | 48% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::stdlib:pytest`
- `src/harnessed/launcher.py`
- `src/harnessed/schema.py`
- `tests/support.py`
- `tests/test_agent_pin_channel_gate.py`
- `tests/test_agent_pin_lint.py`
- `tests/test_backend_seam.py`
- `tests/test_catalog_json_schemas.py`
- `tests/test_exec_verbs.py`
- `tests/test_hub_transport.py`
- `tests/test_launcher_warn_ack.py`
- `tests/test_schema.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | perf_counter, match |
| `external-call::stdlib:pytest` | pytest |
| `src/harnessed/launcher.py` | _acknowledge_warnings |
| `src/harnessed/schema.py` | _unversioned_acquisitions, dockerfile_body, command, record, validate_agent_pin, ... |
| `tests/support.py` | func, podman |
| `tests/test_agent_pin_channel_gate.py` | test_an_absurdly_long_value_is_rejected_promptly, test_an_absurdly_long_ref_is_rejected_promptly |
| `tests/test_agent_pin_lint.py` | test_the_same_unversioned_spec_twice_counts_once, test_the_error_names_the_agent_and_the_installer_url, test_a_tag_clone_is_accepted, test_codex_passes_now_that_A2_has_pinned_it, test_omp_passes_now_that_A5b_has_pinned_its_bun, ... |
| `tests/test_backend_seam.py` | tmp_path, test_a_service_less_stack_needs_no_container_runtime, monkeypatch |
| `tests/test_catalog_json_schemas.py` | kind, _all_manifests, _manifests |
| `tests/test_exec_verbs.py` | test_the_warning_acknowledgement_is_skipped, monkeypatch |
| `tests/test_hub_transport.py` | test_a_stack_yaml_with_an_empty_value_is_refused_end_to_end, tmp_path |
| `tests/test_launcher_warn_ack.py` | capsys, test_non_tty_never_pauses_even_with_warnings, test_no_warning_never_pauses, capsys, prompted, ... |
| `tests/test_schema.py` | test_stack_name_equal_to_harness_raises, test_invalid_permissions_raises, test_empty_string_entry_rejected, test_non_list_rejected, tmp_path, ... |

## Connected Communities

- **tests +3 dirs · get** (8 cross-edges)
- **harnessed +3 dirs** (6 cross-edges)
- **tests +2 dirs · strip** (4 cross-edges)
- **tests +3 dirs · startswith** (3 cross-edges)
- **harnessed +2 dirs · _write** (2 cross-edges)
- **tests +3 dirs · append** (2 cross-edges)
- **harnessed +1 dirs · _spec** (2 cross-edges)
- **harnessed +1 dirs · _mutable_fetch_ref** (2 cross-edges)
- **tests +2 dirs · harnessed.launcher** (1 cross-edges)
- **tests +3 dirs · split** (1 cross-edges)
- **tests +1 dirs · search** (1 cross-edges)
- **harnessed +2 dirs · declared_primitives** (1 cross-edges)
- **tests · _parse** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-106")
explore(operation:"context", task:"understand tests +2 dirs · validate_agent_pin", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
