# Testing Patterns

**Analysis Date:** 2026-06-27

## Test Framework

**Runner:**
- pytest 8.x
- Config: `pyproject.toml` (`[tool.pytest.ini_options]` → `testpaths = ["tests"]`)

**Assertion Library:**
- pytest built-in assertions (no `unittest.TestCase`, no third-party assertion libraries)

**Coverage:**
- `pytest-cov` installed (dev dependency)

**Run Commands:**
```bash
mise exec -- uv run pytest                    # Run all tests
mise exec -- uv run pytest tests/test_scan.py # Run single file
mise exec -- uv run pytest --cov              # Coverage (pytest-cov)
HARNESSED_PODMAN=1 mise exec -- uv run pytest # Include live podman tests
```

## Test File Organization

**Location:**
- Separate `tests/` directory at repo root (NOT co-located with source)
- `tests/__init__.py` present (makes it a package)

**Naming:**
- `test_<module_name>.py` maps to `src/harnessed/<module_name>.py`
- e.g., `tests/test_emit.py` tests `src/harnessed/emit.py`

**Directory structure:**
```
tests/
├── __init__.py
├── test_claude_config_seed.py    # launcher auth seeding (claude)
├── test_emit.py                  # profile artifact emission
├── test_launcher_install.py      # shim install + image staleness
├── test_omp_auth_seed.py         # launcher auth seeding (omp)
├── test_paths.py                 # path resolver
├── test_recipes_integration.py   # assembly oracle + live podman tests
├── test_scan.py                  # CVSS scoring + scan gate
└── test_schema.py                # schema validators
```

## Test Structure

**Suite organization:** Class-based grouping by feature/function under test.

```python
class TestWriteMcpJson:
    def test_creates_mcp_json_at_profile_root(self, tmp_path):
        out = write_mcp_json(tmp_path)
        assert out == tmp_path / ".mcp.json"
        assert out.is_file()

    def test_content_has_single_hatago_entry(self, tmp_path):
        write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert HATAGO_MCP_KEY in data["mcpServers"]
        assert len(data["mcpServers"]) == 1
```

**Test method naming:** `test_<scenario_description>` — describes WHAT should happen, not HOW.
- `test_npm_command_raises` (not `test_validate_no_raw_npm_1`)
- `test_profile_with_mcp_json_is_built` (not `test_is_built_true`)
- `test_floating_pin_is_rejected`

**Class naming:** `Test<Feature>` — maps to the thing being tested, not the test file.
- `TestWriteMcpJson`, `TestValidateNoRawNpm`, `TestCvss3Base`, `TestGate`, `TestProfileDir`

**Patterns:**
- Setup: private helper methods on the class (e.g., `def _stack(self)`, `def _make_recipe(...)`)
- No `setUp`/`tearDown` — use `tmp_path` and `monkeypatch` fixtures instead
- One assertion cluster per test (each test covers one logical behavior, may have multiple asserts)
- Comment the "why" in complex assertions: `# Must be profile_dir/.mcp.json, NOT profile_dir/.claude/.mcp.json`

## Fixtures

**Built-in pytest fixtures used:**
- `tmp_path` — isolated temporary directory per test; used for all file I/O tests
- `monkeypatch` — patch env vars, module attributes, `Path.home()`

**`monkeypatch` patterns:**
```python
# Env var manipulation
monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
monkeypatch.delenv("XDG_DATA_HOME", raising=False)

# Patching Path.home() for hermetic filesystem tests
monkeypatch.setattr(Path, "home", lambda: tmp_path)
```

**No conftest.py** — all fixtures are inline or built-in. No shared fixture file exists.

**No custom fixtures** — test classes use private helper methods instead:
```python
def _host(monkeypatch, tmp_path, claude_json: dict | None):
    home = tmp_path / "home"
    home.mkdir()
    if claude_json is not None:
        (home / ".claude.json").write_text(json.dumps(claude_json))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home
```

## Mocking

**Framework:** `monkeypatch` (pytest built-in) — no `unittest.mock`, no `pytest-mock`.

**What is mocked:**
- Filesystem (`Path.home()`, env vars via `monkeypatch.setenv`)
- External state (no network calls, no subprocess in unit tests)

**What is NOT mocked:**
- File I/O (use `tmp_path` for real file operations)
- Pure functions (tested directly with real inputs)
- Subprocess calls (integration tests use real subprocesses gated by `HARNESSED_PODMAN=1`)

## Negative/Error Testing

**Pattern:** `pytest.raises` with optional `match` to assert error message content.

```python
def test_npm_command_raises(self):
    r = _make_recipe(servers=[McpServer(name="s", command="npm", args=["install"])])
    with pytest.raises(RecipeLintError, match="pnpm"):
        validate_no_raw_npm(r)

def test_floating_pin_is_rejected(tmp_path):
    with pytest.raises(PinValidationError):
        assemble(None, NEGATIVE_STACK, tmp_path)
```

**Return-`None` testing:** Test that functions return `None` on bad input (not raise):
```python
def test_none_on_unparseable(self):
    assert _cvss3_base("not-a-cvss-vector") is None
```

## Parametrize

Used for multi-stack test coverage in integration tests:

```python
@pytest.mark.parametrize("stack", REAL_STACKS)
def test_stack_assembles_and_oracle_is_nonempty(stack, tmp_path):
    assemble(None, stack, tmp_path)
    _stk, caps = _oracle(stack)
    total = len(caps.mcp_servers) + len(caps.skills) + ...
    assert total > 0
```

`REAL_STACKS` is computed at module load time by scanning `catalog/stacks/`.

## Test Types

**Unit Tests (default suite):**
- Pure function tests: CVSS scoring, schema validators, path resolution
- File emission tests: write JSON/config files into `tmp_path`, read back and assert
- Hermetic: no network, no subprocess, no podman required
- Scope: one module per test file; one behavior per test method

**Integration Tests (assembly oracle — fast, no podman):**
- `tests/test_recipes_integration.py` Layer 1: parse real catalog stacks, run full assembly into `tmp_path`
- Tests that real catalog stacks resolve, assemble, and produce non-empty capability declarations
- Still hermetic (no podman); runs in the default `pytest` invocation

**Live Container Tests (podman-gated):**
- `tests/test_recipes_integration.py` Layer 2: `build` + `test` against a running instance
- Gated: `HARNESSED_PODMAN=1` env var required; skipped by default
- Uses `@pytest.mark.skipif(not _PODMAN, reason="set HARNESSED_PODMAN=1 for live podman tests")`
- Custom marker: `podman = pytest.mark.skipif(...)` defined at module level, applied as `@podman`
- Runs `harnessed build <stack>` and `harnessed test <stack> --json` via subprocess, parses JSON output

**E2E Tests:**
- No separate E2E framework; live container tests serve as behavioral E2E
- `harnessed test --json` output is the oracle: `report["ok"] is True`, capabilities cross-checked

## Security-Sensitive Test Annotation

Tests for security-critical code are annotated in the test file docstring:
```python
"""Tests for CVSS scoring and scan gate (C1 — security-critical code)."""
```

C1-tagged test files: `tests/test_scan.py`, `tests/test_schema.py`.

## Coverage

**Requirements:** No enforced minimum threshold in config.

**View Coverage:**
```bash
mise exec -- uv run pytest --cov=harnessed --cov-report=term-missing
```

**Coverage gaps:** `capability.py` (live introspection) and `launcher.py` (podman invocation) are covered only by the podman-gated integration layer.

## Negative Fixture Pattern

The codebase uses a "negative fixture stack" in the catalog to test rejection paths:

```python
NEGATIVE_STACK = "claude_floating-recipe"

def test_floating_pin_is_rejected(tmp_path):
    with pytest.raises(PinValidationError):
        assemble(None, NEGATIVE_STACK, tmp_path)
```

The fixture (`catalog/stacks/claude_floating-recipe/`) is a real catalog entry that deliberately violates the pin gate. Tests use `None` as `root` to resolve against the real catalog.

---

*Testing analysis: 2026-06-27*
