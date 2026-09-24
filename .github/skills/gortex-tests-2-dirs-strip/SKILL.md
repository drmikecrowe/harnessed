---
name: gortex-tests-2-dirs-strip
description: "Work in the tests +2 dirs · strip area — 117 symbols across 21 files (52% cohesion)"
---

# tests +2 dirs · strip

117 symbols | 21 files | 52% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `external-call::dep:harnessed.capmatrix`
- `src/harnessed/capability.py`
- `src/harnessed/emit.py`
- `src/harnessed/persist.py`
- `src/harnessed/prose.py`
- `src/harnessed/schema.py`
- `src/harnessed/svcstate.py`
- `src/harnessed/toollock.py`
- `tests/test_agent_pin_channel_gate.py`
- `tests/test_aoe.py`
- `tests/test_backend_seam.py`
- `tests/test_build_cache_mounts.py`
- `tests/test_capmatrix.py`
- `tests/test_external_contracts_live.py`
- `tests/test_install_migration_content.py`
- `tests/test_install_script.py`
- `tests/test_pin_hold_marker.py`
- `tests/test_project_tool_env.py`
- `tests/test_prose_lint.py`
- `tests/test_userns_mapping.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | strip, items |
| `external-call::dep:harnessed.capmatrix` | harnessed.capmatrix |
| `src/harnessed/capability.py` | _sse_to_objects, payload |
| `src/harnessed/emit.py` | stack_name, body, m, _split_rule_sections, body, ... |
| `src/harnessed/persist.py` | PersistNotAllowlistedError |
| `src/harnessed/prose.py` | frontmatter, description_of |
| `src/harnessed/schema.py` | raw_args, _parse_agent_unpinnable, raw_install, _parse_services, _parse_init, ... |
| `src/harnessed/svcstate.py` | rt, project_path, _svc_stacks_from_instances |
| `src/harnessed/toollock.py` | _section_key, text, _blocks, path |
| `tests/test_agent_pin_channel_gate.py` | value, test_non_ascii_digits_are_not_a_ref_either |
| `tests/test_aoe.py` | _a, _k, assemble |
| `tests/test_backend_seam.py` | test_the_contract_is_exactly_the_six_named_capabilities |
| `tests/test_build_cache_mounts.py` | test_the_cache_mount_parents_are_owned_by_the_image_user, path, script, _run, TestTheShippedImageDoesNotHandOverARootOwnedHome |
| `tests/test_capmatrix.py` | test_every_primitive_has_a_cell_on_every_backend, TestMatrixConformance, test_every_degraded_cell_has_a_detail, test_every_cell_is_a_known_level |
| `tests/test_external_contracts_live.py` | test_mise_trust_succeeds_for_a_real_toml, TestMiseTrustIntegration, tmp_path, test_real_mise_binary_accepts_host_mise_env, tmp_path, ... |
| `tests/test_install_migration_content.py` | name, test_a_refs_recipe_carries_no_pin_literal_at_all |
| `tests/test_install_script.py` | test_the_archive_url_carries_a_resolvable_variable_not_a_positional |
| `tests/test_pin_hold_marker.py` | test_no_recipe_holds_without_a_reason |
| `tests/test_project_tool_env.py` | test_it_prints_one_bare_line, monkeypatch, tmp_path, TestTheCliCommand, test_it_prints_the_path, ... |
| `tests/test_prose_lint.py` | test_folded_scalar_indicator_is_not_counted_as_content, test_quoted_description_loses_its_delimiters, test_multiline_description_stops_at_the_next_key |
| `tests/test_userns_mapping.py` | test_no_bare_keep_id_remains_in_src |

## Connected Communities

- **tests +3 dirs · get** (31 cross-edges)
- **tests +3 dirs · startswith** (15 cross-edges)
- **tests +3 dirs · append** (14 cross-edges)
- **harnessed +3 dirs** (11 cross-edges)
- **tests +2 dirs · run** (4 cross-edges)
- **tests +2 dirs · validate_agent_pin** (3 cross-edges)
- **tests +3 dirs · split** (3 cross-edges)
- **harnessed +1 dirs · project_env_path** (2 cross-edges)
- **tests +3 dirs · Path** (2 cross-edges)
- **tests +2 dirs · update** (2 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (2 cross-edges)
- **tests +2 dirs · McpServer** (2 cross-edges)
- **tests +3 dirs · write_omp_identity** (2 cross-edges)
- **tests +2 dirs · endswith** (2 cross-edges)
- **. +1 dirs · _gate** (1 cross-edges)
- **tests +2 dirs · _pin** (1 cross-edges)
- **harnessed +1 dirs · start** (1 cross-edges)
- **tests · _recipe · test_install_migration_content** (1 cross-edges)
- **harnessed +2 dirs · _make_entry** (1 cross-edges)
- **harnessed +2 dirs · declared_primitives** (1 cross-edges)
- **tests +2 dirs · InstallRef** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-64")
explore(operation:"context", task:"understand tests +2 dirs · strip", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
