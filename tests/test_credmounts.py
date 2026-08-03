"""`credmounts` — host credential forwarding, extracted from launcher.py (bd harnessed-4l8).

The per-builder behaviour (1Password vs gpg-agent precedence, YubiKey vendor-id matching, the
~/.ssh allow-list) is covered by tests/test_launcher_install.py::TestCredentialForwarding, which
still drives it through `launcher`. What lives HERE is what the extraction put at risk: the
direction of the dependency, and the security properties that are the whole reason these builders
are written the way they are — a move that quietly widened one would not fail any existing test.
"""

from __future__ import annotations

import ast

from pathlib import Path

import pytest

from harnessed import credmounts
from harnessed.paths import CONTAINER_HOME


class TestModuleBoundary:
    """The direction rule from the dynstack exemplar — see
    tests/test_dynstack.py::TestModuleBoundary. Pure derivation lives in a focused module;
    launcher.py keeps the Typer surface and podman orchestration; dependencies point INTO the
    module and never back out.
    """

    def test_credmounts_does_not_import_launcher_at_any_depth(self):
        """Checked over the parsed IMPORTS, not the raw text.

        `test_dynstack.py` asserts the string "launcher" is absent from the source, which works
        there and does not work here: `_gnupg_mounts`'s docstring explains what the BASH launcher
        used to mount and why that was wrong, and that prose moved verbatim with the code. A pure
        move must not reword the thing it moves, so the check has to test the dependency rather
        than the vocabulary.

        `ast.walk` descends into function bodies, so a function-local `import launcher` — which
        would keep the coupling while looking clean at the top of the file, including on a branch
        no test happens to take — is caught too.
        """
        src = (Path(__file__).parent.parent / "src" / "harnessed" / "credmounts.py").read_text()
        imported: list[str] = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported += [node.module or ""] + [a.name for a in node.names]
        assert not [name for name in imported if "launcher" in name], imported

    def test_container_home_tracks_paths(self):
        """The module derives `_CONTAINER_HOME_STR` itself rather than importing launcher's copy.
        `paths.CONTAINER_HOME` stays the single source of truth, so the two must not drift."""
        assert credmounts._CONTAINER_HOME_STR == str(CONTAINER_HOME)


class TestPrivateKeyMaterialIsNeverForwarded:
    """The security property the whole module exists to hold: reference the live credential store,
    never replicate the secret (ARCHITECTURE.md §Constraints). These assert on what is ABSENT from
    the generated args, which is exactly what a careless move could widen without failing anything.
    """

    def test_gnupg_private_keyring_is_never_mounted(self, tmp_path):
        """`private-keys-v1.d/` holds real secret key material for software openpgp keys. The bash
        launcher mounted all of ~/.gnupg; `ro` does not help, because readable means exfiltratable
        by an agent in the container."""
        home = tmp_path
        gnupg = home / ".gnupg"
        (gnupg / "private-keys-v1.d").mkdir(parents=True)
        (gnupg / "private-keys-v1.d" / "ABCD.key").write_text("SECRET KEY MATERIAL")
        (gnupg / "pubring.kbx").write_text("public")
        (gnupg / "trustdb.gpg").write_text("trust")

        args = credmounts._gnupg_mounts(home)

        assert not any("private-keys-v1.d" in a for a in args)
        assert not any("ABCD.key" in a for a in args)
        # The non-secret surface still comes through, or the mount would be pointless.
        assert any("pubring.kbx" in a for a in args)
        assert all(a.endswith(":ro") for a in args if a.startswith(str(gnupg)))

    def test_ssh_dir_forwards_public_surface_but_no_unlisted_private_key(self, tmp_path):
        home = tmp_path
        ssh = home / ".ssh"
        ssh.mkdir()
        (ssh / "id_ed25519").write_text("PRIVATE")
        (ssh / "id_ed25519.pub").write_text("public")
        (ssh / "config").write_text("Host *")
        (ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAA")

        args = credmounts._ssh_dir_mounts(home, [])

        joined = " ".join(args)
        assert "id_ed25519.pub" in joined and "config" in joined and "known_hosts" in joined
        # The private key is present on disk and NOT opted in, so it must not appear. Checked
        # without the `.pub` suffix so the public identity does not satisfy the assertion.
        assert not any(a.endswith(f"{ssh}/id_ed25519") or f"/id_ed25519:" in a for a in args)

    def test_opted_in_private_key_is_mounted_read_only(self, tmp_path):
        """`ssh_keys:` is the escape hatch for hosts with no agent — it must work, and only ro."""
        home = tmp_path
        ssh = home / ".ssh"
        ssh.mkdir()
        (ssh / "id_ed25519").write_text("PRIVATE")

        args = credmounts._ssh_dir_mounts(home, ["id_ed25519"])

        assert ["-v", f"{ssh / 'id_ed25519'}:{CONTAINER_HOME}/.ssh/id_ed25519:ro"] == args

    def test_a_symlink_escaping_ssh_dir_is_refused(self, tmp_path):
        """Defense-in-depth: `~/.ssh/config -> ~/.aws/credentials` must not mount the secret target
        just because the NAME is on the always-forward list."""
        home = tmp_path
        ssh = home / ".ssh"
        ssh.mkdir()
        secret = home / "aws-credentials"
        secret.write_text("[default]\naws_secret_access_key = REAL")
        (ssh / "config").symlink_to(secret)
        # A legitimate file alongside it, so an empty result cannot pass this test by accident.
        (ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAA")

        args = credmounts._ssh_dir_mounts(home, [])

        assert not any("aws-credentials" in a for a in args)
        assert args == ["-v", f"{ssh / 'known_hosts'}:{CONTAINER_HOME}/.ssh/known_hosts:ro"]

    def test_an_opted_in_key_cannot_escape_the_ssh_dir(self, tmp_path):
        home = tmp_path
        ssh = home / ".ssh"
        ssh.mkdir()
        secret = home / "elsewhere.key"
        secret.write_text("PRIVATE")
        (ssh / "linked").symlink_to(secret)
        (ssh / "id_ed25519").write_text("PRIVATE BUT OPTED IN")

        args = credmounts._ssh_dir_mounts(home, ["linked", "id_ed25519"])

        assert not any("elsewhere.key" in a for a in args)
        # The in-dir opt-in still lands, so a blanket "return []" would not satisfy this.
        assert args == ["-v", f"{ssh / 'id_ed25519'}:{CONTAINER_HOME}/.ssh/id_ed25519:ro"]

    def test_a_colon_in_a_name_does_not_reparse_the_volume_spec(self, tmp_path):
        """`-v src:dst:opts` is colon-delimited, so a name carrying one would change what gets
        mounted where. Host-derived names must be skipped, not interpolated."""
        home = tmp_path
        ssh = home / ".ssh"
        ssh.mkdir()
        (ssh / "we:ird.pub").write_text("public")
        (ssh / "config").write_text("Host *")

        args = credmounts._ssh_dir_mounts(home, [])

        assert not any("we:ird" in a for a in args)
        assert any("config" in a for a in args)


class TestGhHostsMissingPlaintextToken:
    """Drives a warning about `gh` in the container having no usable token, so a false positive
    nags on a working setup and a false negative hides a broken one."""

    def test_keychain_backed_entry_has_no_token(self, tmp_path):
        # Confirmed shape on macOS: the token is entirely absent, not present-but-empty.
        hosts = tmp_path / "hosts.yml"
        hosts.write_text("github.com:\n  users:\n    someone: {}\n  user: someone\n")
        assert credmounts._gh_hosts_missing_plaintext_token(hosts) is True

    def test_plaintext_token_anywhere_counts(self, tmp_path):
        hosts = tmp_path / "hosts.yml"
        hosts.write_text("github.com:\n  users:\n    someone:\n      oauth_token: gho_x\n")
        assert credmounts._gh_hosts_missing_plaintext_token(hosts) is False

    def test_empty_file_does_not_warn(self, tmp_path):
        """No entries at all is not the same as entries-without-a-token — nothing to warn about."""
        hosts = tmp_path / "hosts.yml"
        hosts.write_text("")
        assert credmounts._gh_hosts_missing_plaintext_token(hosts) is False

    def test_unparseable_file_does_not_warn(self, tmp_path):
        hosts = tmp_path / "hosts.yml"
        hosts.write_text("{{{ not yaml")
        assert credmounts._gh_hosts_missing_plaintext_token(hosts) is False


class TestGitIdentityConfigMount:
    def test_xdg_git_dir_wins_over_legacy_gitconfig(self, tmp_path):
        home = tmp_path
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".gitconfig").write_text("[user]\n  name = legacy\n")

        args = credmounts._git_identity_config_mount(home)

        assert args == ["-v", f"{home / '.config' / 'git'}:{CONTAINER_HOME}/.config/git:ro"]

    def test_legacy_gitconfig_used_when_no_xdg_dir(self, tmp_path):
        home = tmp_path
        (home / ".gitconfig").write_text("[user]\n  name = t\n")

        args = credmounts._git_identity_config_mount(home)

        assert args == ["-v", f"{home / '.gitconfig'}:{CONTAINER_HOME}/.gitconfig:ro"]

    def test_neither_present_is_a_noop(self, tmp_path):
        assert credmounts._git_identity_config_mount(tmp_path) == []


class TestTrustedSshKeys:
    """Mounting a real private key is the KEY OWNER's decision, not a shared-catalog stack
    author's — so the gate is on where the stack.yaml came from."""

    def test_keys_from_a_shared_catalog_stack_are_dropped(self):
        assert credmounts._trusted_ssh_keys(["id_ed25519"], False, "shared") == []

    def test_keys_from_the_user_overlay_are_honored(self):
        assert credmounts._trusted_ssh_keys(["id_ed25519"], True, "mine") == ["id_ed25519"]

    def test_no_keys_declared_is_not_a_warning_either_way(self):
        assert credmounts._trusted_ssh_keys([], False, "shared") == []


class TestHostOsGatedBuilders:
    @pytest.mark.parametrize("os_name", ["macos", "other"])
    def test_yubikey_passthrough_is_linux_only(self, monkeypatch, os_name):
        """macOS runs the container in a Linux VM with no /dev/bus/usb, so USB passthrough is not
        possible there — it must not even shell out to lsusb."""
        monkeypatch.setattr(credmounts, "_host_os", lambda: os_name)
        ran: list[int] = []
        monkeypatch.setattr(credmounts.subprocess, "run", lambda *a, **k: ran.append(1))

        assert credmounts._yubikey_device_args() == []
        assert ran == []

    def test_op_agent_socket_path_is_os_aware(self, tmp_path, monkeypatch):
        monkeypatch.setattr(credmounts, "_host_os", lambda: "macos")
        assert "Group Containers" in str(credmounts._op_agent_socket(tmp_path))
        monkeypatch.setattr(credmounts, "_host_os", lambda: "linux")
        assert credmounts._op_agent_socket(tmp_path) == tmp_path / ".1password" / "agent.sock"
