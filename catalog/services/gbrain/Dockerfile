# Service image: gbrain — a shared, long-lived knowledge brain (plan 04-01 / GAP 5).
#
# Built by `harnessed svc up gbrain` on first use (or `podman build -t harnessed-gbrain:latest`).
# Scanned by the BLD-02 image-scan gate when built via the launcher. This is a SERVICE Dockerfile,
# so it carries its OWN full lineage (FROM, USER, CMD) — unlike a recipe Dockerfile, which omits
# FROM/ARG HARNESS and toggles USER (recipe-authoring guide "Rules for recipe Dockerfiles").
#
# ── Deviation: Bun, not pnpm ──────────────────────────────────────────────────────────────────
# gbrain is a Bun project — `bun install`, Bun-specific server APIs, a `bun.lockb`. It CANNOT be
# installed or run with pnpm. The supply-chain rule "pnpm everywhere (no npm/npx)" targets the npm
# ecosystem; Bun is a distinct, upstream-mandated runtime, the same way Python servers use `uvx`.
# The BLD-03 raw-npm/npx lint (`\bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b`) does not match `bun`,
# so `bun install` passes. Do NOT "fix" this to pnpm — it would break the build.
#
# ── BYO external Postgres (v1) ────────────────────────────────────────────────────────────────
# v1 points gbrain at an OPERATOR-SUPPLIED external Postgres+pgvector via `DATABASE_URL` (Supabase
# / Neon / self-hosted with `CREATE EXTENSION vector`). The DB is supplied at `svc up` via env /
# .env.schema; harnessed does not manage it. PGLite cannot serve HTTP (upstream SECURITY.md: `--http`
# fails fast on PGLite), so a shared brain is Postgres-backed regardless. v2 (GAP 7) ships a managed
# Postgres sidecar via a compose file and removes this prerequisite.

# oven/bun is the runtime gbrain requires. Pin the exact tag (no :latest) — refresh to the current
# minor at `harnessed build`.
FROM oven/bun:1.2-debian

# gbrain ships NO semver git tags (only two `eval-run-v*` markers), so pin to a commit SHA — like
# the gstack recipe's fetch-by-SHA. HEAD at planning time: 814258d. Refresh to latest at
# `harnessed build` and record it here. A bare `github:garrytan/gbrain` (default branch) is a
# floating ref and would fail pin validation.
ARG GBRAIN_REF=814258dda67945ffec9457a1e73980e947b7e462
ENV GBRAIN_HTTP_TRUST_PROXY=0
# hatago is a direct single-hop proxy; keep the default loopback trust (no forwarded-header spoofing).

WORKDIR /app
RUN bun install -g "github:garrytan/gbrain#${GBRAIN_REF}"

# Brain repo + `~/.gbrain` config live under GBRAIN_DATA_DIR, persisted via the service volume.
# The Postgres retrieval index lives in the operator's external DB (out-of-band).
RUN mkdir -p /data/.gbrain
ENV GBRAIN_DATA_DIR=/data/.gbrain

# `--bind 0.0.0.0` is mandatory: gbrain defaults to 127.0.0.1 (loopback) and would refuse the pod's
# host-gateway (`host.containers.internal`) otherwise. `--public-url` is NOT set — the brain is
# reached over the pod network, not a public domain; no OAuth issuer/redirect needs it.
# `gbrain init --migrate-only` runs the DB migration against DATABASE_URL at container start, then
# `serve --http` exposes the MCP surface at /mcp (the path the service resolver emits). The
# long-lived bearer hatago sends is minted out-of-band by the operator (`gbrain auth create`) and
# placed in the recipe's `headers` via the user-overlay; it is not produced here.
EXPOSE 3112
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl -sf http://localhost:3112/.well-known/oauth-authorization-server || exit 1

CMD ["sh", "-c", "gbrain init --migrate-only --yes && gbrain serve --http --bind 0.0.0.0 --port 3112"]
