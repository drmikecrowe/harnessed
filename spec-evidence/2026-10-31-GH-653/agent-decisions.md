# Agent decisions: `use` runs install scripts in the stack mise environment

### A1. `use` also restores `PATH`, not only the mise session variables
- Other option: restore the mise session variables only, as `_launch_host` does for the agent.
- Why: `use` calls `claude plugin` after the installs, and a `claude` reached through a mise shim breaks under a redirected `PATH` and mise environment (#449), so both go back.
- Command: hotfix

### A2. The redirect stays inline in `use`, not in a new shared helper
- Other option: move the snapshot, apply and restore into a helper in `hostrun.py` that `_launch_host` also calls.
- Why: `_launch_host` keeps the redirect for its whole launch and restores only the agent's copy, so the two lifetimes differ, and a shared helper would change `host-run`, which the Must NOT list forbids.
- Command: hotfix

### A3. `use` does not call `_apply_host_tool_path` itself
- Other option: call it before `_host_install_tools`, as `_launch_host` does.
- Why: `_host_install_tools` and `_host_run_installs` already put the prefix on the install scripts' `PATH`, a mutant without the call passed every test, and `_launch_host` needs its own call only for the MCP presence check, which `use` does not run at that point.
- Command: build
