# Codebase Concerns

**Analysis Date:** 2026-06-27

## Tech Debt

**Dead dual-scan subsystem:**
- Issue: `src/harnessed/scan.py` contains a full gating scanner (`ScanError`, `run_source_scan`, `run_image_scan`, `run_snyk_container_scan`, Socket.dev handling) that predates the host-native restructure. `launcher.py` does NOT import `scan.py` — none of it runs during `harnessed build`. The in-image advisory scan (`catalog/base/harnessed-scan`, emitted by `emit.write_derived_dockerfile`) is the current model. The old gating model is dead code.
- Files: `src/harnessed/scan.py`, `src/harnessed/cli.py`
- Impact: Reader confusion — two scan systems, one dead. Any engineer reading the code sees `ScanError` ("the build must abort") and assumes the build aborts on HIGH+ findings; it does not. The `harnessed-tools` CLI entrypoint (`cli.py`) also imports the dead scanner functions.
- Fix approach: Documented in `docs/todos/2026-06-26-remove-pre-restructure-scan-py.md`. Decide if `run_image_scan_online` (nightly rescan) is still needed; if so, retain only that and remove the gating/container/source-scan + Socket.dev code. Evaluate whether `harnessed-tools` (`cli.py`) is itself fully legacy.

**`harnessed-tools` CLI is likely legacy:**
- Issue: `pyproject.toml` registers `harnessed-tools = "harnessed.cli:main"` as a CLI entrypoint. `ARCHITECTURE.md` and `CLAUDE.md` both state "no tool container; assembly runs in-process." The launcher (`launcher.py`) calls `assemble()` directly — `harnessed-tools assemble` is a parallel, unused path.
- Files: `src/harnessed/cli.py`, `pyproject.toml`
- Impact: Installs an extra binary that does nothing in normal operation. Imports dead scanner code.
- Fix approach: Decide fate (see `docs/todos/2026-06-26-remove-pre-restructure-scan-py.md`); if keeping, strip the scan subcommands.

**HATAGO_PORT defined in three places:**
- Issue: Port 3535 and the `http://localhost:3535/mcp` endpoint are independently defined in `src/harnessed/paths.py` (line 20), `src/harnessed/emit.py` (lines 30–31), and `src/harnessed/capability.py` (lines 48, 54). The canonical location should be `paths.py`, but `emit.py` and `capability.py` define their own copies.
- Files: `src/harnessed/paths.py`, `src/harnessed/emit.py`, `src/harnessed/capability.py`
- Impact: If the port changes, must be updated in three places. `capability.py` reads `HATAGO_PORT` from env at import time but `emit.py` does not — a mismatch if the port is ever overridden.
- Fix approach: Have `emit.py` and `capability.py` import `HATAGO_PORT` from `paths.py`.

**`_service_refs` in launcher ignores catalog root context:**
- Issue: `_service_refs(stack)` in `launcher.py` (line 525–531) calls `load_stack_with_recipes(None, stack)` — hardcoded `None` means it always resolves across the full catalog roots. If a build was driven with `--root <test-fixture-dir>`, the service resolution in `_ensure_services` uses the production catalog, not the test root.
- Files: `src/harnessed/launcher.py` (line 525)
- Impact: Low risk in production (only one root in normal use); in integration tests the service catalog is the production catalog regardless of `--root`.
- Fix approach: Thread the `root` parameter from `_build_stack` through `_service_refs`/`_ensure_services`.

**Web site has drifted from current documentation:**
- Issue: The `web/` Astro site was built against an earlier model. Key concepts (host-native Python CLI, `catalog/agents/`, no tool container, the `harnessed build` flow) are not reflected in the site's copy. The current vocabulary (agent / recipe / service / stack) differs from what the site uses.
- Files: `web/src/`, `web/src/components/`, `web/src/pages/`
- Impact: New users reading the website get incorrect mental model. Install instructions on the site may contradict `README.md`.
- Fix approach: Documented in `docs/todos/2026-06-26-overhaul-web-folder-to-match-new-docs.md`. Audit `web/src` against `ARCHITECTURE.md`, `README.md`, `docs/harnessed-design.md`; re-derive copy from the canonical markdown.

**`profiles/` directory committed to repo root:**
- Issue: The design says profiles are emitted to `$XDG_DATA_HOME/harnessed/profiles/` (not the repo). A `profiles/` directory exists in the repo root and is listed in `.gitignore` (`/profiles/`). The directory itself is gitignored, but it holds stale built artifacts from previous runs (e.g., `antigravity-time`, `claude-multi`, `codex-time`, `floating-test`, etc.).
- Files: `profiles/` (repo root)
- Impact: The directory is gitignored so it can't be accidentally committed, but its presence in the repo root is confusing and indicates the XDG path migration may not be fully adopted.
- Fix approach: Delete the local `profiles/` directory; confirm `paths.profiles_root()` (`$XDG_DATA_HOME/harnessed/profiles/`) is consistently used everywhere.

## Known Bugs / Gaps

**Advisory scan never gates the build:**
- Symptoms: `harnessed build <stack>` completes successfully even when the in-image scan (`harnessed-scan`) finds HIGH or CRITICAL CVEs. The scan is strictly advisory — it reports and writes `scan-report.json` but never fails the build.
- Files: `src/harnessed/emit.py` (line 144: "ADVISORY"), `src/harnessed/launcher.py` (`_surface_scan_report`)
- Trigger: Any recipe that installs a dependency with a known HIGH+ CVE.
- Workaround: Check `~/.local/share/harnessed/profiles/<stack>/scan-report.json` manually after build; the launcher prints a one-line advisory if crit/high > 0.

**No automated CI for the Python CLI:**
- Symptoms: The only CI workflow (`.github/workflows/deploy-web.yml`) deploys the `web/` Astro site. There is no CI workflow that runs `pytest` against the Python CLI, checks types, or lints.
- Files: `.github/workflows/` (only `deploy-web.yml`)
- Impact: Regressions in `launcher.py`, `schema.py`, `assemble.py`, `capability.py` are not caught until a human runs tests locally.
- Fix approach: Add a GitHub Actions workflow that runs `uv run pytest` on push/PR.

**No user-facing install script:**
- Symptoms: Installation requires the user to already have both podman and uv/pipx, then manually run `uv tool install ./harnessed`. There is no single bootstrap script new users can run.
- Files: `README.md`, `src/harnessed/paths.py`
- Impact: High barrier to first-time setup. Blocks adoption.
- Fix approach: Documented in `docs/todos/2026-06-26-plan-user-install-script.md`. Requires design decisions on delivery method (hosted curl script vs checked-in `install.sh`), whether to install podman, and source (PyPI vs repo).

## Security Considerations

**Advisory-only supply chain scan:**
- Risk: The in-image `harnessed-scan` layer surfaces CVE findings but does NOT abort the build. A recipe installing a dependency with CRITICAL CVEs produces a `scan-report.json` and a warning — but the image is built and can be launched.
- Files: `catalog/base/harnessed-scan`, `src/harnessed/emit.py` (line 145: scan is advisory only)
- Current mitigation: One-line advisory summary printed at the end of `harnessed build`; `scan-report.json` written to the profile dir.
- Recommendations: Consider making HIGH+ findings an opt-in gate (`--strict-scans`), or at minimum surface the finding count prominently in `harnessed list`.

**omp agent dir is rw-mounted and fully shared with host:**
- Risk: The `~/.omp/agent` directory (containing auth credentials, config, usage, and sessions) is bind-mounted rw into the omp container. A compromised or misbehaving AI agent inside the container can read/modify the host's omp credentials and all session data.
- Files: `src/harnessed/launcher.py` (`_omp_agent_mount`, line 489–510)
- Current mitigation: Documented trade-off; SQLite WAL coordinates concurrent writes.
- Recommendations: Consider a copy-on-start model (as used for `.claude.json`) for sensitive auth files, or at minimum mount `agent/auth*` files ro.

**Antigravity harness re-prompts OAuth every fresh launch (no credential persistence):**
- Risk: Without an in-pod keyring, the `agy` harness stores no OAuth tokens across container recreates. Every `--fresh` launch requires the user to complete a browser OAuth flow. In a future scenario where the user delegates an automated session, it would re-prompt unexpectedly.
- Files: `src/harnessed/launcher.py` (no `_antigravity_auth_mount`), `catalog/agents/antigravity/`
- Current mitigation: Documented as a known limitation.
- Recommendations: Documented in `docs/todos/2026-06-21-persist-agy-auth-via-in-pod-keyring.md`. Implement an in-pod gnome-keyring with a harnessed-owned state dir.

## Performance Bottlenecks

**Base image rebuild on every `harnessed build <stack>`:**
- Problem: `_build_stack` always calls `_build_base_image(rt)` (line 225), which re-runs `podman build` on `harnessed-base` on every stack build. The build is layer-cached and is a no-op when unchanged, but the `podman build` subprocess still runs and checks the cache.
- Files: `src/harnessed/launcher.py` (line 225, `_build_base_image`)
- Cause: Ensures that a stale base never silently propagates; the comment acknowledges "cache-backed: a no-op when the base Dockerfile is unchanged."
- Improvement path: Could skip if the base Dockerfile mtime matches a stored hash, but the current design is simple and correct.

**Temporary container create/rm cycle for baked extension extraction:**
- Problem: `_merge_baked_extensions` and `_surface_scan_report` each run `podman create <image>` + `podman cp` + `podman rm` to extract files from the built image. This adds two sequential temp-container lifecycles per stack build.
- Files: `src/harnessed/launcher.py` (lines 278–332)
- Cause: No podman API for direct file extraction without a running container.
- Improvement path: These can be parallelized into a single temporary container per build (create once, copy both artifacts, rm once).

## Fragile Areas

**Apple `container` runtime is unsupported (hardcoded `localhost:3535`):**
- Files: `src/harnessed/emit.py` (line 31: `HATAGO_ENDPOINT = "http://localhost:3535/mcp"`), `src/harnessed/capability.py` (line 48), all harness Dockerfiles baking MCP config
- Why fragile: The current design assumes the harness and hatago containers share `localhost` via a pod/`--network container:`. Apple `container` runs one lightweight VM per container with no shared netns — `localhost:3535` from the harness container cannot reach hatago.
- Safe modification: Do not change the endpoint without addressing the full matrix (`.mcp.json`, opencode's `~/.config/opencode`, gemini's `~/.gemini/settings.json`, antigravity's `mcp_config.json`, codex's `config.toml`).
- Full solution documented in `docs/todos/2026-06-21-apple-container-named-network-mcp-endpoint.md`.

**`launch_headless` parses instance name from stdout with regex:**
- Files: `src/harnessed/capability.py` (lines 237–243)
- Why fragile: Instance name is parsed via `re.search(r"Isolated pod running headless:\s+(\S+)", combined)` from the combined stdout+stderr of the `harnessed` subprocess. Any change to the success message in `launcher.py` (line 709) silently breaks the capability test.
- Safe modification: When changing the success message in `launcher.py`, update the regex in `capability.py` simultaneously. Consider exporting the instance name via a machine-readable channel (e.g., a temp file or env var) instead.

**`_session_active` uses `podman top` output parsing:**
- Files: `src/harnessed/launcher.py` (lines 356–367)
- Why fragile: `_session_active` determines whether a session is live by running `podman top <inst> comm` and checking if any non-`sleep` process exists. If the `prune` command runs while a harness is mid-startup (before it execs into the shell), it may incorrectly prune an instance. Also, `podman top` output format is not guaranteed stable across podman versions.
- Safe modification: Add a startup/ready marker file inside the container before exec.

**Schema parser is tolerant of unknown fields without warning:**
- Files: `src/harnessed/schema.py` (docstring: "tolerant of unknown fields")
- Why fragile: Misspelled recipe fields (e.g. `skkills:` instead of `skills:`) are silently ignored. There is no validation that unknown top-level keys in `recipe.yaml` are flagged.
- Safe modification: Acceptable for forward-compat; consider adding a `--strict` mode for recipe authors.

## Scaling Limits

**Single hatago port (3535) — no multi-stack port allocation:**
- Current capacity: All stacks use port 3535 inside their pod. Multiple stacks running simultaneously each have their own pod/netns, so there is no port conflict inside containers.
- Limit: Shared-service sidecars are published on fixed host ports (defined in `service.yaml`). Running two instances of the same stack against two projects shares one service container — this is by design but means concurrent sessions that modify service state will interfere.
- Scaling path: Service containers are intentionally shared; this is documented as an intentional design choice.

## Dependencies at Risk

**`hatago-mcp-hub` is run via `pnpm dlx` (latest):**
- Risk: `pnpm dlx @himorishige/hatago-mcp-hub` pulls the latest npm release at build time. If the hatago API changes (e.g., config schema, CLI flags, transport default), the baked hatago image silently adopts the new version.
- Impact: A breaking hatago release could cause `harnessed build` or `harnessed test` to fail without a code change.
- Migration plan: Pin `@himorishige/hatago-mcp-hub` to a specific version in `catalog/base/Dockerfile.hatago`. The `pnpm-workspace.yaml` `minimumReleaseAge` policy (if applied to the hatago build) would add quarantine time.

**`ruamel.yaml` pinned to `>=0.18,<0.19`:**
- Risk: `ruamel.yaml` 0.18.x is the current stable series; `<0.19` is forward-compatible. Not a risk today but the project should track when 0.19 is released.
- Impact: If 0.19 has breaking API changes, the pin protects the project; the pin will need updating with testing.
- Migration plan: No action needed now; track ruamel.yaml releases.

## Missing Critical Features

**No CI for the Python CLI:**
- Problem: No GitHub Actions workflow runs `pytest`, type checks (`mypy`/`pyright`), or linting (`ruff`) on the Python source.
- Blocks: Confident refactoring, accepting external contributions, automated regression detection.

**No PyPI publication:**
- Problem: `pyproject.toml` has the project configured (`name = "harnessed"`, `version = "0.1.0"`) but there is no workflow or documentation for publishing to PyPI.
- Blocks: The planned one-shot install script (`docs/todos/2026-06-26-plan-user-install-script.md`) requires either a PyPI release or a git-hosted install.

## Test Coverage Gaps

**`launcher.py` has zero direct unit tests:**
- What's not tested: All pod lifecycle operations (`_build_stack`, `launch`, `_attach`, `_pod_teardown`, `_merge_baked_extensions`, `_surface_scan_report`). These are integration-only paths requiring a live podman.
- Files: `src/harnessed/launcher.py` (1082 lines), `tests/` (no `test_launcher.py`)
- Risk: Regressions in mount arg assembly, image build order, stale-image detection, or pod creation go undetected until a live run.
- Priority: High. The pure helper functions (`_img_differs`, `_build_mount_args`, `_claude_config_seed_mount`, `_omp_agent_mount`) are unit-testable without podman and should be extracted and tested.

**`capability.py` pure functions are partially tested:**
- What's not tested: `expected_capabilities` (stack + recipe fixture), `build_report` (expected vs live diff logic), `_exec` wrapper behavior.
- Files: `src/harnessed/capability.py`, `tests/` (no dedicated capability unit test)
- Risk: Manifest-oracle logic could silently diverge from what the live introspection produces.
- Priority: Medium. `build_report` is a pure function and fully testable.

**No test for `_service_refs`/`_ensure_services`:**
- What's not tested: Service resolution, `_wait_service`, the service-refs-to-ensure-services flow.
- Files: `src/harnessed/launcher.py` (lines 520–566)
- Risk: Service port mismatches or resolution failures surface only during live stack launches.
- Priority: Medium.

---

*Concerns audit: 2026-06-27*
