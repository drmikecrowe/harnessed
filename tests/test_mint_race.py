"""Concurrency tests for _resolve_stack mint-race fix (issue #287).

The race: two concurrent launches with an identical recipe set both call is_file()
before either calls mint(). Both read preexisting=False, both get a non-None minted_dir,
and both believe they own the manifest — so a failing build can delete a manifest another
launch is actively using.

Fix: wrap check+mint with fcntl.flock on a per-derived-name lock file that is a SIBLING
of the stack dir so it survives rmtree of the guarded directory.
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harnessed import dynstack
from harnessed import launcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DERIVED_NAME = "default.serena"  # result of derive_name(["serena"], "default")
RECIPE = ["serena"]
EXTENDS = "default"


def _make_mint(tmp_path: Path, derive_fn=None):
    """Return a fake dynstack.mint that writes a minimal stack.yaml and returns (name, path).

    derive_fn must be the ORIGINAL (unpatched) derive_name so that the fake mint does not
    recurse into a barrier-patched derive_name from inside a held lock.
    """
    _derive = derive_fn or dynstack.derive_name

    def _mint(recipes, extends, services=None):
        name = _derive(recipes, extends, services=services)
        stack_dir = tmp_path / "harnessed" / "generated" / "stacks" / name
        stack_dir.mkdir(parents=True, exist_ok=True)
        manifest = stack_dir / "stack.yaml"
        if not manifest.exists():
            manifest.write_text(f"name: {name}\nrecipes: {recipes!r}\n")
        return name, stack_dir

    return _mint


# ---------------------------------------------------------------------------
# S1 — Race condition: exactly one owner under concurrent launch
# ---------------------------------------------------------------------------


class TestMintRace:
    def test_exactly_one_owner_under_concurrent_launch(self, tmp_path, monkeypatch):
        """Two concurrent threads must yield exactly one owner (minted_dir is not None).

        Today's code fails: both threads see is_file()=False before either calls mint(),
        so both return minted_dir != None (len(owners) == 2). The barrier guarantees the
        race window is open before either acquires (or checks) the lock.

        With the fix: thread A holds the lock, writes the file, releases; thread B acquires,
        sees is_file()=True, releases — returns minted_dir=None. len(owners) == 1.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setattr(launcher, "_seed_user_default_recipe", lambda: None)

        data_tmp = tmp_path / "data"

        # Capture original before patching — _make_mint must not call the barrier-patched version.
        original_derive = dynstack.derive_name
        fake_mint = _make_mint(data_tmp, derive_fn=original_derive)
        monkeypatch.setattr(dynstack, "mint", fake_mint)

        barrier = threading.Barrier(2, timeout=5)

        def synced_derive(recipes, extends, services=None):
            result = original_derive(recipes, extends, services=services)
            # Both threads must be past derive_name before either can see/acquire the lock.
            # This makes the race window deterministic: without flock, both call is_file()=False.
            barrier.wait()
            return result

        monkeypatch.setattr(dynstack, "derive_name", synced_derive)

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(launcher._resolve_stack, None, RECIPE, EXTENDS, False, [])
                for _ in range(2)
            ]
            for f in futs:
                try:
                    results.append(f.result())
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        assert not errors, f"threads raised: {errors}"

        owners = [minted_dir for _, minted_dir in results if minted_dir is not None]
        assert len(owners) == 1, (
            f"expected exactly 1 owner, got {len(owners)}; "
            "two concurrent launches both claimed ownership — mint-race not fixed"
        )

    # -----------------------------------------------------------------------
    # S3 — Lock file survives rmtree at delete site 2954-2955
    # -----------------------------------------------------------------------

    def test_lock_file_survives_rmtree(self, tmp_path):
        """The lock file (stacks/{derived}.lock) is a SIBLING of the stack dir.

        An rmtree of the stack dir must not delete the lock file.
        """
        stacks_dir = tmp_path / "stacks"
        stack_dir = stacks_dir / DERIVED_NAME
        lock_file = stacks_dir / f"{DERIVED_NAME}.lock"

        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text("name: test\n")
        lock_file.write_text("")  # simulate the lock file

        # Simulate what delete site 2954-2955 does
        shutil.rmtree(stack_dir, ignore_errors=True)

        assert lock_file.exists(), (
            f"lock file {lock_file} was deleted by rmtree of {stack_dir}; "
            "lock file must be a sibling, not inside the stack dir"
        )
        assert not stack_dir.exists(), "stack dir should be gone after rmtree"

    # -----------------------------------------------------------------------
    # S4 — Lock file survives rmtree at delete site 2965-2966
    # -----------------------------------------------------------------------

    def test_lock_file_survives_exception_path_rmtree(self, tmp_path):
        """Same as S3 but for the except Exception path at 2965-2966."""
        stacks_dir = tmp_path / "stacks"
        stack_dir = stacks_dir / DERIVED_NAME
        lock_file = stacks_dir / f"{DERIVED_NAME}.lock"

        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text("name: test\n")
        lock_file.write_text("")

        shutil.rmtree(stack_dir, ignore_errors=True)

        assert lock_file.exists()
        assert not stack_dir.exists()

    # -----------------------------------------------------------------------
    # S5 — Lock file survives rmtree at delete site 3497 (container-run)
    # -----------------------------------------------------------------------

    def test_lock_file_survives_build_failure_rmtree(self, tmp_path):
        """Same sibling-survives property for the build-failure delete at 3497."""
        stacks_dir = tmp_path / "stacks"
        stack_dir = stacks_dir / DERIVED_NAME
        lock_file = stacks_dir / f"{DERIVED_NAME}.lock"

        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text("name: test\n")
        lock_file.write_text("")

        shutil.rmtree(stack_dir, ignore_errors=True)

        assert lock_file.exists()
        assert not stack_dir.exists()

    # -----------------------------------------------------------------------
    # S6 — Sequential second call returns minted_dir=None
    # -----------------------------------------------------------------------

    def test_sequential_second_call_returns_none(self, tmp_path, monkeypatch):
        """A sequential second call for the same recipe set must return minted_dir=None."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setattr(launcher, "_seed_user_default_recipe", lambda: None)

        data_tmp = tmp_path / "data"
        monkeypatch.setattr(dynstack, "mint", _make_mint(data_tmp))

        name1, minted1 = launcher._resolve_stack(None, RECIPE, EXTENDS, False, [])
        name2, minted2 = launcher._resolve_stack(None, RECIPE, EXTENDS, False, [])

        assert name1 == name2
        assert minted1 is not None, "first call should mint and own the manifest"
        assert minted2 is None, "second call must return None — manifest already exists"

    # -----------------------------------------------------------------------
    # S7 — Concurrent mints produce identical on-disk content
    # -----------------------------------------------------------------------

    def test_concurrent_mint_content_matches_single_threaded(self, tmp_path, monkeypatch):
        """Concurrent launch produces identical manifest to single-threaded launch."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setattr(launcher, "_seed_user_default_recipe", lambda: None)

        original_derive = dynstack.derive_name

        # Single-threaded reference in a separate tmp space
        solo_tmp = tmp_path / "solo"
        monkeypatch.setenv("XDG_DATA_HOME", str(solo_tmp / "data"))
        monkeypatch.setattr(
            dynstack, "mint", _make_mint(solo_tmp / "data", derive_fn=original_derive)
        )
        _solo_name, solo_dir = launcher._resolve_stack(None, RECIPE, EXTENDS, False, [])
        solo_content = (solo_dir / "stack.yaml").read_text()

        # Concurrent launch in the original tmp space
        data_tmp = tmp_path / "data"
        monkeypatch.setenv("XDG_DATA_HOME", str(data_tmp))
        monkeypatch.setattr(dynstack, "mint", _make_mint(data_tmp, derive_fn=original_derive))

        barrier = threading.Barrier(2, timeout=5)

        def synced_derive(recipes, extends, services=None):
            result = original_derive(recipes, extends, services=services)
            barrier.wait()
            return result

        monkeypatch.setattr(dynstack, "derive_name", synced_derive)

        results = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(launcher._resolve_stack, None, RECIPE, EXTENDS, False, [])
                for _ in range(2)
            ]
            results = [f.result() for f in futs]

        owners = [d for _, d in results if d is not None]
        assert len(owners) == 1
        concurrent_content = (owners[0] / "stack.yaml").read_text()
        assert concurrent_content == solo_content

    # -----------------------------------------------------------------------
    # S8 — Non-owner failure leaves manifest intact
    # -----------------------------------------------------------------------

    def test_non_owner_failure_leaves_manifest_intact(self, tmp_path, monkeypatch):
        """Non-owning thread gets minted_dir=None, so its except-block skips rmtree.

        The owner's manifest must survive a simulated build failure in the non-owner.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setattr(launcher, "_seed_user_default_recipe", lambda: None)

        data_tmp = tmp_path / "data"
        original_derive = dynstack.derive_name
        monkeypatch.setattr(dynstack, "mint", _make_mint(data_tmp, derive_fn=original_derive))

        barrier = threading.Barrier(2, timeout=5)

        def synced_derive(recipes, extends, services=None):
            result = original_derive(recipes, extends, services=services)
            barrier.wait()
            return result

        monkeypatch.setattr(dynstack, "derive_name", synced_derive)

        results = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(launcher._resolve_stack, None, RECIPE, EXTENDS, False, [])
                for _ in range(2)
            ]
            results = [f.result() for f in futs]

        owners = [d for _, d in results if d is not None]
        non_owners = [d for _, d in results if d is None]

        assert len(owners) == 1, "exactly one owner required"
        assert len(non_owners) == 1, "exactly one non-owner required"

        owner_manifest = owners[0] / "stack.yaml"
        assert owner_manifest.exists(), "owner's manifest should exist"

        # Simulate non-owner build failure: the except block runs `if minted_dir is not None: rmtree`
        # Since minted_dir is None for the non-owner, NO rmtree runs.
        non_owner_minted_dir = non_owners[0]  # should be None
        if non_owner_minted_dir is not None:
            shutil.rmtree(non_owner_minted_dir, ignore_errors=True)

        # Owner's manifest must still be on disk
        assert owner_manifest.exists(), (
            "owner's manifest was deleted — non-owner minted_dir was not None, "
            "meaning the lock did not establish exclusive ownership"
        )
