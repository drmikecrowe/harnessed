"""#538: a permission rule the agent writes into its live settings.json survives a relaunch.

Both relaunch paths rebuild settings.json from the profile, and the profile always defines
`permissions` (the floor carries `mcp__hatago` and `defaultMode`). Before the fix the live block was
replaced wholesale, so a "Don't ask again" answer was gone on the next launch. Each path is pinned
here: the host's `_propagate_host_settings` and the container's `_merged_settings_text`.
"""

import json

import pytest

from harnessed import hosthome, launcher, paths, volumes
from support import patch_all

# What the assembled profile always carries: harnessed's required grant plus the mode floor.
_PROFILE = {
    "permissions": {
        "defaultMode": "acceptEdits",
        "allow": ["mcp__hatago"],
    },
}

# What Claude Code wrote into the live file during the last session.
_LIVE = {
    "permissions": {
        "defaultMode": "stale",
        "allow": ["mcp__hatago", "Read(~/.claude/projects/**)"],
        "deny": ["Bash(rm:*)"],
        "ask": ["Bash(git push:*)"],
        "additionalDirectories": ["/srv/data"],
    },
}


def _assert_rules_carried(got: dict) -> None:
    perms = got["permissions"]
    assert perms["allow"] == ["mcp__hatago", "Read(~/.claude/projects/**)"], (
        "the profile's grant must come first and the live rule must survive, once each"
    )
    assert perms["deny"] == ["Bash(rm:*)"]
    assert perms["ask"] == ["Bash(git push:*)"]
    assert perms["additionalDirectories"] == ["/srv/data"]
    assert perms["defaultMode"] == "acceptEdits", "the profile must still win on scalars"


class TestHostPath:
    def test_live_permission_rules_survive_the_propagation(self, tmp_path):
        prof, live = tmp_path / "profile.json", tmp_path / "settings.json"
        prof.write_text(json.dumps(_PROFILE))
        live.write_text(json.dumps(_LIVE))

        hosthome._propagate_host_settings(prof, live)

        _assert_rules_carried(json.loads(live.read_text()))

    def test_no_live_extras_keeps_the_byte_identical_copy(self, tmp_path):
        """With nothing to carry, the live file is the profile's bytes exactly."""
        prof, live = tmp_path / "profile.json", tmp_path / "settings.json"
        prof.write_text(json.dumps(_PROFILE, indent=4))
        live.write_text(json.dumps({"permissions": {"allow": ["mcp__hatago"]}}))

        hosthome._propagate_host_settings(prof, live)

        assert live.read_text() == prof.read_text()

    def test_a_rebuild_starts_from_the_profile_alone(self, tmp_path, monkeypatch):
        """Host `--fresh` discards the build stamp, which forces this rebuild."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s-538", "claude")
        prof.mkdir(parents=True)
        (prof / "settings.json").write_text(json.dumps(_PROFILE))
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")

        home, _a, _c, _r = launcher._host_launch_plan("s-538", "claude", tmp_path, recipes=[])
        launcher._stamp_host_home(home, "fp-1")
        (home / "settings.json").write_text(json.dumps(_LIVE))

        # Unchanged stack: the live rule survives.
        home, _a, _c, rebuilt = launcher._host_launch_plan("s-538", "claude", tmp_path, recipes=[])
        assert rebuilt is False
        _assert_rules_carried(json.loads((home / "settings.json").read_text()))

        # Changed stack: the wholesale rebuild resets to the profile.
        patch_all(monkeypatch, "_host_stack_fingerprint", lambda stack, recipes: "fp-2")
        home, _a, _c, rebuilt = launcher._host_launch_plan("s-538", "claude", tmp_path, recipes=[])
        assert rebuilt is True
        assert json.loads((home / "settings.json").read_text()) == _PROFILE


class TestContainerPath:
    @pytest.fixture
    def prof(self, tmp_path):
        (tmp_path / "settings.json").write_text(json.dumps(_PROFILE))
        return tmp_path

    def test_live_permission_rules_survive_the_merge(self, prof, monkeypatch):
        monkeypatch.setattr(volumes, "_volume_read", lambda *a: json.dumps(_LIVE))

        text = volumes._merged_settings_text("podman", "vol", "img", prof, fresh=False)

        assert text is not None
        _assert_rules_carried(json.loads(text))

    def test_fresh_starts_from_the_profile_alone(self, prof, monkeypatch):
        monkeypatch.setattr(volumes, "_volume_read", lambda *a: json.dumps(_LIVE))

        assert volumes._merged_settings_text("podman", "vol", "img", prof, fresh=True) is None, (
            "None means the plain profile copy stands"
        )
