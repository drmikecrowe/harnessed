# gsd-core

GSD Core — a spec-driven-development suite of skills, agents, and workflows. Installed by running
its own upstream installer (`@opengsd/gsd-core`), pinned to an exact version in `recipe.yaml`.

Ships as skills/agents written by that installer, which `install.sh` invokes. No MCP server.

## Container vs `harnessed host-run`

`install.sh` runs in **both** modes and does the same thing in each — this is a pure content recipe,
so nothing is skipped host-side. The installer's `--global` flag targets `os.homedir()/.claude`. On a
host-native launch, `install.sh` points a throwaway `$HOME` at the stack's own config dir so "global"
means *this stack*, never your real `~/.claude`.

The installer itself comes from the recipe's `tools:` entry (`npm:@opengsd/gsd-core@<version>`),
installed before `install.sh` runs in both modes. If that bin is missing the install fails loudly,
naming `tools:`, rather than silently shipping a stack with no GSD skills.

## Footprint / removal

Everything the installer writes lands inside the stack's config dir, and the package itself lives in
the stack's own mise tree. Both go with the stack, and nothing is written to your real `~/.claude`
or your global mise config.

**Do not delete the tools tree on its own.** A host launch reprovisions only when the stack's
fingerprint changed; the stamp that records it (`.harnessed-stack`) lives in the stack's *home*, not
in the tools tree. Removing the tools tree alone leaves that stamp intact, so the next launch prints
"Stack unchanged — reusing … (installs skipped)" and never puts the tools back. That is the same
silently-half-installed state bd harnessed-8px.15 exists to prevent.

To remove a stack, remove its home as well — the home carries the stamp, so dropping it is what
forces the rebuild:

```bash
data="${XDG_DATA_HOME:-$HOME/.local/share}/harnessed"
rm -r "$data/home/<stack>" "$data/tools/<stack>"
```

Upstream: <https://github.com/open-gsd/gsd-core>
