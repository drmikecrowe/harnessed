# Secrets setup (opt-in varlock + 1Password)

`harnessed` works fully without any secrets backend. This guide is for operators who
*want* 1Password-backed secrets resolved into their stacks at launch — opt-in, env-only,
never baked into an image or committed file. For the *why* (threat model, design rationale),
see [docs/harnessed-design.md §16](../harnessed-design.md#16-proposed-secrets--varlock--1password-optional).

## What this does

With a `.env.schema` present, secrets resolve from 1Password via [varlock](https://varlock.dev)
and reach the pod members as **environment variables only** — never written to a profile, a
container image layer, or a repo file. Absent the schema, `harnessed` is bit-for-bit today's
behavior: varlock is never invoked, no `op` call, no env mutation. The opt-in switch is a
single filesystem test.

## Quickstart

```bash
# 1. Copy the shipped template into your XDG harnessed config dir.
mkdir -p ~/.config/harnessed
cp .env.schema.example ~/.config/harnessed/.env.schema

# 2. Edit the op:// refs to match your 1Password vault items.
#    Example (Private vault, items named "Snyk" and "SocketDev", field "credential"):
#       SNYK_TOKEN=op(op://Private/Snyk/credential)
#       SOCKET_SECURITY_API_KEY=op(op://Private/SocketDev/credential)
$EDITOR ~/.config/harnessed/.env.schema

# 3. Launch any isolated stack. Resolved secrets reach the pod as env only.
harnessed tracer-time
```

The `.env.schema.example` shipped at the repo root is the canonical template — copy it,
don't author from scratch. The `@plugin(@varlock/1password-plugin@1.2.0)` +
`@initOp(allowAppAuth=true)` decorators are required (they wire the `op(op://…)` resolver
and tell varlock to use the mounted agent socket for app-auth).

## How resolution works

`harnessed` is host-podman-only — there is no host Node, no host varlock, no host `op`.
Resolution happens **inside a throwaway `harnessed-tools` container**:

1. The launcher detects `~/.config/harnessed/.env.schema` (one `[ -f ]` test — inert when
   absent).
2. It runs a `--rm --userns=keep-id` `harnessed-tools` container with:
   - `-e HOME=$CONTAINER_HOME` so the `tools` user resolves the agent socket to the mounted
     `$CONTAINER_HOME/.1password/agent.sock` (NOT the unmounted `/home/tools/.1password/…`).
   - The schema (ro) + a writable scratch `$CONTAINER_HOME` (resolved env crosses back here).
   - The 1Password agent socket (`~/.1password/agent.sock` → `$CONTAINER_HOME/.1password/agent.sock`).
3. Inside the container: `varlock load --format env` resolves the `op://` refs against the
   agent socket and emits dotenv (`KEY=value`) lines.
4. The host captures the result into a **mode-0600 temp `--env-file`** under `$TMPDIR` and
   passes it to both pod members (hatago + harness) via `--env-file`.
5. After the interactive attach returns, the temp file is **unlinked** (T-05-06).

The agent socket is the same one already wired for every stack by
[lib/harnessed-mounts.sh:22-27](../../lib/harnessed-mounts.sh) (the `op` app-auth transport,
`allowAppAuth=true`). No token is written to disk; the desktop app holds the credential.

## Headless / CI fallback (`OP_SERVICE_ACCOUNT_TOKEN`)

For environments without the desktop app (CI, the nightly re-scan timer), set
`OP_SERVICE_ACCOUNT_TOKEN` in the launcher env. varlock's 1Password plugin will use it
instead of the agent socket. `harnessed` forwards it through to the throwaway resolve
container only when it is already set — it never prompts and never echoes.

> **Caution (per CLAUDE.md "What NOT to Use"):** a visible service-account token leaks into
> any process sharing the env. **Scope it narrowly to the invocation** — prefix it on the
> command line (`OP_SERVICE_ACCOUNT_TOKEN=… harnessed tracer-time`) or inject via your CI
> secret store. Do **not** `export` it in your shell profile or `~/.bashrc`, and do not
> leave it in a long-lived shell session.

## Per-service secrets

Sidecar services (hindsight, openbrain, …) can declare their own schemas at
`~/.config/<service>/.env.schema` — e.g. `~/.config/hindsight/.env.schema` for the hindsight
sidecar. The schema syntax is identical; see the `.env.schema.example` header comment.

## Scanner tokens

`harnessed build` runs the supply-chain scanners (snyk, Socket.dev) when their tokens are
present and warns-and-skips otherwise. Two ways to provide a token:

1. **Via `.env.schema` (this guide)** — the `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` refs
   resolve from 1Password the same way as any other secret, and reach the build-time scan
   step via the same `--env-file` path (`build_stack` calls `resolve_secret_env` before the
   scan). This is the recommended path for operators already using varlock.
2. **Via `harnessed auth snyk|socket`** — one-shot setup that persists the token to host
   config (`~/.config/configstore/snyk.json` for snyk), never an image layer:

   ```bash
   harnessed auth snyk      # opens a browser flow at a TTY; writes configstore/snyk.json
   harnessed auth socket    # prompts for the API token; stores in socket's config
   ```

   The token persists across launches on the host; `harnessed build` reads it via the
   standard scanner-config path. Use this when you do NOT want varlock/1Password and just
   want a persistent scanner token.

## Verification

After launching with a schema present, confirm secrets reached the pod **and** did not leak:

```bash
# 1. The value reached the pod env (replace <instance> + <KEY> with your own):
podman exec <instance> env | grep SNYK_TOKEN
# expected: SNYK_TOKEN=<the resolved value>

# 2. The value is NOT in the committed profile:
grep -r SNYK_TOKEN profiles/    # expected: no matches

# 3. The value is NOT baked into the image:
podman history harnessed-hatago:latest | grep -i snyk    # expected: no matches

# 4. The temp env-file is gone after launch:
ls /tmp/harnessed-env.* 2>/dev/null    # expected: no matches (unlinked post-launch)
```

If `podman exec … env | grep <KEY>` returns nothing but you expected it to, check that:
- `~/.config/harnessed/.env.schema` exists and has a non-`@optional` entry for `<KEY>`.
- The 1Password desktop app is running and unlocked (the agent socket must be live for
  app-auth), OR `OP_SERVICE_ACCOUNT_TOKEN` is set in the launcher env.
- The `op(op://Vault/Item/field)` ref points at a real vault item.

## See also

- [docs/harnessed-design.md §16](../harnessed-design.md#16-proposed-secrets--varlock--1password-optional) — the design rationale (the *why*).
- [docs/harnessed-design.md §7](../harnessed-design.md) — supply-chain scanners + the warn-and-skip contract.
- [.env.schema.example](../../.env.schema.example) — the canonical schema template.
