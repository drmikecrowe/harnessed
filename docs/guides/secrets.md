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

`harnessed` runs `varlock` **on the host** to resolve `op://` refs. This is required, not a
preference: 1Password's desktop app authorizes the `op` CLI by **calling application** (your
terminal), so app-auth (`@initOp(allowAppAuth=true)`) works on the host but **cannot** work
from inside a container — there the desktop app has no host app to bind the grant to, and `op`
fails with *"cannot connect to 1Password app"* no matter which socket is mounted. (The
`~/.1password/agent.sock` mounted into every stack is the **SSH agent**, for git signing — not
the `op` app-auth transport.)

1. The launcher detects `~/.config/harnessed/.env.schema` (one `[ -f ]` test — inert when
   absent; with no schema, `varlock` is never invoked).
2. It runs `varlock load --format env` **on the host**, in the schema's directory. The first
   run prompts the 1Password desktop app to **Authorize** your terminal for CLI access —
   approve it once and the grant persists.
3. The resolved dotenv is captured into a **mode-0600 temp `--env-file`** under `$TMPDIR`.
4. That `--env-file` is spread into the launched container(s) — **both pod members** (isolated),
   the **instance** (transparent), the **sidecar** (`svc up`), and the **scan step**
   (`harnessed build`) — so resolved secrets reach the container as **env only**, never a
   profile, image layer, or repo file (T-05-05).
5. The temp file is **unlinked** after launch (T-05-06).

This needs `varlock` on the host (`npm i -g varlock`); `op` (already on most 1Password hosts) is
driven by varlock via app-auth. The "podman-only host" invariant still holds for the
**no-secrets** path — varlock is never touched without a schema. Hosts without host `varlock`
fall back to the headless path below.

## Headless / CI fallback (`OP_SERVICE_ACCOUNT_TOKEN`)

For environments without the 1Password desktop app **or** without host `varlock` (CI, the
nightly re-scan timer, a headless server), set `OP_SERVICE_ACCOUNT_TOKEN` in the launcher env.
With a service-account token, resolution runs in a throwaway `harnessed-tools` container (HTTPS
bearer auth — no desktop app, no app-auth, no socket). `harnessed` forwards the token only when
it is already set — it never prompts and never echoes.

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
   resolve from 1Password and reach the build-time scan step via the same host-resolved
   `--env-file` path (`build_stack` calls `resolve_secret_env` before the scan). Recommended for
   operators already using varlock. Get a **Snyk** token at
   <https://app.snyk.io/account/personal-access-tokens> (Account settings → Personal Access
   Tokens → Generate); a **Socket** key from <https://socket.dev> → Settings → API tokens.
2. **Via the launcher env directly** — for a one-off without varlock/1Password, export the token
   before building. The build scan is env-gated on `SNYK_TOKEN`, and `build_stack` forwards it:

   ```bash
   SNYK_TOKEN='<token>' harnessed build tracer-time     # scoped to the one invocation
   ```
3. **Via `harnessed auth snyk|socket`** — persists the token to host config
   (`~/.config/configstore/snyk.json` for snyk), for **interactive `snyk`/`op` use inside the
   tools container**. This does **not** feed `harnessed build`'s scan step — that gate is the
   `SNYK_TOKEN` env var, not configstore — so use path 1 or 2 for the build scan:

   ```bash
   harnessed auth snyk      # opens a browser flow at a TTY; writes configstore/snyk.json
   harnessed auth socket    # prompts for the API token; stores in socket's config
   ```

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
