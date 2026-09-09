#!/usr/bin/env python3
"""Patch the mise-installed openwiki 0.4.3 runner to retry a page worker that
ends its turn without calling submit_page.

Why this exists: a worker whose stream ends without a submit (observed with
glm-5.3-flash: 94 LLM calls, clean exit, no tool call) is marked "skipped" by
openwiki, the page snapshot is restored, and the run finalizes "interrupted"
WITHOUT advancing the diff base -- one quit costs the next run a full
regeneration of the whole changeset. Neither 0.4.3 nor 0.5.0 retries a skipped
page (verified against the 0.5.0 tarball 2026-09-08); see PR #445 run 6.
Until upstream ships a retry, this gives each page worker one fresh second
attempt before the page is skipped. The retry shares the worker's virtual
backend, so attempt 2 sees the page markdown attempt 1 already wrote.

The patch fails loudly when its anchor text does not match: that means the
installed openwiki is no longer the verified 0.4.3 layout, and the patch must
be re-derived by a human, not guessed at.

Usage:
  tools/openwiki-retry-patch.py [file.js]   # locate + patch (idempotent)
  tools/openwiki-retry-patch.py --check     # exit 0 patched / 1 not
  tools/openwiki-retry-patch.py --revert    # restore the .orig backup
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys

MARKER = "[openwiki-retry-patch]"
DEFAULT_GLOB = "~/.local/share/mise/installs/npm-openwiki/0.4.3/node_modules/.mise/openwiki@*/node_modules/openwiki/dist/agent/repository-runner.js"
EXPECTED_VERSION = "0.4.3"

AGENT_DECL = "    const agent = createDeepAgent({\n"
AGENT_FACTORY = "    const createWorkerAgent = () => createDeepAgent({\n"

OLD_BLOCK = """\
    try {
        await streamWorkerTools(agent, [
            {
                role: "user",
                content: "Research and document the assigned page, then submit it.",
            },
        ], onEvent);
    }
    catch (error) {
        if (submitted)
            return null;
        if (fatalSubmissionFailure)
            throw error;
        await skipRepositoryPage(run, snapshot);
        emitDeferredPageWarning(job.path, onEvent);
        return snapshot;
    }
    if (submitted)
        return null;
    await skipRepositoryPage(run, snapshot);
    emitDeferredPageWarning(job.path, onEvent);
    return snapshot;
}
"""

NEW_BLOCK = (
    """\
    // """
    + MARKER
    + """ one fresh retry before a page is marked skipped: a worker that
    // ends without submit_page (PR #445 run 6) otherwise costs the run a clean finalize.
    for (let attempt = 1; attempt <= 2; attempt++) {
        try {
            await streamWorkerTools(createWorkerAgent(), [
                {
                    role: "user",
                    content: "Research and document the assigned page, then submit it.",
                },
            ], onEvent);
        }
        catch (error) {
            if (submitted)
                return null;
            if (fatalSubmissionFailure)
                throw error;
        }
        if (submitted)
            return null;
        if (attempt < 2) {
            onEvent?.({
                type: "text",
                source: "main",
                text: `[openwiki-retry-patch] ${job.path} worker ended without submit_page (attempt ${attempt}); retrying with a fresh worker.\\n`,
            });
            continue;
        }
        await skipRepositoryPage(run, snapshot);
        emitDeferredPageWarning(job.path, onEvent);
        return snapshot;
    }
}
"""
)


def find_target(explicit: str | None) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    matches = sorted(glob.glob(os.path.expanduser(DEFAULT_GLOB)))
    if not matches:
        sys.exit(f"error: no openwiki install matches {DEFAULT_GLOB}")
    if len(matches) > 1:
        sys.exit(f"error: ambiguous install paths: {matches}")
    return matches[0]


def install_version(target: str) -> str:
    pkg = os.path.normpath(os.path.join(os.path.dirname(target), "..", "..", "package.json"))
    try:
        with open(pkg) as fh:
            return json.load(fh)["version"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        sys.exit(f"error: cannot read openwiki version from {pkg}: {exc}")


def node_binary() -> str:
    found = shutil.which("node")
    if found:
        return found
    try:
        return subprocess.run(
            ["mise", "where", "node"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        sys.exit(f"error: node not found on PATH or via mise: {exc}")


def syntax_check(target: str) -> None:
    node = node_binary()
    proc = subprocess.run([node, "--check", target], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"error: node --check failed on patched file:\n{proc.stderr}")


def main() -> None:
    args = sys.argv[1:]
    check_only = "--check" in args
    revert = "--revert" in args
    positional = [a for a in args if not a.startswith("--")]
    target = find_target(positional[0] if positional else None)

    backup = target + ".orig"
    if revert:
        if not os.path.exists(backup):
            sys.exit(f"error: no backup at {backup}")
        shutil.copy2(backup, target)
        print(f"reverted: {target}")
        return

    version = install_version(target)
    if version != EXPECTED_VERSION:
        sys.exit(
            f"error: install is openwiki {version}, patch verified against "
            f"{EXPECTED_VERSION} only; refusing to patch"
        )

    with open(target) as fh:
        text = fh.read()

    if MARKER in text:
        print(f"already patched: {target}")
        syntax_check(target)
        return
    if check_only:
        sys.exit(f"not patched: {target}")

    head, sep, tail = text.partition("async function runPageAgent(")
    if not sep:
        sys.exit("error: runPageAgent not found -- anchor drift, re-derive the patch")

    if tail.count(AGENT_DECL) != 1:
        sys.exit(
            f"error: expected exactly one agent declaration in runPageAgent, "
            f"found {tail.count(AGENT_DECL)}"
        )
    if tail.count(OLD_BLOCK) != 1:
        sys.exit(
            f"error: expected exactly one worker try-block in runPageAgent, "
            f"found {tail.count(OLD_BLOCK)}"
        )

    tail = tail.replace(AGENT_DECL, AGENT_FACTORY, 1)
    tail = tail.replace(OLD_BLOCK, NEW_BLOCK, 1)
    patched = head + sep + tail

    if not os.path.exists(backup):
        shutil.copy2(target, backup)

    with open(target, "w") as fh:
        fh.write(patched)
    syntax_check(target)
    print(f"patched: {target} (backup: {backup})")


if __name__ == "__main__":
    main()
