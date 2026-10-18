# ponytail

"Lazy senior dev" mode: the agent writes the simplest code that works. YAGNI, stdlib first, no unrequested abstractions.

Ships six skills (`ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`) and three Claude lifecycle hooks, installed by the recipe's `install.sh` in the container image and on a `--host` launch alike. The hooks inject the ruleset at session start and into subagents, and keep the `/ponytail lite|full|ultra|off` level across prompts. They need `node`, which harnessed-base provides; without it they exit 0 and only the skills work.

Not carried from the upstream plugin: the Gemini-format `commands/*.toml`, the statusline badge, and the task-board ledger (`hooks/claude-band.json`).

## Removing what this recipe leaves behind

`install.sh` writes only under the harnessed-owned agent config dir.

The hooks write the active level under that same config dir: a shared `.ponytail-active` flag, plus one file per project in `ponytail-modes/`. Nothing lands in the project tree.

Upstream: <https://github.com/DietrichGebert/ponytail>
