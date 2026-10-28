"""Integrations: register a stack with an external tool, run as `--register-<name>-only` (GH-569).

An integration is `integrations/<name>/register` in a catalog root: an executable file. The roots are
`paths.catalog_roots()`, overlay first, so a user adds or overrides one in
`~/.config/harnessed/catalog/integrations/<name>/register` and nothing under `src/` changes.

The launcher reads the flag on its four global verbs, builds the stack when its profile is missing
or stale (`needs_build`), writes the global launchers, and runs the file with no arguments, in the
project, with the parent environment plus the `HARNESSED_*` names `environ` sets. The launch exits
with the file's status and starts no agent. The contract is in the GH-569 SPEC, "The integration
contract".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import launchscript, paths, staleness
from .attachcmd import _ACP_HARNESSES
from .schema import SchemaError

_FLAG = re.compile(r"--register-([a-z0-9][a-z0-9-]*)-only")

# The verbs a global launcher execs (GH-565). Nothing else reads the flag, so `harnessed build`
# and every other verb reject it as an unknown option.
VERBS = ("host-run", "container-run", "host-acp", "container-acp")

# Set only when the launch was given the matching flag, and removed from the parent's environment
# otherwise: one left there by an outer launch would read as this launch's flag.
_OPTIONAL = (
    "HARNESSED_NO_STRICT_MCP", "HARNESSED_AOE_GROUP", "HARNESSED_AOE_TITLE",
    "HARNESSED_AOE_MANAGED_WORKTREE",
)


class IntegrationError(Exception):
    """A register run that cannot start. `code` is the exit status: 2 for a usage error."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def extract(argv: list[str]) -> tuple[list[str], Optional[str]]:
    """Split one `--register-<name>-only` off a global verb's argv, before any `--`.

    Returns `(argv without the flag, name)`, or `(argv, None)` when there is no flag. A flag after
    `--` is the harness's passthrough. Two flags raise `IntegrationError` (exit 2): one run, one
    integration, one exit status.
    """
    if not argv or argv[0] not in VERBS:
        return argv, None
    end = argv.index("--") if "--" in argv else len(argv)
    hits = [(i, m.group(1)) for i in range(end) if (m := _FLAG.fullmatch(argv[i]))]
    if not hits:
        return argv, None
    if len(hits) > 1:
        raise IntegrationError("only one --register-<name>-only flag is allowed per command", 2)
    i, name = hits[0]
    return [*argv[:i], *argv[i + 1 :]], name


def find(name: str) -> Path:
    """The `register` file of integration `name`, overlay first. Raises `IntegrationError` (exit 2)
    when no root has one, listing every name the roots hold, or when the file is not executable."""
    script = paths.find_in_catalog("integrations", name) / "register"
    if not script.is_file():
        names = paths.list_catalog("integrations")
        raise IntegrationError(
            f"no integration named '{name}'; available: {', '.join(names) or 'none'}", 2
        )
    if not os.access(script, os.X_OK):
        raise IntegrationError(f"{script} is not executable (chmod +x it)", 2)
    return script


def check(script: Path, harness: str, verb: str) -> None:
    """Refuse, before any build, a run the integration's optional `requires` file rules out.

    One requirement per line, `#` starts a comment: `harness <name>...`, `backend host|container`
    and `verb <global verb>...` list what the integration supports, and `acp` needs a harness with
    an ACP mode. Raises
    `IntegrationError`: exit 1 for a run ruled out, exit 2 for a line it cannot read.
    """
    spec = script.parent / "requires"
    if not spec.is_file():
        return
    name = script.parent.name
    backend = "container" if verb.startswith("container-") else "host"
    try:
        text = spec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise IntegrationError(f"{spec}: cannot read it: {exc}", 2) from exc
    for line in text.splitlines():
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        key, values = words[0], words[1:]
        if key == "harness":
            if harness not in values:
                raise IntegrationError(
                    f"the {name} integration supports {', '.join(values)} only (got {harness})", 1
                )
        elif key == "backend":
            if backend not in values:
                raise IntegrationError(
                    f"the {name} integration supports the {' or '.join(values)} backend only", 1
                )
        elif key == "verb":
            if verb not in values:
                raise IntegrationError(
                    f"the {name} integration supports the {' or '.join(values)} verbs only", 1
                )
        elif key == "acp":
            if values:
                raise IntegrationError(f"{spec}: 'acp' takes no values", 2)
            if harness not in _ACP_HARNESSES:
                raise IntegrationError(
                    f"{name.capitalize()} needs an ACP harness; {harness} has no ACP mode "
                    f"(ACP harnesses: {', '.join(_ACP_HARNESSES)})", 1
                )
        else:
            raise IntegrationError(f"{spec}: unknown requirement '{key}'", 2)


def needs_build(stack: str, harness: str) -> bool:
    """Whether the profile is missing or stale, the same check `container-run` makes. A recipe that
    no longer resolves also says yes: the build then fails with the reason, and nothing runs."""
    if not paths.is_built(stack, harness):
        return True
    try:
        staleness.check_profile_fresh(None, stack, harness)
    except (staleness.StaleProfileError, SchemaError):
        return True
    return False


def environ(
    name: str, verb: str, harness: str, stack: str, project: Path, *,
    no_strict_mcp: bool = False, aoe_group: Optional[str] = None, aoe_title: Optional[str] = None,
    aoe_managed_worktree: bool = False,
) -> dict[str, str]:
    """The parent environment plus the contract's names. Every added value is a name, a path, `1`,
    or an `--aoe-*` value the user typed: no credential store is read to build them."""
    backend = "container" if verb.startswith("container-") else "host"
    bin_dir = paths.user_bin_dir()

    def launcher(v: str) -> str:
        return str(bin_dir / launchscript.global_name(v, stack, harness))

    acp = f"{backend}-acp"
    env = {k: v for k, v in os.environ.items() if k not in _OPTIONAL}
    env.update({
        "HARNESSED_INTEGRATION": name,
        "HARNESSED_HARNESS": harness,
        "HARNESSED_STACK": stack,
        "HARNESSED_BACKEND": backend,
        "HARNESSED_VERB": verb,
        "HARNESSED_LAUNCHER": launcher(verb),
        "HARNESSED_RUN_LAUNCHER": launcher(f"{backend}-run"),
        "HARNESSED_ACP_LAUNCHER": launcher(acp) if acp in launchscript.global_verbs(harness) else "",
        "HARNESSED_PROJECT": str(project),
        "HARNESSED_PYTHON": sys.executable,
    })
    if no_strict_mcp:
        env["HARNESSED_NO_STRICT_MCP"] = "1"
    if aoe_group is not None:
        env["HARNESSED_AOE_GROUP"] = aoe_group
    if aoe_title is not None:
        env["HARNESSED_AOE_TITLE"] = aoe_title
    if aoe_managed_worktree:
        env["HARNESSED_AOE_MANAGED_WORKTREE"] = "1"
    return env


def run(script: Path, env: dict[str, str], cwd: Path) -> int:
    """Run `script` with stdout and stderr passed through; its exit status, a signal as 128+N."""
    try:
        code = subprocess.run([str(script)], cwd=cwd, env=env, check=False).returncode
    except OSError as exc:
        raise IntegrationError(f"cannot run {script}: {exc}", 1) from exc
    return 128 - code if code < 0 else code
