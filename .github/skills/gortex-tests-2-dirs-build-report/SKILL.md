---
name: gortex-tests-2-dirs-build-report
description: "Work in the tests +2 dirs · build_report area — 216 symbols across 9 files (81% cohesion)"
---

# tests +2 dirs · build_report

216 symbols | 9 files | 81% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/update.py`
- `tests/test_agent_pins.py`
- `tests/test_extra_tools_pins.py`
- `tests/test_install_refs_env.py`
- `tests/test_install_script.py`
- `tests/test_update_cooldown.py`
- `tests/test_update_pins.py`
- `tests/test_update_release_selection.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | sort |
| `src/harnessed/update.py` | agent_dirs, minimum_release_age_minutes, _select, latest, recipe, ... |
| `tests/test_agent_pins.py` | test_the_rewrite_keeps_the_spec_and_its_comments, agent_dir, TestApplyWritesAgentPins, _findings, tmp_path, ... |
| `tests/test_extra_tools_pins.py` | suffix, test_a_missing_file_yields_no_pins_rather_than_raising, test_an_unpinned_file_yields_no_pins_rather_than_raising, test_apply_skips_a_file_neither_rewriter_owns, test_pins_carry_a_label_saying_where_a_bump_would_land, ... |
| `tests/test_install_refs_env.py` | TestTheDerivedCacheIsNotReportedAsAnUpstreamPin, tmp_path, test_a_HAND_WRITTEN_cache_is_still_reported, tmp_path, test_a_derived_cache_produces_no_cache_pin |
| `tests/test_install_script.py` | TestGstackMigrated, _resolve, test_no_declared_ref_anywhere_in_the_catalog_is_unresolved, test_a_ref_whose_upstream_publishes_nothing_is_held_not_unresolved, test_every_pin_is_held_rather_than_unresolved, ... |
| `tests/test_update_cooldown.py` | body, test_an_undated_harness_release_is_offered_not_unresolved, TestHarnessesTrackLatest, tmp_path, test_an_explicit_window_overrides_the_harness_default, ... |
| `tests/test_update_pins.py` | tmp_path, TestRewrite, tmp_path, test_every_catalog_recipe_discovers_without_error, test_apply_never_touches_an_opaque_pin, ... |
| `tests/test_update_release_selection.py` | test_every_pair_of_real_published_shapes_is_orderable, test_a_unicode_digit_int_cannot_parse_does_not_raise, test_a_prerelease_still_sorts_below_its_own_release, test_numeric_prerelease_identifiers_still_compare_numerically, test_a_numeric_identifier_sorts_below_an_alphanumeric_one, ... |

## Connected Communities

- **tests +3 dirs · append** (20 cross-edges)
- **tests · _recipe_dir** (8 cross-edges)
- **tests +3 dirs · get** (6 cross-edges)
- **tests +3 dirs · Path** (5 cross-edges)
- **tests +2 dirs · strip** (5 cross-edges)
- **tests +1 dirs · _write** (4 cross-edges)
- **tests +2 dirs · harnessed.launcher** (3 cross-edges)
- **tests +3 dirs · split** (2 cross-edges)
- **tests +3 dirs · startswith** (2 cross-edges)
- **tests · _recipe · test_install_refs_env** (2 cross-edges)
- **harnessed +2 dirs · declared_primitives** (2 cross-edges)
- **. +2 dirs · _relock_recipe** (1 cross-edges)
- **. +1 dirs · _recipe · . · test_install_script** (1 cross-edges)
- **tests +1 dirs · boom** (1 cross-edges)
- **harnessed +2 dirs · _write** (1 cross-edges)
- **harnessed +3 dirs** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-442")
explore(operation:"context", task:"understand tests +2 dirs · build_report", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
