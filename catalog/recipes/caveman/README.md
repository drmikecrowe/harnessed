# caveman

An output-compression skill: the agent answers in terse "caveman" prose — roughly 75% fewer output
tokens — while keeping full technical accuracy. Code, commands, and paths are never caveman-ified.

Levels: `lite`, `full`, `ultra`, and `wenyan` variants. Ships as skills and commands installed by
the recipe's `install.sh` — in the container image and on a `--host` launch alike. No MCP server.

## Removing what this recipe leaves behind

Everything `install.sh` writes lands under the harnessed-owned agent config dir, which is rebuilt
from scratch on every launch — nothing to clean up there.

The one write **outside** harnessed-owned space is the first-run marker the recipe's `SessionStart`
hook drops in each project it has greeted, so the `/caveman-init` nudge fires once per repo. To
reset it (or to remove it after dropping the recipe), run this in the project:

```bash
rm -f .claude/.caveman-notified
```

Upstream: <https://github.com/JuliusBrussee/caveman>
