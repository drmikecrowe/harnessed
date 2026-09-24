---
name: gortex-tests-1-dirs-completedprocess
description: "Work in the tests +1 dirs · CompletedProcess area — 134 symbols across 17 files (69% cohesion)"
---

# tests +1 dirs · CompletedProcess

134 symbols | 17 files | 69% cohesion

## When to Use

Use this skill when working on files in:
- ``
- `tests/test_claude_container_auth.py`
- `tests/test_ctrquery_timeouts.py`
- `tests/test_docker_userns.py`
- `tests/test_launch_secrets.py`
- `tests/test_launcher_build.py`
- `tests/test_launcher_install.py`
- `tests/test_launcher_scan_command.py`
- `tests/test_launcher_test_command.py`
- `tests/test_launcher_timeouts.py`
- `tests/test_launchscript.py`
- `tests/test_project_scoped_services.py`
- `tests/test_recipe_hash.py`
- `tests/test_recipe_tests_on_install.py`
- `tests/test_rescan_credentialed.py`
- `tests/test_svcstate_timeouts.py`
- `tests/test_unproxied_secrets_warning.py`

## Key Files

| File | Symbols |
|------|---------|
| `` | CompletedProcess |
| `tests/test_claude_container_auth.py` | fake_run, kwargs, cmd |
| `tests/test_ctrquery_timeouts.py` | timeout, cmd, warn, kw, _fake_bounded, ... |
| `tests/test_docker_userns.py` | _fake_run, k, a, _capture, cmd, ... |
| `tests/test_launch_secrets.py` | TestResolveSecretsVarlockFailure, tmp_path, test_varlock_error_drops_global, monkeypatch |
| `tests/test_launcher_build.py` | cmd, fake_run, kwargs, cmd, kwargs, ... |
| `tests/test_launcher_install.py` | cmd, check, kwargs, fake_run |
| `tests/test_launcher_scan_command.py` | fake_bounded, kwargs, cmd |
| `tests/test_launcher_test_command.py` | monkeypatch, delegated, fake_run, kwargs, cmd, ... |
| `tests/test_launcher_timeouts.py` | test_teardown_timeout_does_not_swallow_the_bodys_exception, cmd, err, kw, kw, ... |
| `tests/test_launchscript.py` | path, args, args, path, other_toplevel, ... |
| `tests/test_project_scoped_services.py` | a, monkeypatch, monkeypatch, fake_run, fake_run, ... |
| `tests/test_recipe_hash.py` | test_no_stacks_is_a_noop, tmp_path, monkeypatch |
| `tests/test_recipe_tests_on_install.py` | k, k, _spy, a, cmd, ... |
| `tests/test_rescan_credentialed.py` | monkeypatch, cmd, tmp_path, a, monkeypatch, ... |
| `tests/test_svcstate_timeouts.py` | kw, kw, cmd, _inner, timeout, ... |
| `tests/test_unproxied_secrets_warning.py` | run, kw, cmd |

## Connected Communities

- **tests +3 dirs · append** (12 cross-edges)
- **tests +2 dirs · update** (7 cross-edges)
- **harnessed +3 dirs** (7 cross-edges)
- **tests +2 dirs · harnessed.launcher** (4 cross-edges)
- **tests +2 dirs · patch_all** (3 cross-edges)
- **tests +3 dirs · get** (3 cross-edges)
- **. +1 dirs · _gate** (1 cross-edges)
- **tests +3 dirs · split** (1 cross-edges)
- **tests +2 dirs · patch** (1 cross-edges)
- **tests +2 dirs · validate_agent_pin** (1 cross-edges)

## How to Explore

```
analyze(operation:"communities", id:"community-267")
explore(operation:"context", task:"understand tests +1 dirs · CompletedProcess", format:"gcx")
```

_`format: "gcx"` returns the [GCX1 compact wire format](../../docs/wire-format.md) — round-trippable, ~27% fewer tokens than JSON. Drop it for JSON output; agents using `@gortex/wire` or the Go `github.com/gortexhq/gcx-go` package decode either._
