"""`_COMMANDS` must list every registered subcommand.

`launcher.main()` treats the first non-option token as a STACK NAME and prepends `launch` unless
that token is in `_COMMANDS`. So a subcommand missing from the set is not merely undocumented — it
is unreachable, and it fails with "Missing argument 'HARNESS'", which reads like the user's mistake
rather than a missing registration. Found when `volume-gc` (bd harnessed-8px.21.8) was added and
routed to `launch`.
"""
from __future__ import annotations

from harnessed.launcher import _COMMANDS, app


def _registered() -> set[str]:
    names = {c.name for c in app.registered_commands if c.name}
    for group in app.registered_groups:
        if group.name:
            names.add(group.name)
    return names


def test_every_registered_command_is_routable():
    missing = sorted(_registered() - _COMMANDS)
    assert not missing, (
        "these subcommands are registered but absent from _COMMANDS, so `main()` will route them "
        f"to `launch` and they will fail with a confusing usage error: {missing}"
    )


def test_no_stale_entries():
    """A name in the set that no command answers to shadows a STACK of that name."""
    stale = sorted(_COMMANDS - _registered() - {"launch"})
    assert not stale, f"_COMMANDS lists names no command is registered for: {stale}"


def test_container_env_trusts_the_projects_mise_config():
    """bd harnessed-8px.27.

    `_write_project_tool_env` drops a `mise.local.toml` into EVERY project, and mise refuses an
    untrusted config. The image's `mise trust -a` lives in ~/.bashrc and /etc/profile.d, which only
    run for a login or interactive shell — but setup scripts run as `podman exec … bash <script>`,
    which is neither. serena's setup died on exactly this, because its binary is a mise shim and
    merely invoking it loads the project config.

    Asserted on the source rather than a live launch: the value is the mount path, which only exists
    mid-launch, and the failure mode is the var being dropped from the `podman run` line entirely.
    """
    import inspect

    from harnessed import launcher

    src = inspect.getsource(launcher.launch)
    assert "MISE_TRUSTED_CONFIG_PATHS" in src, "the project's mise config is not trusted"
    assert "*mise_trust_env," in src, (
        "MISE_TRUSTED_CONFIG_PATHS is built but never spliced into the container's `podman run`"
    )
