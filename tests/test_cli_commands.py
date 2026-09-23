"""CLI-level invariants that only hold at the `app` boundary.

This file used to police `_COMMANDS`, the hand-maintained set naming every token `launcher.main()`
must NOT mistake for a stack. A registered command missing from it was unreachable and failed with
"Missing argument 'HARNESS'", which read like the user's mistake rather than a missing registration
(found when `volume-gc` was added — bd harnessed-8px.21.8). Both guard tests went with the
mechanism: the stack is named by `--stack` now, so a leading token is always a subcommand and there
is no set to keep in step.
"""
from __future__ import annotations

import sys

import pytest

from harnessed import launcher, persist


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

    src = inspect.getsource(launcher.ContainerBackend.apply_isolation)
    assert "MISE_TRUSTED_CONFIG_PATHS" in src, "the project's mise config is not trusted"
    assert "*mise_trust_env," in src, (
        "MISE_TRUSTED_CONFIG_PATHS is built but never spliced into the container's `podman run`"
    )


class TestPersistRefusalIsNotACrash:
    """The persist gate is default-deny, so a refusal is a normal first-launch outcome.

    Every refusal message already names its remediation (the exact allowlist line, or the chown).
    Uncaught, typer's excepthook wraps it in a Rich traceback and the remediation reads as harnessed
    crashing on the user. `main()` is the only place that covers every verb the gate runs from.
    """

    @pytest.mark.parametrize(
        "err",
        [
            persist.PersistDeniedError,
            persist.PersistNotAllowlistedError,
            persist.PersistOwnershipError,
        ],
    )
    def test_the_message_survives_and_the_exit_is_clean(self, err, monkeypatch, capsys):
        def refuse():
            raise err("add /home/u/.config/gh to the allowlist")

        monkeypatch.setattr(launcher, "app", refuse)
        monkeypatch.setattr(sys, "argv", ["harnessed", "omp"])

        with pytest.raises(SystemExit) as caught:
            launcher.main()

        assert caught.value.code == 1
        # `from None` — otherwise the refusal is still chained and prints as a traceback anyway.
        assert caught.value.__suppress_context__
        assert "allowlist" in capsys.readouterr().err

    def test_other_failures_keep_their_traceback(self, monkeypatch):
        """Narrow on purpose: only the gate's own errors lose their traceback."""

        def boom():
            raise RuntimeError("unrelated")

        monkeypatch.setattr(launcher, "app", boom)
        monkeypatch.setattr(sys, "argv", ["harnessed", "omp"])

        with pytest.raises(RuntimeError):
            launcher.main()
