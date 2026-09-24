---
name: gortex-harnessed-2-dirs-make-entry
description: "Work in the harnessed +2 dirs · _make_entry area — 116 symbols across 10 files (76% cohesion)"
---

# harnessed +2 dirs · _make_entry

116 symbols | 10 files | 76% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `src/harnessed/paths.py`
- `src/harnessed/persist_gc.py`
- `src/harnessed/schema.py`
- `src/harnessed/setupenv.py`
- `src/harnessed/svcguards.py`
- `src/harnessed/svcstate.py`
- `tests/test_paths.py`
- `tests/test_persist_gc.py`
- `tests/test_project_scoped_services.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | sha1 |
| `src/harnessed/paths.py` | project_path, project_path, project_path, git_common_dir, project_hash, ... |
| `src/harnessed/persist_gc.py` | recipe, stop, project_path, prune_project, scope, ... |
| `src/harnessed/schema.py` | recipe, _persist_entry_dir, project_path, entry, mode, ... |
| `src/harnessed/setupenv.py` | _repo_primitives, project_path |
| `src/harnessed/svcguards.py` | _placement_marker, project_path |
| `src/harnessed/svcstate.py` | _repo_project_hashes, project_path |
| `tests/test_paths.py` | tmp_path, test_under_xdg_data_persist_namespace, monkeypatch, tmp_path, tmp_path, ... |
| `tests/test_persist_gc.py` | tmp_path, tmp_path, test_noop_when_no_matching_dir, test_removes_specific_name, name, ... |
| `tests/test_project_scoped_services.py` | test_outside_a_git_repo_it_still_returns_this_folder, tmp_path, test_a_plain_repo_yields_its_own_hash, TestRepoProjectHashesUsesRealGit, tmp_path |

## Connected Communities

- **harnessed +3 dirs** (5 cross-edges)
- **tests +2 dirs · main** (3 cross-edges)
- **tests +3 dirs · append** (3 cross-edges)
- **tests +2 dirs · run** (3 cross-edges)
- **tests +3 dirs · startswith** (3 cross-edges)
- **tests +3 dirs · Path** (3 cross-edges)
- **tests +2 dirs · InstallRef** (2 cross-edges)
- **tests +2 dirs · harnessed.launcher** (2 cross-edges)
- **harnessed +1 dirs · list_entries** (2 cross-edges)
- **harnessed +2 dirs · _prompt_setup_notices** (2 cross-edges)
- **harnessed +2 dirs · profile_dir** (2 cross-edges)
- **tests +2 dirs · endswith** (1 cross-edges)
- **harnessed +1 dirs · _apply_host_mise_env** (1 cross-edges)
- **harnessed +2 dirs · declared_primitives** (1 cross-edges)
- **tests +2 dirs · strip** (1 cross-edges)
- **harnessed +2 dirs · opencode_agent_name** (1 cross-edges)
- **tests +3 dirs · get** (1 cross-edges)
- **tests +2 dirs · patch_all** (1 cross-edges)
- **. +2 dirs · git_common_dir_checked** (1 cross-edges)
- **harnessed +1 dirs · instance_name** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-337")
explore(operation:"context", task:"understand harnessed +2 dirs · _make_entry", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
