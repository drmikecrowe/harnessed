"""Build the `-v` / `-e` arguments that give a container its harness config and credentials.

One question per builder: what does podman need on the command line so the agent inside the
container finds this piece of host state where it expects it? Seeding a config dir, forwarding the
Claude OAuth token, mounting keyring state, wiring the 1Password/AWS credential paths, and laying
out the persist mounts.

Credentials are REFERENCED, never replicated (ARCHITECTURE.md §Constraints): these emit mount specs
and env vars pointing at the live store, and never copy a secret into a per-stack home.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from . import persist
from .console import _err
from .credmounts import (
    _gh_hosts_missing_plaintext_token,
    _git_identity_config_mount,
    _gnupg_mounts,
    _gpg_ssh_socket,
    _ssh_agent_args,
    _ssh_dir_mounts,
    _yubikey_device_args,
)
from .hosthome import _OAUTH_TOKEN_VAR
from .launchenv import _plain_env_values, _varlock_resolve
from .layout import _catalog_base
from .setupenv import _ensure_gitignore_entry
from .paths import CONTAINER_HOME
from .schema import load_stack_with_recipes

# The in-container home as a string, for interpolating into `-v src:dst` specs. Derived here rather
# than imported from launcher so the dependency points INTO this module; `paths.CONTAINER_HOME`
# stays the single source of truth for the value itself.
_CONTAINER_HOME_STR = str(CONTAINER_HOME)

def _build_mount_args(
    harness: str,
    prof: Path,
    mount_path: Path,
    config_volume: str = "",
    tools_volume: str = "",
) -> list[str]:
    """Assemble -v mount arguments for the harness container.

    `mount_path` is the host folder path-mirrored into the container (the project itself by default,
    or a parent dir via --mount-folder). The agent's cwd (start_dir) lives at or under it.

    `config_volume` is the composed agent-config volume from `_ensure_config_volume`. When empty
    (a harness with no `~/.claude` surface) nothing is mounted there at all.
    """
    args: list[str] = []
    ctr_home = _CONTAINER_HOME_STR

    # .mcp.json → $CONTAINER_HOME/.mcp.json (claude only; --mcp-config points here)
    mcp_src = prof / ".mcp.json"
    if mcp_src.is_file() and harness == "claude":
        args += ["-v", f"{mcp_src}:{ctr_home}/.mcp.json:ro"]

    # The agent config tree — ONE composed volume (bd harnessed-8px.21.2), not the per-subdir `:ro`
    # bind-mounts this replaces. Those mounted `<profile>/.claude/<subdir>` OVER the image's own,
    # hiding every skill/command an `install.script` had delivered: 70 of 75 skills invisible, and
    # an EMPTY profile `commands/` dir shadowing a real one, because `synclinks._fan_into` creates
    # skills/commands/rules unconditionally and the mount gate was existence, not non-emptiness.
    # `_ensure_config_volume` composes image content and profile content into one tree instead, so
    # there is nothing left to shadow.
    if config_volume and harness in ("claude", "omp", "opencode"):
        args += ["-v", f"{config_volume}:{ctr_home}/.claude"]
    # `~/.local` — mise installs + shims, $PNPM_HOME, and $HARNESSED_BIN_DIR, all three on PATH.
    # Harness-independent: `tools:` is a recipe declaration, not a claude-shaped one.
    if tools_volume:
        args += ["-v", f"{tools_volume}:{ctr_home}/.local"]

    # opencode persona config (bd main-rlw): the merged opencode.json + persona prompt (written
    # post-build by _merge_baked_opencode, only when the stack has `instructions:`) override the
    # image-baked config, wiring the custom agent + rules-glob. Mounted only when present, so a
    # no-instructions opencode stack falls back to the untouched image config.
    if harness == "opencode":
        oc_cfg = prof / "opencode" / "opencode.json"
        if oc_cfg.is_file():
            args += ["-v", f"{oc_cfg}:{ctr_home}/.config/opencode/opencode.json:ro"]
        oc_prompts = prof / "opencode" / "prompts"
        if oc_prompts.is_dir():
            args += ["-v", f"{oc_prompts}:{ctr_home}/.config/opencode/prompts:ro"]

    # antigravity identity (bd main-6he): the baked GEMINI.md + settings.json emitted by
    # emit.write_antigravity_identity mirror the container's ~/.gemini/ tree. Mounted ro only when
    # present, so a no-instructions antigravity stack leaves the image config untouched.
    if harness == "antigravity":
        agy_settings = prof / ".gemini" / "settings.json"
        if agy_settings.is_file():
            args += ["-v", f"{agy_settings}:{ctr_home}/.gemini/settings.json:ro"]
        agy_identity = prof / ".gemini" / "GEMINI.md"
        if agy_identity.is_file():
            args += ["-v", f"{agy_identity}:{ctr_home}/.gemini/GEMINI.md:ro"]

    # codex identity (bd main-6he): the baked AGENTS.md emitted by emit.write_codex_agents_md is
    # codex's top-level memory doc (~/.codex/AGENTS.md). Mounted ro only when present.
    if harness == "codex":
        codex_agents = prof / ".codex" / "AGENTS.md"
        if codex_agents.is_file():
            args += ["-v", f"{codex_agents}:{ctr_home}/.codex/AGENTS.md:ro"]

    # History dirs (rw) — sourced from host $HOME for session persistence.
    home = str(Path.home())
    for rel in (".claude/projects", ".claude/file-history", ".claude/tasks",
                ".claude/session-env", ".claude/todos"):
        host_d = Path(home) / rel
        host_d.mkdir(parents=True, exist_ok=True)
        args += ["-v", f"{host_d}:{ctr_home}/{rel}:rw"]

    # omp: the whole agent dir (auth + sessions) is bind-mounted rw from the host by
    # _omp_agent_mount (appended in launch()); _omp_mcp_seed_mount then shadows just its mcp.json
    # with a per-instance copy that adds the hatago endpoint.

    # Claude's OAuth credentials: seeded + mounted rw by _claude_creds_seed_mount (appended in
    # launch()) — a ro mount here would block Claude Code's in-container token refresh, causing
    # the "gets logged out" bug (see _claude_creds_seed_mount docstring).

    # egress-firewall.sh (run inside the container by _apply_firewall).
    fw = _catalog_base("egress-firewall.sh")
    if fw.is_file():
        args += ["-v", f"{fw}:/usr/local/sbin/egress-firewall:ro"]

    # Path mirroring (MNT2-02): the mount root is accessible at its host absolute path inside the
    # container (so the agent sees host paths). With --mount-folder this is a parent of the project.
    args += ["-v", f"{mount_path}:{mount_path}"]

    return args


def _claude_config_seed_mount(harness: str, inst: str, isolated_auth: bool = False) -> list[str]:
    """Mount a minimal, token-free ~/.claude.json stub so Claude Code skips first-run onboarding.

    The real OAuth token lives in the rw ~/.claude/.credentials.json mount (see
    _claude_creds_seed_mount). But Claude Code *also* gates its onboarding (the "Select login
    method" screen) on ~/.claude.json — a credentialed container with no .claude.json still shows
    onboarding. We seed ONLY onboarding + identity fields (never the token), copied from the host
    ~/.claude.json, written to a per-instance state dir and mounted rw so Claude's runtime writes
    never touch the host file. (design §4b; ports lib/harnessed-isolated-config.sh.)

    `isolated_auth` DROPS the identity half. `oauthAccount` carries the host account's email, uuid
    and organization, and `userID` its account id — copying them into a stack that authenticates as
    somebody ELSE would both hand your account metadata to a client-facing container and pair a
    stub identifying you with credentials belonging to them. The onboarding fields are all that
    branch needs; the client's own login repopulates the rest.
    """
    if harness not in ("claude", "omp"):
        return []

    oauth_account: object = {}
    user_id: object = ""
    host_json = Path.home() / ".claude.json"
    if host_json.is_file() and not isolated_auth:
        try:
            data = json.loads(host_json.read_text(encoding="utf-8"))
            oauth_account = data.get("oauthAccount", {})
            user_id = data.get("userID", "")
        except (ValueError, OSError):
            pass  # missing/malformed host config → seed the onboarding flag only

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    stub = state_dir / "claude.json"
    stub.write_text(
        json.dumps({
            "hasCompletedOnboarding": True,
            "firstStartTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "numStartups": 1,
            "oauthAccount": oauth_account,
            "userID": user_id,
        }),
        encoding="utf-8",
    )
    return ["-v", f"{stub}:{_CONTAINER_HOME_STR}/.claude.json:rw"]


def _claude_oauth_token_args(harness: str, env_files: Sequence[Path] = ()) -> list[str]:
    """Pass a long-lived `CLAUDE_CODE_OAUTH_TOKEN` through to the container when one is configured.

    This is the SUPPORTED way to authenticate a containerized Claude Code against a subscription
    (`claude setup-token`, ~1-year lifetime, precedence above the credentials file). Because it
    never expires mid-session, it needs no in-container refresh — which is what makes the
    credential-file copy (and its whole divergence problem) unnecessary. See
    _claude_creds_seed_mount for the legacy fallback.

    Two supply routes, in order:
      * a resolved `--env-file` (varlock/1Password or a project `.env`) — already handed to the
        container by the caller, so nothing extra is emitted here. This is the recommended route:
        the token is long-lived, so it belongs in a secret store, not a shell profile.
      * the host environment — forwarded as a bare `-e NAME` so podman reads the value from its
        own env instead of putting the secret on the command line (visible in `ps`).

    The env-file route WINS (bd harnessed-36l, extended to the container path). `podman run -e`
    beats `--env-file`, so forwarding the host value unconditionally made a shell export outrank
    every declared source — and a per-project token for a DIFFERENT account (a client's, resolved
    from 1Password into `<project>/.env.schema`) could then never take effect, silently
    authenticating that project as whoever the shell was exported for. Host mode already resolves
    this the other way at `_launch_host`: "letting a stale export in the invoking shell silently
    beat it is the failure mode that is hardest to see from inside a session." Skipping the `-e`
    here makes the two backends agree.
    """
    if harness not in ("claude", "omp"):
        return []
    # ANY explicit assignment in an env-file wins, empty included. A non-empty one supplies the
    # token, so the forward is redundant; an empty one is how a source turns the token OFF, and
    # since `-e` beats `--env-file` a forward there would override the very intent that declared it.
    if _env_files_value(_OAUTH_TOKEN_VAR, env_files) is not None:
        return []
    if os.environ.get(_OAUTH_TOKEN_VAR):
        return ["-e", _OAUTH_TOKEN_VAR]
    return []


def _env_files_value(var: str, env_files: Sequence[Path]) -> str | None:
    """The value `var` ends up with across resolved `--env-file`s, or None when none assigns it.

    LAST assignment wins, matching podman: `_resolve_launch_secrets` orders the files global →
    project precisely so the project overrides the global, and `--env-file` is last-wins. Returning
    on the first hit instead would let a global token mask a project-level `VAR=` written to
    disable it — the container would then receive the empty value while every caller believed a
    token was configured (bd harnessed-7bk; `_claude_oauth_token_configured` has the same shape for
    the same reason).

    An explicit empty string is a REAL answer, distinct from None: it means "declared, and turned
    off". Every path here is a generated temp written by `_resolve_launch_secrets` (clean
    `KEY=VALUE`, values literal to end-of-line), never the user's own file — but `_plain_env_values`
    is reused rather than a bare `split('=')` so the normalization stays in one place. Unreadable
    files are skipped: a launch must not hard-fail here.
    """
    value: str | None = None
    for f in env_files:
        try:
            values = _plain_env_values(f)
        except OSError:
            continue
        if var in values:
            value = values[var]
    return value


def _claude_oauth_token_configured(harness: str, project_path: Path | None = None) -> bool:
    """True when ``CLAUDE_CODE_OAUTH_TOKEN`` will reach the container at runtime.

    Checks, in order:
    1. ``os.environ`` — the token is already in the host process environment.
    2. Varlock resolution — structured check via ``_varlock_resolve``; asking
       ``resolved.get(KEY)`` is the authoritative answer and avoids a fragile
       text scan of a serialised env-file (the previous approach).
    3. Plain ``.env`` fallback — when no ``.env.schema`` / varlock is present,
       ``_plain_env_values`` parses the raw file directly.

    Drives ``_claude_creds_seed_mount``'s decision to skip or restore the legacy
    credential-file mount.

    Empty is NOT configured — ``export CLAUDE_CODE_OAUTH_TOKEN=`` is how a shell
    profile disables a token, and treating the bare name as "configured" would
    retire the credential file and silently log the user out with no recovery path
    (same semantics as ``_host_oauth_token_configured``).

    Dirs are resolved in full and the LAST answer wins, rather than returning on the
    first hit (bd harnessed-7bk).  Presence has to agree with the precedence the
    VALUES actually follow: ``_resolve_launch_secrets`` orders the env-files global →
    project and ``--env-file`` is last-wins, so a project-level ``VAR=`` written to
    disable a global token really does reach the container as empty.  Returning True
    on the global hit meant no credential file was mounted either — a container with
    no usable token AND no credentials, logged out with no recovery path from inside
    the pod.  Resolving every dir is cheap: ``_varlock_resolve`` memoises, and these
    same dirs were already resolved for the env-file list.

    Emits a warning when ``_varlock_resolve`` itself fails (returns ``None``): the
    token may be configured but is unreachable at launch time (e.g. via a runtime
    secrets agent that does not write env-files).  The warning distinguishes this
    "cannot determine" state from "genuinely no token", so the credential-file
    mount that follows is not a silent regression.
    """
    if harness not in ("claude", "omp"):
        return False

    # Route 1: already in the host process environment.
    if os.environ.get(_OAUTH_TOKEN_VAR):
        return True

    have_varlock = bool(shutil.which("varlock"))
    global_dir = Path.home() / ".config" / "harnessed"
    dirs: list[Path] = [global_dir]
    if project_path is not None:
        dirs.append(project_path)

    # Dirs where varlock ran and FAILED. Collected rather than warned about inline: a later dir can
    # still supply the token (global varlock down, project `.env` has it), in which case we return
    # True and mount nothing — so an inline warning would promise a credential-file fallback that
    # never happens. Deferring to the return-False path also means ONE warning per launch listing
    # every failed dir, instead of one per dir.
    unresolved: list[Path] = []
    # None until some dir declares the variable; then the LAST declaration, empty included.
    declared: str | None = None

    for d in dirs:
        schema = d / ".env.schema"
        if schema.is_file() and have_varlock:
            # Route 2: structured varlock query — no text-file scan.
            resolved = _varlock_resolve(d)
            if resolved is None:
                unresolved.append(d)
            elif _OAUTH_TOKEN_VAR in resolved:
                declared = resolved[_OAUTH_TOKEN_VAR]
        else:
            plain = d / ".env"
            if plain.is_file():
                # Route 3: plain .env — _plain_env_values strips export / surrounding quotes.
                values = _plain_env_values(plain)
                if _OAUTH_TOKEN_VAR in values:
                    declared = values[_OAUTH_TOKEN_VAR]

    if declared:  # empty string is NOT configured — the token was declared and turned off
        return True

    if declared is None and unresolved:
        # No source produced a token AND varlock failed somewhere, so we genuinely cannot tell
        # "no token" from "token we could not reach". Say so before the credential file is mounted.
        where = ", ".join(str(d) for d in unresolved)
        _err.print(
            f"[bold yellow]warning:[/bold yellow] could not resolve "
            f"{_OAUTH_TOKEN_VAR} via varlock in {where} — varlock failed, so "
            "the token may be present but is unreachable here.\n"
            "  Mounting a credential file as fallback.  If a runtime secrets "
            "agent supplies the token inside the container, this mount is "
            "unnecessary — configure the token explicitly to suppress it."
        )

    return False


def _claude_creds_seed_mount(harness: str, inst: str, token_configured: bool = False) -> list[str]:
    """LEGACY FALLBACK: seed a per-instance copy of ~/.claude/.credentials.json, mounted rw.

    Mounting host credential files into a container is an anti-pattern (Anthropic's own
    devcontainer guidance says to prefer short-lived/scoped tokens), and it cannot be made
    correct: host and container refresh their copies independently, and concurrent refresh-token
    rotation is undocumented. `CLAUDE_CODE_OAUTH_TOKEN` supersedes this entirely — when one is
    configured (`token_configured`) no credential file is mounted at all.

    This path remains only so hosts that have not yet run `claude setup-token` keep working.
    It seeds from the host's credentials, and — unlike the original — RE-SEEDS when the existing
    copy has expired. The old code seeded exactly once, so an instance whose copy aged out was
    permanently logged out: relaunching never refreshed it and the only cure was deleting the
    state dir by hand. Re-seeding is gated on expiry precisely so a token the container itself
    refreshed is never clobbered while it is still valid (the reason for the original guard).
    """
    if harness not in ("claude", "omp") or token_configured:
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    stub = state_dir / "credentials.json"

    if not stub.is_file() or _claude_creds_expired(stub):
        host_creds = Path.home() / ".claude" / ".credentials.json"
        if not host_creds.is_file():
            return []
        stub.write_bytes(host_creds.read_bytes())
        stub.chmod(0o600)

    _err.print(
        "[bold yellow]warning:[/bold yellow] mounting a copy of your Claude credentials into the "
        "container — it expires in hours and cannot refresh in step with the host.\n"
        f"  Fix once:  [cyan]claude setup-token[/cyan]  then store the token as [bold]{_OAUTH_TOKEN_VAR}[/bold] "
        "in 1Password/varlock or your project .env\n"
        "  That token lasts ~1 year, needs no refresh, and this mount disappears."
    )
    return ["-v", f"{stub}:{_CONTAINER_HOME_STR}/.claude/.credentials.json:rw"]


def _isolated_auth_store(inst: str) -> Path:
    """Host path of an isolated-auth stack's own credentials file (single source of truth)."""
    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_root / "harnessed" / inst / "isolated-auth" / "credentials.json"


def _claude_isolated_auth_mount(harness: str, inst: str) -> list[str]:
    """Give a stack its OWN Claude identity: a per-instance credentials file it logs into itself.

    For `isolated_auth: true` (Stack) — running a stack as a DIFFERENT account (a client's) while
    every other stack keeps using the host's. Nothing is seeded from the host and no host token is
    forwarded, so the agent comes up logged OUT and `/login` writes the client's credentials here.

    Contrast with the two shared-identity paths this REPLACES:
      * `_claude_creds_seed_mount` copies the host's credentials — wrong account, and a copy that
        rots on refresh;
      * `_claude_oauth_token_args` forwards the host's token — wrong account.
    Both are suppressed by the caller when this is active. Because nothing is copied, the SOP in
    ARCHITECTURE.md §Constraints is satisfied rather than bent: this file is the ONLY copy of the
    credential it holds, so there is no second copy to diverge from and no refresh race.

    WHY A HOST FILE AND NOT THE CONFIG VOLUME. `~/.claude` is the per-stack config volume, which
    `_ensure_config_volume` DESTROYS whenever the profile fingerprint changes (`fresh=not
    unchanged`) — its docstring's "safe to destroy: credentials are bind-mounted over it and live on
    the host" is exactly the invariant relied on here. A login stored in the volume would be wiped
    by the next recipe edit. The mount shape (single file, rw, over the volume) is the one
    `_claude_creds_seed_mount` already uses, so in-container refresh behaves the same way it does
    today; only the SOURCE policy differs.

    Seeded as `{}` when absent because podman bind-mounts a MISSING source as a new empty DIRECTORY,
    which Claude cannot read as a credentials file. `{}` parses as "no `claudeAiOauth`" — logged
    out — which is precisely the desired first-run state. Never re-seeded and never expiry-checked
    (unlike the legacy path): expiry here means "the client's own token should refresh in place",
    and rewriting the file would throw their login away. `--fresh` is the way back to logged-out.

    Empty for every harness without a `~/.claude/.credentials.json` surface — see the caller's
    warning, which tells the author the field did nothing rather than failing silently.
    """
    if harness != "claude":
        return []
    store = _isolated_auth_store(inst)
    store.parent.mkdir(parents=True, exist_ok=True)
    if not store.is_file():
        store.write_text("{}", encoding="utf-8")
        store.chmod(0o600)
    return ["-v", f"{store}:{_CONTAINER_HOME_STR}/.claude/.credentials.json:rw"]


def _isolated_auth_fresh_wipe(harness: str, inst: str) -> None:
    """`--fresh` drops an isolated-auth login so the next launch re-prompts (mirrors
    `_keyring_fresh_wipe`).

    The store deliberately SURVIVES an ordinary recreate — persisting the client's login across pod
    teardowns is the whole point — and neither `_persist_mounts` nor the per-instance state dir is
    wiped on `--fresh`. So "start clean" needs the removal spelled out here, exactly as antigravity's
    keyring does. No-op for every harness the mount does not apply to.
    """
    if harness != "claude":
        return
    shutil.rmtree(_isolated_auth_store(inst).parent, ignore_errors=True)


# The npm spec for the mcp-remote CLI, scoped (`@drmikecrowe/mcp-remote@0.1.38-test.3`) or bare.
# Charset-constrained deliberately: the matched token is the anchor for a version that would
# otherwise be free to carry a ':' into a podman `-v` spec, which is ':'-delimited.
_MCP_REMOTE_SPEC = re.compile(r"\A(?:@[^/@\s]+/)?mcp-remote@[A-Za-z0-9._+-]+\Z")


def _mcp_remote_invocations(servers: Sequence) -> list[list[str]]:
    """The argv of every stdio server that runs the mcp-remote CLI (usually zero or one).

    Both builders below key off the recipe's OWN args rather than a schema field, so the pin stays
    the single source of truth: bump it and the mount and the publish follow together. A network
    server (`url`) is proxied by hatago directly and never spawns this CLI.
    """
    return [
        list(s.args)
        for s in servers
        if s.is_stdio_child and any(_MCP_REMOTE_SPEC.match(a) for a in s.args)
    ]


def _mcp_remote_callback_port(argv: list[str]) -> int | None:
    """The callback port the recipe pinned, or None when it pinned none.

    mcp-remote's CLI is `mcp-remote <url> [callback-port]` and the port is `args[1]` — a raw INDEX,
    not "the second non-flag token" (chunk-NIAXKAUT.js L21091-21092). The one thing removed before
    that index is read is each `--header <value>` pair, spliced out of argv in the loop at
    L21077-21086; every other value-taking option (`--transport`, `--host`, `--resource`) is found
    later by `indexOf` and LEFT IN PLACE, so it cannot renumber anything.

    That asymmetry has to be mirrored exactly, in both directions:
      * miss the splice and a recipe sending an auth header publishes nothing while mcp-remote
        listens — the silent timeout this whole change exists to remove;
      * filter flags generally and a non-`--header` option before the URL looks like a valid pin
        here while upstream reads that option as `serverUrl` and never listens at all.
    Absent a pin the tool selects its own port (L21233), which harnessed cannot know; inventing one
    forwards a port nothing answers, which looks wired and is not.
    """
    idx = next((n for n, a in enumerate(argv) if _MCP_REMOTE_SPEC.match(a)), None)
    if idx is None:
        return None
    rest = argv[idx + 1:]
    positional: list[str] = []
    n = 0
    while n < len(rest):
        # Upstream guards the splice with `i < args.length - 1`, so a DANGLING `--header` survives
        # in its argv while it is dropped from this list. That difference is not observable: the
        # only way it could move the port is by sitting at index 1, and there the kept token is
        # `--header` itself — rejected by the decimal check below exactly as the short list is
        # rejected for being too short. Both roads return None, so the branch is omitted rather
        # than carried as a line no test can ever distinguish.
        if rest[n] == "--header":
            n += 2
            continue
        positional.append(rest[n])
        n += 1
    # `isascii() and isdecimal()`, NOT `isdigit()`. `str.isdigit()` is True for characters `int()`
    # refuses — superscripts like '²' are digits but not decimals — so an `isdigit()` guard in front
    # of `int()` reads as validation while leaving an uncaught ValueError that would take down
    # `pod create` instead of skipping the publish. `isdecimal()` closes that, and `isascii()` also
    # rejects the other-script decimals ('٠١٢') that `int()` accepts but no port is ever written in.
    if len(positional) < 2 or not (positional[1].isascii() and positional[1].isdecimal()):
        return None
    port = int(positional[1])
    # Floor is 1024, not 1: harnessed runs the pod ROOTLESS, and a rootless publish of a privileged
    # port fails at `pod create` on a default `net.ipv4.ip_unprivileged_port_start=1024`. Skipping a
    # port that cannot be published is the same policy as skipping one already taken — a launch that
    # dies because a recipe pinned port 80 would be a worse failure than an unpublished callback.
    # mcp-remote's own default is 3335 + hash%45816, so this never binds on real pins.
    return port if 1024 <= port <= 65535 else None


def _port_free(port: int) -> bool:
    """True when 127.0.0.1:<port> can be bound right now. Best-effort and racy by nature — the
    caller uses it to DROP a publish, never to promise one, so losing the race costs a skipped
    publish rather than a failed launch."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _mcp_remote_callback_publish_args(
    servers: Sequence, port_free: "Callable[[int], bool] | None" = None
) -> list[str]:
    """Publish mcp-remote's OAuth callback port into the pod, so the redirect can land.

    THE DEFECT THIS FIXES. mcp-remote authenticates by opening a browser and listening for the
    redirect on 127.0.0.1:<port>. Inside a pod that publishes nothing, those are two different
    loopbacks: the browser opens in the container where nobody can see it, and the URL pasted into
    the HOST's browser redirects to the HOST's 127.0.0.1 — a different netns from the listener. The
    flow can never complete, and hatago reports three `Request timed out` retries with no hint as to
    why. Publishing the port joins the two halves; the user pastes the authorize URL, consents, and
    the redirect reaches the process that is waiting for it.

    LOOPBACK-BOUND, never `0.0.0.0`. An unqualified `-p` publishes on every interface (see the
    service publish and its comment), and an OAuth callback listener has no business on the LAN.

    A TAKEN PORT IS SKIPPED, NOT FATAL. Two concurrent instances of the same stack would otherwise
    collide at `pod create` ("port already in use") before either could authenticate. The second one
    does not need it: either the first is mid-consent and will write tokens into the shared store, or
    valid tokens already exist — and an instance holding valid tokens reaches neither the callback
    server nor the lockfile, since both hang off the `UnauthorizedError` branch (L20896-20904).
    (Only the HOST-side publish can collide. The in-pod bind cannot: each pod has its own netns, so
    two instances both listening on 32081 inside their own pods never see each other.)

    THE PUBLISH ALONE IS INERT — see `_mcp_remote_pasta_net_args`. mcp-remote's callback server is
    `app.listen(port, "127.0.0.1")` with no way to change the bind address (L21016; `--host` only
    rewrites the ADVERTISED redirect URI and the tool warns as much, L21130), and rootless pasta
    forwards a published port to the namespace's PUBLIC address by default. Verified on real podman:
    a loopback-bound listener in a pod published with `-p` is unreachable from the host, while the
    same pod with the pasta option below answers. Both args must be emitted together.
    """
    is_free = port_free or _port_free
    args: list[str] = []
    seen: set[int] = set()
    for argv in _mcp_remote_invocations(servers):
        port = _mcp_remote_callback_port(argv)
        if port is None or port in seen:
            continue
        seen.add(port)
        if not is_free(port):
            _err.print(
                f"[yellow]note:[/yellow] host port {port} is in use, so this instance publishes no "
                "mcp-remote OAuth callback. It will use the tokens already in the shared store; "
                "only a first-time consent needs the port."
            )
            continue
        args += ["-p", f"127.0.0.1:{port}:{port}"]
    return args


def _mcp_remote_pasta_net_args(publish_args: list[str], net: str) -> list[str]:
    """The pasta option WITHOUT WHICH the callback publish does nothing at all.

    mcp-remote's callback server binds `127.0.0.1` unconditionally
    (`app.listen(options.port, "127.0.0.1")`, L21016). `--host` does NOT move it — it only rewrites
    the redirect URI that gets advertised, and the tool prints a warning saying the code "will not
    reach this process" as a result (L21130). So the listener is loopback-only inside the pod netns,
    and there is no upstream flag to change that.

    Rootless podman uses pasta, which by default delivers a forwarded port to the namespace's PUBLIC
    address — not its loopback — so a `-p` publish sails past a loopback-only listener.
    `--host-lo-to-ns-lo` is the documented pasta option that "connections to a host loopback address
    forwarded with -t or -u will be delivered to the same loopback address in the namespace".

    Measured on real podman (rootless, netavark, pasta), same pod and same `-p` both times:

        listener bound 127.0.0.1, no pasta option   -> curl exit 56, unreachable
        listener bound 0.0.0.0,   no pasta option   -> HTTP 200
        listener bound 127.0.0.1, --host-lo-to-ns-lo -> HTTP 200

    An explicit HARNESSED_NET wins: the operator asked for a specific network and silently rewriting
    it would be worse than a callback that needs one manual step. Say so rather than fight them.
    """
    if not publish_args:
        return []
    if net:
        _err.print(
            f"[yellow]note:[/yellow] HARNESSED_NET={net} is set, so the mcp-remote OAuth callback "
            "port is published without pasta's [bold]--host-lo-to-ns-lo[/bold]. The callback server "
            "listens on the pod's 127.0.0.1, which that network may not deliver to — if the browser "
            "redirect hangs, authorize once on the host instead."
        )
        return ["--network", net]
    return ["--network", "pasta:--host-lo-to-ns-lo"]


def _mcp_remote_pod_args(
    servers: Sequence, net: str, port_free: "Callable[[int], bool] | None" = None
) -> list[str]:
    """Everything `pod create` needs for mcp-remote's OAuth callback, as ONE list.

    The publish and the pasta option are emitted together because separately they are a trap: a
    publish without `--host-lo-to-ns-lo` forwards straight past mcp-remote's loopback-bound listener
    and changes nothing, while looking in `podman pod inspect` exactly like a working one. Composing
    them here means the launcher cannot wire one and forget the other, and means the coupling is
    assertable without driving a real `pod create`.

    Also owns the plain `--network` passthrough, since `--network` cannot be passed twice.
    """
    publish = _mcp_remote_callback_publish_args(servers, port_free=port_free)
    if not publish:
        return ["--network", net] if net else []
    return publish + _mcp_remote_pasta_net_args(publish, net)


def _mcp_auth_store_dir(inst: str, isolated_auth: bool, home: Path | None = None) -> Path:
    """The HOST directory bind-mounted at the container's `~/.mcp-auth`.

    Extracted so the mount and the "is this server authorized yet?" check below cannot disagree
    about where the tokens live — a launch that mounts one directory and inspects another would
    re-prompt forever while a perfectly good token sat next door.
    """
    home = home or Path.home()
    return _isolated_auth_store(inst).parent / ".mcp-auth" if isolated_auth else home / ".mcp-auth"


def _mcp_remote_spec_version(argv: Sequence[str]) -> str | None:
    """The pinned version out of the `[@scope/]mcp-remote@VERSION` argument.

    The store is version-namespaced — `getConfigDir` appends `mcp-remote-<version>` unconditionally
    (chunk-NIAXKAUT.js L20290) — so the version is part of the token path, and reading it back out
    of the recipe's own args keeps the pin the single source of truth. Bump the pin and this follows;
    there is no second copy to forget.
    """
    spec = next((a for a in argv if _MCP_REMOTE_SPEC.match(a)), None)
    return spec.rsplit("@", 1)[1] if spec else None


def _mcp_remote_server_url(argv: Sequence[str]) -> str | None:
    """The remote server URL — mcp-remote's positional arg 0, read exactly as upstream reads it.

    Same `--header <value>` splice as `_mcp_remote_callback_port`, for the same reason: upstream
    removes those pairs before indexing (L21077-21092), so a recipe passing an auth header would
    otherwise have its URL misread as the header's value.
    """
    idx = next((n for n, a in enumerate(argv) if _MCP_REMOTE_SPEC.match(a)), None)
    if idx is None:
        return None
    rest = list(argv[idx + 1:])
    positional: list[str] = []
    n = 0
    while n < len(rest):
        if rest[n] == "--header":
            n += 2
            continue
        positional.append(rest[n])
        n += 1
    return positional[0] if positional else None


def _mcp_remote_token_file(store: Path, argv: Sequence[str]) -> Path | None:
    """Where mcp-remote writes THIS server's tokens, or None when argv does not name one.

    `<store>/mcp-remote-<version>/<sha256(server_url)>_tokens.json`. The basename is a plain
    SHA-256 of the server URL — verified against a real store, not inferred: the file
    `704a0484…fab3_lock.json` sitting beside the Atlassian consent is exactly
    `sha256("https://mcp.atlassian.com/v1/mcp/authv2")`.

    Computing it means the "needs authorization" test is EXACT rather than a guess at directory
    contents. A stack with two OAuth servers gets two independent answers, and a half-finished
    consent (client_info and code_verifier present, tokens absent — the real state observed
    mid-flow) reads as unauthorized, which is what it is.
    """
    version = _mcp_remote_spec_version(argv)
    url = _mcp_remote_server_url(argv)
    if not version or not url:
        return None
    digest = hashlib.sha256(url.encode()).hexdigest()
    return store / f"mcp-remote-{version}" / f"{digest}_tokens.json"


def _mcp_remote_pending_auth(
    servers: Sequence, inst: str, isolated_auth: bool, home: Path | None = None
) -> list[tuple[str, list[str]]]:
    """Every mcp-remote server with no token yet — `(server name, argv)`, in declaration order.

    This is the whole detection behind the launch-time prompt. It answers a question nothing else
    can answer from outside the container: mcp-remote only reveals that it needs a browser AFTER
    hatago has spawned it, on a grandchild's stderr that the harness discards, by which point the
    only visible symptom is `MCP error -32001: Request timed out`.

    An EXPIRED token is deliberately not "pending". Refresh is a token-endpoint POST with no browser
    and no callback (`refreshAuthorization`), so prompting for one would interrupt a launch that was
    about to succeed on its own. Only absent — never authorized, or revoked — asks for a human.
    """
    store = _mcp_auth_store_dir(inst, isolated_auth, home)
    pending: list[tuple[str, list[str]]] = []
    for server in servers:
        if not getattr(server, "is_stdio_child", False):
            continue
        argv = list(server.args)
        if not any(_MCP_REMOTE_SPEC.match(a) for a in argv):
            continue
        token = _mcp_remote_token_file(store, argv)
        if token is None or token.is_file():
            continue
        pending.append((server.name, argv))
    return pending


def _mcp_auth_store_mount(
    servers: Sequence, inst: str, isolated_auth: bool, home: Path | None = None
) -> list[str]:
    """Bind-mount `~/.mcp-auth` rw so an OAuth consent outlives the pod it happened in.

    Without this the tokens are written into the container's own home and die with the instance, so
    every launch walks the whole browser flow again. `saveTokens` rewrites the token in place on
    refresh (L21511), which is why this is `rw` and why it satisfies ARCHITECTURE.md §Constraints:
    the live store is REFERENCED, and nothing is copied, seeded, or snapshotted into a per-stack home.

    THE SOURCE DEPENDS ON WHOSE IDENTITY THE STACK RUNS AS, mirroring the split that
    `_claude_isolated_auth_mount` and `_claude_creds_seed_mount` already make:

      * `isolated_auth` — a per-instance dir beside that stack's own Claude credentials. The flag
        exists so a stack runs as a DIFFERENT account (a client's); handing it the host's ~/.mcp-auth
        would give it the HOST's Atlassian identity, which is the exact wrong-account failure the
        flag prevents. `instance_name` is deterministic, so the dir is the same one every launch,
        survives an ordinary recreate, and is reset by `--fresh` (`_isolated_auth_fresh_wipe`).
      * otherwise — the host's own `~/.mcp-auth`. These stacks already run on the host's Claude
        identity, so sharing its Atlassian consent is consistent, and one host-side authorization
        then covers the host and every container together.

    THE WHOLE DIRECTORY, NOT `mcp-remote-<version>/`. The store is version-namespaced
    (`getConfigDir`, L20290), and mounting one version's subdir would mean deriving the version here
    and leaving a stale mount pointing at a directory nothing reads the moment the pin moved.
    `ensureConfigDir` creates whatever subdir it needs INSIDE the mount (L20294), so mounting the
    parent removes the trap entirely: a bump costs one re-consent, never a silent logout.

    The source is CREATED when absent rather than demanded — the store is an output of the auth
    flow, not a precondition to police. harnessed creates it (0o700, matching `ensureConfigDir`'s own
    mode) instead of letting podman auto-create the missing source, so it is owned by the right uid
    under `paths.USERNS_ARG` rather than by whoever podman decides.
    """
    if not _mcp_remote_invocations(servers):
        return []
    source = _mcp_auth_store_dir(inst, isolated_auth, home)
    # ':' is the `-v src:dst:opts` separator, so a source containing one reparses the spec into a
    # mount of somewhere else entirely — the same defensive skip `_ssh_dir_mounts` applies.
    if ":" in str(source):
        _err.print(
            f"[yellow]note:[/yellow] skipping the mcp-remote token store mount — {source} "
            "contains ':'."
        )
        return []
    # AFTER the mkdir, deliberately, and this ordering is the whole guarantee. Checking first leaves
    # the absent-directory case unguarded twice over: `guard_ownership` on a path that does not exist
    # yet passes trivially, and the two statements are a TOCTOU window in which anything that
    # appears at `source` is then adopted by `exist_ok=True` and mounted rw. Checking after covers
    # both orders — a pre-existing foreign dir survives an `exist_ok` mkdir unchanged and is caught
    # here, and so is one that raced in. A foreign-owned dir maps to an unrelated subuid inside the
    # pod, so the refresh write fails with EACCES and nothing on the host says why.
    source.mkdir(parents=True, exist_ok=True)
    persist.guard_ownership(source)
    # Tightened whether harnessed created it or inherited it. Only chmod'ing our own fresh dir left
    # the claim "0o700" true on one branch and false on the other — and the inherited branch is the
    # LIKELY one, since mcp-remote's `ensureConfigDir` makes the version subdir 0o700 while the
    # parent it creates alongside lands at the caller's umask (commonly 0o755). The tokens sit one
    # level down, but a listable parent still discloses which servers have been authorized and when.
    # Narrowing only: never widens a directory the user deliberately locked down harder.
    if source.stat().st_mode & 0o077:
        source.chmod(0o700)
    return ["-v", f"{source}:{_CONTAINER_HOME_STR}/.mcp-auth:rw"]


def _claude_creds_expired(creds: Path) -> bool:
    """True when a seeded credential copy's OAuth access token has passed its `expiresAt`.

    Unparseable/absent expiry counts as expired: a copy we cannot vouch for is worth replacing
    with the host's current one. Reads only the expiry timestamp — never the token itself.
    """
    try:
        data = json.loads(creds.read_text(encoding="utf-8"))
        expires_at = data.get("claudeAiOauth", {}).get("expiresAt")
    except (ValueError, OSError):
        return True
    if not isinstance(expires_at, (int, float)):
        return True
    return (expires_at / 1000) <= datetime.now(timezone.utc).timestamp()


def _keyring_state_mount(harness: str, inst: str) -> list[str]:
    """Persist agy's Secret Service keyring store across recreates (bd main-ec5, antigravity only).

    Mirrors _claude_config_seed_mount's per-instance state-dir pattern: a host dir under
    XDG_STATE_HOME/harnessed/<inst>/keyrings is bind-mounted rw at the container's
    ~/.local/share/keyrings (agy's keyring store). `inst` is deterministic (stack + project), and a
    recreate only tears down the pod — host state dirs are never touched — so the same dir re-mounts
    and the in-pod OAuth token persists automatically. Unlike the claude.json stub, the token is
    generated in-pod and is NOT re-derivable from the host, so nothing is seeded; the dir is simply
    preserved as-is. Empty for every non-antigravity harness (they are unaffected).
    """
    if harness != "antigravity":
        return []
    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    keyring_dir = state_root / "harnessed" / inst / "keyrings"
    keyring_dir.mkdir(parents=True, exist_ok=True)
    return ["-v", f"{keyring_dir}:{_CONTAINER_HOME_STR}/.local/share/keyrings:rw"]


def _keyring_fresh_wipe(harness: str, inst: str) -> None:
    """--fresh wipes the persisted agy keyring so the next launch re-prompts OAuth (bd main-ec5).

    _keyring_state_mount's dir deliberately SURVIVES a normal recreate — that is the whole point of
    persisting the token — and neither _persist_mounts nor the per-instance state dir is wiped on
    --fresh (both are designed to survive it). So --fresh's "start clean" contract needs an explicit
    removal here; routing this through _persist_mounts would carry the wrong (survives-fresh)
    semantics. No-op for every non-antigravity harness.
    """
    if harness != "antigravity":
        return
    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    shutil.rmtree(state_root / "harnessed" / inst / "keyrings", ignore_errors=True)


def _keyring_init(harness: str) -> str:
    """Keyring-daemon init prefix for the antigravity attach shell (bd main-ec5).

    agy persists its Google-OAuth token to the Secret Service keyring, but the isolated container has
    no keyring daemon. Start a session D-Bus + gnome-keyring-daemon HERE — in the same shell that
    execs agy — so agy inherits DBUS_SESSION_BUS_ADDRESS / GNOME_KEYRING_CONTROL / SSH_AUTH_SOCK. A
    detached daemon (exec -d) would not export its env into this attach shell, so it MUST run inline.
    The keyring is unlocked with an empty password (printf ''), auto-creating the login keyring empty
    on first run; its store is a persistent host mount (_keyring_state_mount), so the token survives
    recreates. Returns "" for every non-antigravity harness (their attach shell is unchanged).
    """
    if harness != "antigravity":
        return ""
    return (
        "export $(dbus-launch) "
        "&& printf '' | gnome-keyring-daemon --unlock --components=secrets "
        '&& eval "$(printf \'\' | gnome-keyring-daemon --start --components=secrets)"'
    )


def _omp_agent_mount(harness: str) -> list[str]:
    """Bind-mount the host's omp agent dir so the pod shares one omp state with the host.

    omp (Oh My Pi) keeps everything under ~/.omp/agent — credentials (agent.db `auth_credentials`,
    plaintext JSON), setup/provider config (config.yml), usage tracking, and sessions. Rather than
    copy a per-instance snapshot, we bind-mount the host dir rw: auth is always current, usage is
    written back to the single host ledger, and sessions are shared across the host and every
    container (the user runs these containers as their primary omp — the host is not a separate
    source of truth). The omp image bakes ~/.omp/{plugins,natives}, NOT agent/, so this shadows
    nothing. Trade-off: full host-state sharing (not isolated); SQLite/WAL coordinates concurrent
    host+container access on the same kernel, but avoid heavy simultaneous writes from both.
    """
    if harness != "omp":
        return []
    host_agent = Path.home() / ".omp" / "agent"
    if not host_agent.is_dir():
        _err.print(
            "[yellow]note:[/yellow] no ~/.omp/agent on the host — omp will prompt to log in "
            "(run `omp` on the host first)."
        )
        return []
    return ["-v", f"{host_agent}:{_CONTAINER_HOME_STR}/.omp/agent:rw"]


def _omp_mcp_seed_mount(harness: str, inst: str) -> list[str]:
    """Point omp at the in-container hatago hub by seeding a per-instance ~/.omp/agent/mcp.json.

    harnessed wires the MCP layer for claude via `claude --mcp-config <profile .mcp.json>` — the
    single hatago endpoint that fronts every assembled server (stdio children hatago spawns, http
    servers it proxies). omp has no such flag: it reads MCP servers only from ~/.omp/agent/mcp.json,
    which `_omp_agent_mount` bind-mounts rw from the host (shared state). So a stack's MCP servers,
    which live behind hatago, are invisible to omp — the exact gap behind "repowise didn't install".

    Fix: generate a per-instance mcp.json = the host file's contents (preserving whatever the user
    manages there) plus a `hatago` HTTP entry, and bind-mount it ro OVER ~/.omp/agent/mcp.json. This
    nested file mount shadows the dir mount's own mcp.json (podman applies the more-specific
    destination), so omp connects to hatago — WITHOUT mutating the shared host file. Regenerated
    every launch (a pure function of the host file + the hatago endpoint), so host edits propagate on
    the next launch and nothing in-container writes back (ro)."""
    if harness != "omp":
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    seed = state_dir / "omp-mcp.json"

    cfg: dict = {}
    host_mcp = Path.home() / ".omp" / "agent" / "mcp.json"
    if host_mcp.is_file():
        try:
            cfg = json.loads(host_mcp.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.setdefault("mcpServers", {})["hatago"] = {"type": "http", "url": paths.hatago_endpoint()}
    seed.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    return ["-v", f"{seed}:{_CONTAINER_HOME_STR}/.omp/agent/mcp.json:ro"]


def _ccstatusline_settings_mount(home: Path | None = None) -> list[str]:
    """Forward the host's ccstatusline config read-only, if present.

    The `ccstatusline` recipe bakes a Claude `statusLine` that runs the `ccstatusline` renderer;
    that renderer reads ~/.config/ccstatusline/settings.json. Bind-mounting the host's file :ro
    (same file-by-file, is_file()-guarded, read-only pattern as the gh-hosts credential forward)
    lets the container's status line match the host's layout/segments. This is personalization, not
    a credential, so it is NOT gated on `forward_git_credentials` — and it is guarded on host-file
    existence, so a host with no ccstatusline config is a clean no-op (ccstatusline falls back to
    its built-in defaults). Harness-agnostic: for a non-claude harness (no baked statusLine) the
    mounted file simply goes unread.
    """
    home = home or Path.home()
    cfg = home / ".config" / "ccstatusline" / "settings.json"
    if not cfg.is_file():
        return []
    return ["-v", f"{cfg}:{_CONTAINER_HOME_STR}/.config/ccstatusline/settings.json:ro"]


# Default port the aws-sso ECS server listens on (aws-sso-cli default). Kept in sync with the
# `--port` default of `harnessed aws-sso serve`.
AWS_SSO_ECS_PORT = 4144


def _aws_sso_ecs_forward_args(port: int = AWS_SSO_ECS_PORT, token_file: Path | None = None) -> list[str]:
    """Wire the container to the host's aws-sso ECS server (default slot) for stacks that opt in with
    `forward_aws_sso: true`.

    Emits AWS_CONTAINER_CREDENTIALS_FULL_URI (the AWS SDK's ECS-task-role endpoint, pointed at the
    host's `aws-sso ecs server` via host.containers.internal) + AWS_CONTAINER_AUTHORIZATION_TOKEN
    (the bearer token gating that server). The in-container AWS SDK then pulls short-lived STS creds
    over HTTP — no aws-sso binary, ~/.aws-sso store, or SSO token ever enters the container.

    The bearer token is read from the user-owned token file that `harnessed aws-sso serve` writes
    (single source of truth). No-op when that file is absent/empty — so a `forward_aws_sso` stack
    launches fine on a host that hasn't set up the server (the SDK just finds no AWS creds), and the
    token never lands in an image layer (it arrives as a per-launch `-e`).
    """
    tf = token_file or paths.aws_sso_ecs_token_file()
    try:
        token = tf.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not token:
        return []
    uri = f"http://host.containers.internal:{port}/"
    return [
        "-e", f"AWS_CONTAINER_CREDENTIALS_FULL_URI={uri}",
        "-e", f"AWS_CONTAINER_AUTHORIZATION_TOKEN=Bearer {token}",
    ]


def _aws_sso_server_reachable(port: int = AWS_SSO_ECS_PORT, timeout: float = 1.5) -> bool:
    """True iff the host aws-sso ECS server is up AND has a role loaded.

    Probes the server's unauthenticated `GET /healthcheck`, which returns 200 only when the default
    slot holds valid credentials — so a single check covers both "server not running" and "no role
    loaded". Any failure (connection refused, timeout, non-200) is treated as unreachable. The probe
    hits 127.0.0.1 (host loopback), not host.containers.internal — this runs on the host, at launch.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(  # fixed host-local http URL
            f"http://127.0.0.1:{port}/healthcheck", timeout=timeout
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _credential_forward_args(
    home: Path | None = None, ssh_keys: list[str] | None = None, rt: str = "podman"
) -> list[str]:
    """Forward the host's git signing + push credential surface into the harness container.

    Restores what the bash launcher (container.sh) forwarded — so the agent can `git push` and sign
    commits inside the container WITHOUT baking any secret into an image — but OS-aware and with the
    blunt whole-`~/.ssh` mount narrowed to the non-secret surface plus opt-in private keys. Every
    piece is conditioned on host-side existence, so it's a clean no-op when nothing is configured.

    - SSH signing/auth agent (1Password primary, gpg-agent/YubiKey fallback) — see `_ssh_agent_args`.
    - NON-SECRET GPG files only (pubring/trustdb/config, NEVER the private keyring) — `_gnupg_mounts`.
    - YubiKey USB device passthrough (`--device`, Linux only) — see `_yubikey_device_args`.
    - git config (`~/.config/git` dir, else legacy `~/.gitconfig`, ro): carries user.signingkey,
      gpg.format=ssh, gpg.ssh.program=op-ssh-sign, commit.gpgsign so commits actually sign.
    - gh auth (`~/.config/gh/hosts.yml`, ro): the file that carries gh's oauth_token, so `gh pr
      create` etc. authenticate as the host user — just the hosts file, no wider gh config, no token
      baked into env or image.
    - ssh config + known_hosts + public keys (ro), plus stack `ssh_keys` opt-in privates — see
      `_ssh_dir_mounts`.

    NOTE: the dropped "transparent mode" (rw `~/.claude`) is intentionally NOT restored.
    """
    home = home or Path.home()
    ssh_keys = ssh_keys or []
    ctr = _CONTAINER_HOME_STR
    args = _ssh_agent_args(home, _gpg_ssh_socket(), rt=rt)

    args += _gnupg_mounts(home)

    args += _yubikey_device_args()

    args += _git_identity_config_mount(home)

    gh_hosts = home / ".config" / "gh" / "hosts.yml"
    if gh_hosts.is_file():
        args += ["-v", f"{gh_hosts}:{ctr}/.config/gh/hosts.yml:ro"]
        if _gh_hosts_missing_plaintext_token(gh_hosts):
            _err.print(
                "[yellow]note:[/yellow] gh config found, but no plaintext token — it's likely "
                "stored in the host's system credential store (e.g. macOS Keychain), which this "
                "container cannot reach. `gh` will not authenticate inside the container. Run "
                "[bold]gh auth login --insecure-storage[/bold] (or `gh auth refresh "
                "--insecure-storage` if already logged in) on the host to store a plaintext token."
            )

    gh_config = home / ".config" / "gh" / "config.yml"
    if gh_config.is_file():
        args += ["-v", f"{gh_config}:{ctr}/.config/gh/config.yml:ro"]

    args += _ssh_dir_mounts(home, ssh_keys)

    return args


def _persist_mounts(stack: str, project_path: Path) -> list[str]:
    """Bind-mount each recipe's declared persist entries (rw) so their state survives `--fresh`.

    scope: workspace, location: host (T4a):
        harnessed owns a dir at persist/<recipe>/<workspace_hash>/<name>/ and mounts it rw at
        $HOME/<name> inside the pod. Keyed by the resolved launch path (per-worktree).

    scope: project, location: host:
        Same as workspace but keyed by git-common-dir, so every worktree of the same checkout
        shares one dir. Falls back to workspace scope (with a warning) for non-git projects.

    scope: global, location: (none) (T4b):
        Mounts a REAL host dir PATH-PRESERVING (host path == container path) so the tool finds
        its data where it expects — but ONLY after the hard-deny + allowlist gate clears it.

    scope: workspace|project, location: in_repo:
        No extra mount — the workspace is already mounted rw. For vcs: ignored, harnessed
        ensures the project .gitignore contains the entry name (idempotent).

    Ownership (T5): every host-side target dir is ownership-guarded — a pre-existing dir owned
    by another uid would silently EACCES under `paths.USERNS_ARG`, rejected with a remediation.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    args: list[str] = []
    for recipe in recipes:
        for entry in recipe.persist.entries:
            if entry.scope == "global":
                assert entry.path is not None, "global persist entry must have path"  # noqa: S101 — schema-enforced invariant, narrowed here for the checker
                host_dir = persist.resolve_global_persist(entry.path)
                persist.guard_ownership(host_dir)
                args += ["-v", f"{host_dir}:{host_dir}:rw"]

            elif entry.location == "host":
                assert entry.name is not None, "non-global persist entry must have name"  # noqa: S101 — schema-enforced invariant, narrowed here for the checker
                if entry.scope == "workspace":
                    host_dir = paths.persist_workspace_dir(recipe.name, project_path, entry.name)
                else:  # project
                    if paths.git_common_dir(project_path) is None:
                        _err.print(
                            f"[yellow]warning:[/yellow] recipe '{recipe.name}' persist entry "
                            f"'{entry.name}' uses scope: project, but {project_path} is not "
                            "inside a git repository — falling back to workspace scope "
                            "(keyed by the current path, not git-common-dir)."
                        )
                    host_dir = paths.persist_project_dir(recipe.name, project_path, entry.name)
                persist.guard_ownership(host_dir)
                host_dir.mkdir(parents=True, exist_ok=True)
                ctr_dir = f"{_CONTAINER_HOME_STR}/{entry.name}"
                args += ["-v", f"{host_dir}:{ctr_dir}:rw"]

            else:  # location: in_repo
                assert entry.name is not None, "non-global persist entry must have name"  # noqa: S101 — schema-enforced invariant, narrowed here for the checker
                if entry.vcs == "ignored":
                    _ensure_gitignore_entry(project_path, entry.name)
                # No mount — the workspace is already mounted read-write.

    return args
