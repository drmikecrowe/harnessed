# Agent decisions: keep the host Claude login refreshed when the refresher starts from an isolated tree

### A1. The refresher log moves with the lock
- Other option: leave `claude-auth-refresher.log` under `XDG_STATE_HOME` and move only the lock.
- Why: each refresher truncates its log on start, so an isolated refresher would wipe the real one's log, and `_warn_if_refresh_failing` would report the wrong refresher.
- Command: hotfix

### A2. Tier 3, with property and mutation layers
- Other option: Tier 2, the full loop with no property or mutation testing.
- Why: the loop's tier list names auth as Tier 3, and a wrong ownership answer either logs every stack out or writes a login into the wrong file.
- Command: hotfix
