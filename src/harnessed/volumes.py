"""The podman volumes a stack owns, and what gets installed into them.

A stack keeps its agent config and its tool tree in named volumes rather than in the image, so a
rebuild does not discard installed state and two projects sharing a stack share one copy. These
create the volumes, label them for the garbage collectors, fingerprint their contents, and run a
recipe`s `tools:`/`install:` into them.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess

from pathlib import Path

from . import emit
from . import paths
from .console import _err, _out
from .hosthome import _HOST_STACK_FINGERPRINT, _host_stack_fingerprint
from .schema import resolve_recipe_env
from .layout import _agent_image
from .paths import CONTAINER_HOME
from .proc import _run, _say

_CONTAINER_HOME_STR = str(CONTAINER_HOME)

# Where the emitted profile is mounted `:ro` while composing the agent-config volume
# (`_ensure_config_volume`). Scratch for that one throwaway container; never seen by the agent.
_CTR_PROFILE_DIR = "/tmp/harnessed-profile"


def _stack_config_volume(stack: str, harness: str) -> str:
    """Name of the per-stack agent-config volume (bd harnessed-8px.21.2).

    Per (stack, harness) because the composed content differs on both axes: the recipe closure
    picks the content, and the harness picks which profile tree is fanned into it. Two stacks
    sharing a volume would compose each other's skills.
    """
    return f"harnessed-cfg-{harness}-{stack}"


def _ensure_config_volume(
    rt: str, stack: str, harness: str, prof: Path, image: str, *, fresh: bool = False,
) -> str:
    """Create and compose the per-stack agent-config volume, returning its name.

    Replaces the per-subdir `:ro` bind-mounts that caused bd harnessed-8px.22, where a profile
    dir mounted over `~/.claude/skills` hid everything an `install.script` had delivered there —
    measured at 70 of 75 skills invisible, including all 34 `gsd-*`. Nothing is layered over
    anything now: ONE tree, composed in order.

    Two podman behaviours make this work, both verified against 6.0.1 in the bd harnessed-8px.21.1
    spike, and both easy to get wrong:

    1. COPY-UP. Mounting an EMPTY named volume over a path the image populated copies the image's
       content into the volume. That is what delivers the install-written `~/.claude` (and, for
       the `~/.local` volume this bead's sibling adds, the base image's own mise/snyk). It happens
       exactly ONCE — thereafter volume content wins and image updates are invisible, which is why
       the gate in harnessed-8px.21.3 must key on image identity and not only the recipe hash.

    2. USERNS. The pod is created with `paths.USERNS_ARG` and the agent inherits it as a pod member,
       so this populate step MUST use the SAME mapping. A volume first populated under the DEFAULT
       userns is unusable by the agent: uid 1000 inside reads the files as owner 999 and every write
       EACCESes. Verified in both directions. The mapping is pinned to the image uid rather than left
       as bare `keep-id` — see paths.USERNS_ARG and bd harnessed-rv2.1.

    The profile is copied in on every launch, deliberately: that preserves today's semantics where
    the profile always wins over baked content. It is a local copy of small trees, not the
    expensive part — installs are what harnessed-8px.21.3 gates.
    """
    vol = _stack_config_volume(stack, harness)
    if fresh:
        # Composition is purely ADDITIVE — copy-up, then `cp -a` of the profile, then installs.
        # Nothing here removes, so without this a recipe dropped from the stack would leave its
        # skills and commands in the volume forever. `_materialize_host_home` rmtree's the host home
        # on every launch for exactly this reason ("so a removed recipe's files never linger"); the
        # container side has to do the same thing, just gated on the fingerprint instead of
        # unconditionally, because here the content is expensive to rebuild.
        #
        # Safe to destroy: the volume holds COMPOSED content only. Credentials and the rw history
        # dirs are bind-mounted over it at launch and live on the host, so they are not in here.
        _run([rt, "volume", "rm", "-f", vol], check=False, capture_output=True)
    _run([rt, "volume", "create", *_volume_labels(stack, harness, "config"), vol],
         check=False, capture_output=True)
    # `cp -a src/. dst/` MERGES into the copy-up'd tree rather than replacing it — the whole point.
    compose = (
        "set -e; "
        f"if [ -d {_CTR_PROFILE_DIR}/.claude ]; then "
        f"  cp -a {_CTR_PROFILE_DIR}/.claude/. {_CONTAINER_HOME_STR}/.claude/; "
        "fi; "
        f"if [ -f {_CTR_PROFILE_DIR}/settings.json ]; then "
        f"  cp -a {_CTR_PROFILE_DIR}/settings.json {_CONTAINER_HOME_STR}/.claude/settings.json; "
        "fi"
    )
    _run([
        rt, "run", "--rm", paths.USERNS_ARG,
        "-v", f"{vol}:{_CONTAINER_HOME_STR}/.claude",
        "-v", f"{prof}:{_CTR_PROFILE_DIR}:ro",
        "--entrypoint", "sh", image, "-c", compose,
    ], capture_output=True)
    return vol


# Shared by every stack, on purpose — see _run_container_installs.
_SHARED_DL_CACHE_VOLUME = "harnessed-dl-cache"


# Volumes are identified by LABEL, not by parsing their name: a stack name may contain the same
# hyphens the name format uses, so `harnessed-cfg-claude-a-b` is ambiguous about where the harness
# ends and the stack begins. The labels carry the fields directly (bd harnessed-8px.21.8).
_VOL_LABEL = "harnessed.role"


_VOL_STACK_LABEL = "harnessed.stack"


_VOL_HARNESS_LABEL = "harnessed.harness"


def _volume_labels(stack: str, harness: str, role: str) -> list[str]:
    return [
        "--label", f"{_VOL_LABEL}={role}",
        "--label", f"{_VOL_STACK_LABEL}={stack}",
        "--label", f"{_VOL_HARNESS_LABEL}={harness}",
    ]


def _stack_tools_volume(stack: str, harness: str) -> str:
    """Name of the per-stack TOOLS volume — `~/.local`, which covers all three PATH-bearing dirs.

    Verified in the bd harnessed-8px.21.1 spike: `$PNPM_HOME` is `~/.local/share/pnpm`, mise keeps
    its installs and its 67 shims under `~/.local/share/mise`, and `$HARNESSED_BIN_DIR` is
    `~/.local/bin`. One volume at the common parent covers all three, and podman's copy-up carries
    the base image's own mise/snyk/socket IN rather than hiding them.
    """
    return f"harnessed-tools-{harness}-{stack}"


def _container_stack_fingerprint(rt: str, stack: str, recipes: list, image: str) -> str:
    """The container gate: the host fingerprint PLUS the image's identity.

    The extra component is forced by podman's copy-up, which runs exactly ONCE per volume. After
    that the volume's content wins permanently and image updates are invisible — so a base image
    that gained a tool would never reach an existing stack, and nothing would signal it. Verified in
    the harnessed-8px.21.1 spike.

    Host mode needs no such component because a host launch has no image at all, which is why
    `_host_stack_fingerprint` carries `__version__` instead.
    """
    img = subprocess.run(
        [rt, "image", "inspect", "-f", "{{.Id}}", image], capture_output=True, text=True,
    ).stdout.strip()
    return f"{_host_stack_fingerprint(stack, recipes)}:{img}"


def _volume_read(rt: str, volume: str, image: str, rel: str) -> str | None:
    """`cat` one file out of the config volume, or None when absent.

    None vs "" is load-bearing for the settings merge, which must distinguish "no baked file"
    (keep the floor) from "empty file".
    """
    out = subprocess.run(
        [rt, "run", "--rm", paths.USERNS_ARG,
         "-v", f"{volume}:{_CONTAINER_HOME_STR}/.claude", "--entrypoint", "sh", image,
         "-c", f"cat {_CONTAINER_HOME_STR}/.claude/{rel}"],
        capture_output=True, text=True,
    )
    # Anything other than a clean read is "absent", NOT "empty". Returning "" for a failed podman
    # run made `_merge_baked_settings` treat an unreadable volume as MALFORMED JSON — it warned and
    # kept the floor, which looks identical to the harnessed-8px.19 regression this is meant to
    # prevent. Caught by test_merge_baked_settings_reads_the_VOLUME_not_the_image.
    return out.stdout if out.returncode == 0 else None


def _run_container_installs(
    rt: str, stack: str, harness: str, image: str, recipes: list, cfg_vol: str, tools_vol: str,
) -> None:
    """Run `tools:` then every `install.script` INSIDE a container, writing to the two volumes.

    The container half of `_host_run_installs`, in deliberately the same ORDER: `tools:` owns the
    binary and an install.sh CONFIGURES it (`serena init -b LSP`, ccstatusline's `command -v`), so
    the binary must exist first. A real build failed the other way round.

    One container per step rather than one generated shell script: each recipe's env differs, and
    passing it with `-e` avoids hand-quoting a script whose failure mode is silent and
    arbitrary-code-shaped.

    `paths.USERNS_ARG` on every step, matching the pod the agent inherits. A volume written under
    any other mapping is unreadable by the agent (harnessed-8px.21.1).
    """
    common = [
        paths.USERNS_ARG,
        "-v", f"{cfg_vol}:{_CONTAINER_HOME_STR}/.claude",
        "-v", f"{tools_vol}:{_CONTAINER_HOME_STR}/.local",
        # The download cache, and the direct successor to the build's `--mount=type=cache` (bd
        # harnessed-1t4.2: "a layer cache MISS must not mean a re-download"). Those mounts died with
        # the layers; without this the container's ~/.cache is ephemeral and every reinstall
        # re-fetches from the network, which would make the runtime executor SLOWER than the build
        # it replaces.
        #
        # Deliberately NOT per-stack: one volume shared by every stack, which is the sharing 1t4.2
        # existed for. It covers ~/.cache/{mise,pnpm,uv} in one mount because an install.sh may
        # reach for any of them and that is the recipe author's choice to make.
        "-v", f"{_SHARED_DL_CACHE_VOLUME}:{_CONTAINER_HOME_STR}/.cache",
    ]

    tool_specs = sorted({t for r in recipes for t in r.tools})
    if tool_specs:
        joined = " ".join(f'"{t}"' for t in tool_specs)
        _say(f"[blue][INFO][/blue] tools: {len(tool_specs)} pinned tool(s) → {tools_vol}")
        # MISE_NPM_PACKAGE_MANAGER=pnpm is required, not preferred: mise's own `aube` resolver
        # enforces a tree-wide publisher-trust policy that hard-fails a correctly-pinned package
        # over an untrusted transitive dep. Sorted+deduped so the set, not the authoring order,
        # determines the work.
        _run([rt, "run", "--rm", *common, "-e", "MISE_NPM_PACKAGE_MANAGER=pnpm",
              "--entrypoint", "sh", image, "-c", f"mise use -g {joined} && mise install"])

    for recipe in recipes:
        inst = recipe.install
        if inst is None or inst.script is None:
            continue  # root-only install: the whole step is a system layer in the recipe Dockerfile
        cache_host = paths.install_cache_dir(recipe.name, inst.cache) if inst.cache else None
        ctr_cache = f"{emit.CTR_INSTALL_CACHE}/{recipe.name}/{inst.cache}" if cache_host else ""
        env = emit.install_env(
            recipe, mode="container", harness=harness,
            config_dir=f"{_CONTAINER_HOME_STR}/.claude",
            # The SHARED, cross-stack source cache — the same host dir `_host_run_installs` uses.
            # The build path threw this away (`rm -rf` in the same layer), so every stack re-cloned
            # what another had already fetched. Running at runtime is what makes it reachable.
            cache_dir=ctr_cache,
            bin_dir=f"{_CONTAINER_HOME_STR}/.local/bin",
            home_shim=_CONTAINER_HOME_STR,
        )
        # Recipe `env:` beats the inherited environment; the harnessed contract beats BOTH — same
        # winner as the Dockerfile emission, where inline RUN assignments beat preceding ENV lines.
        merged = {**resolve_recipe_env(recipe, mode="container", project_path=None), **env}
        args = [rt, "run", "--rm", *common,
                "-v", f"{recipe.root}:{emit.CTR_RECIPE_DIR}/{recipe.name}:ro"]
        if cache_host is not None:
            cache_host.parent.mkdir(parents=True, exist_ok=True)
            args += ["-v", f"{cache_host}:{ctr_cache}:rw"]
        for k, v in merged.items():
            args += ["-e", f"{k}={v}"]
        args += ["--entrypoint", "bash", image,
                 f"{emit.CTR_RECIPE_DIR}/{recipe.name}/{inst.script}"]
        _say(f"[blue][INFO][/blue] install ({recipe.name}): {inst.script} (container)")
        _run(args)


def _ensure_stack_volumes(
    rt: str, stack: str, harness: str, prof: Path, image: str, recipes: list,
) -> tuple[str, str]:
    """Compose both per-stack volumes, running installs only when the fingerprint moved.

    The container mirror of the host path's `rebuilt` gate: when the stack is unchanged the install
    output is still sitting in the volume, so re-running would re-download and re-extract bytes
    already on disk.

    Called by BOTH `harnessed build` and `harnessed launch`. That shared call is what keeps `build`
    meaningful once it emits system layers only — build populates and then scans, launch populates
    and runs.

    The stamp is written only AFTER the installs succeed, mirroring the host path: a failed install
    must never certify content that was never finished, or the next launch trusts a stamp for a
    half-populated volume instead of retrying.

    The fingerprint is read BEFORE composing, because a changed stack must start from an EMPTY
    config volume. Composition only ever adds, so reusing the old volume would leave a removed
    recipe's skills and commands in place forever.
    """
    tools_vol = _stack_tools_volume(stack, harness)
    _run([rt, "volume", "create", *_volume_labels(stack, harness, "tools"), tools_vol],
         check=False, capture_output=True)
    _run([rt, "volume", "create", "--label", f"{_VOL_LABEL}=shared", _SHARED_DL_CACHE_VOLUME],
         check=False, capture_output=True)

    want = _container_stack_fingerprint(rt, stack, recipes, image)
    have = _volume_read(
        rt, _stack_config_volume(stack, harness), image, _HOST_STACK_FINGERPRINT
    )
    unchanged = (have or "").strip() == want

    # `fresh=` discards the old config volume when the stack moved. The TOOLS volume is kept either
    # way: `mise use -g` is declarative, so a changed tool set rewrites the config it reads, and
    # discarding it would re-download every pinned tool for no benefit. Host mode draws the same
    # line — `_materialize_host_home` wipes the config home but never the stack's tools dir.
    cfg_vol = _ensure_config_volume(rt, stack, harness, prof, image, fresh=not unchanged)
    if unchanged:
        _say(f"[blue][INFO][/blue] Stack unchanged — reusing {cfg_vol} (installs skipped)")
        return cfg_vol, tools_vol

    _run_container_installs(rt, stack, harness, image, recipes, cfg_vol, tools_vol)
    _run([rt, "run", "--rm", paths.USERNS_ARG,
          "-v", f"{cfg_vol}:{_CONTAINER_HOME_STR}/.claude", "--entrypoint", "sh", image, "-c",
          f"printf %s {shlex.quote(want)} > {_CONTAINER_HOME_STR}/.claude/{_HOST_STACK_FINGERPRINT}"],
         capture_output=True)
    return cfg_vol, tools_vol
