# Plan 01-01 Summary: Containerized Engine (host bootstrap + image lineage)

**Completed:** 2026-06-14
**Requirements:** ENG-01, ENG-02

## What was built

- **`harnessed`** — dependency-free host bash bootstrap. Resolves its real dir (symlink-aware), sources the shared lib, detects podman/docker (prefer podman), and dispatches: `transparent` (default stack), `build`/`--build`, `--list`, `--stop`, `--remove`, `--clean`, `--no-firewall`. Builds images on first run via `ensure_images`. Launch path sources `lib/harnessed-transparent.sh` at runtime (plan 01-03).
- **`lib/harnessed-common.sh`** — shared helpers: `detect_runtime`, `image_exists`, `build_images` (host `podman build` of base then claude), `ensure_images` (auto-build first run), instance lifecycle (`generate_instance_name` → `harnessed-<stack>-<projhash>`, `container_exists/running`, `list/stop/remove/clean_instances`, `stop_if_last_session`), `project_relpath` (→ `/home/harnessed/<relpath>`), and `apply_firewall`.
- **`base/Dockerfile.harnessed-base`** — mise/node@22/pnpm/python toolchain + common tools + 1Password CLI, user renamed to `harnessed` with `HOME=/home/harnessed` (D-06). Split from the old `Dockerfile`.
- **`base/Dockerfile.harnessed-claude`** — `FROM harnessed-base` + Claude Code installer (lineage only, §6).

## Key decisions honored

- **No DooD (ENG-02):** the host runs `podman build`/`podman run` directly. No socket, no `CONTAINER_HOST`/`DOCKER_HOST`, no daemon-in-container. The `harnessed-tools` assembler image is deferred to Phase 2.
- **D-06:** in-container home is `/home/harnessed`; the fixed `harnessed` user keeps UID 1000 so `--userns=keep-id` maps the host user.
- **D-04:** images auto-build on first run; `harnessed build`/`--build` forces a rebuild.
- **container parity (toward MODE-02):** `--list/--stop/--remove/--clean` ported so the Phase-1 `container` alias keeps today's behavior.

## Verification

- `bash -n harnessed` ✓ and `bash -n lib/harnessed-common.sh` ✓ (syntax).
- **Live image build:** running via host `podman build` (base → claude). This is plan 01-01's `checkpoint:human-verify` — on the operator's machine: `./harnessed build`, then `podman run --rm harnessed-claude bash -lc 'echo $HOME; which claude'` → expect `/home/harnessed` + a claude path. (Build attempted in-session for evidence; final confirmation is the operator's.)

## Files

- `harnessed`, `lib/harnessed-common.sh`, `base/Dockerfile.harnessed-base`, `base/Dockerfile.harnessed-claude`

## Commits

- `1e52029` feat(01-01): harnessed host bootstrap + shared bash helpers
- `009c781` feat(01-01): base/claude image lineage (home /home/harnessed)
