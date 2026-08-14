"""bd harnessed-1t4.1 — hatago comes from a published npm release, never from source.

The stack `hatago: {repo, ref}` override shallow-cloned a fork and built it inside the DERIVED
image: 410 packages resolved for one layer, on every build, in addition to the hatago the base image
already installs. The fork is published (@drmikecrowe/hatago-mcp-hub), so the whole clone/build path
goes and the base pin simply moves to the fork.

Verified 2026-07-23 before making the switch: the fork's `feat/per-server-tool-filtering` branch is
0 commits AHEAD of main / 17 behind, and main ships 0.1.2 — the per-server tool-filtering work the
override existed for is in the published package. The bin map ({hatago, hatago-mcp-hub}) is
unchanged from upstream 0.0.16, so nothing that invokes the binary by name has to move.

These tests are about the shipped build inputs, not about emit internals.
"""
from __future__ import annotations

import re

import pytest

from harnessed import paths
from harnessed.emit import write_derived_dockerfile
from harnessed.schema import SchemaError, load_stack

HATAGO_PKG = "@drmikecrowe/hatago-mcp-hub"


def _base_dockerfile() -> str:
    return (paths.harnessed_home() / "catalog" / "base" / "Dockerfile.harnessed-base").read_text(
        encoding="utf-8"
    )


class TestBaseImageOwnsTheOnlyHatagoInstall:
    def test_base_installs_the_published_fork_at_an_exact_version(self):
        body = _base_dockerfile()
        match = re.search(rf'{re.escape(HATAGO_PKG)}@(\d+\.\d+\.\d+)', body)
        assert match, f"base image must install {HATAGO_PKG} at a pinned version"

    def test_base_no_longer_installs_the_unmaintained_upstream(self):
        # Upstream @himorishige/hatago-mcp-hub last published 2025-09-14 and is behind the fork.
        assert "@himorishige/hatago-mcp-hub" not in _base_dockerfile()

    def test_nothing_in_the_catalog_builds_hatago_from_source(self):
        catalog = paths.harnessed_home() / "catalog"
        offenders = [
            p.relative_to(catalog).as_posix()
            for p in catalog.rglob("*")
            if p.is_file()
            and p.suffix in ("", ".sh")
            and "hatago-mcp-hub.git" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        assert offenders == []


class TestDerivedImageCarriesNoHatagoLayer:
    def test_derived_dockerfile_never_clones_or_builds_hatago(self, tmp_path):
        body = write_derived_dockerfile(tmp_path, "s", "claude", []).read_text(encoding="utf-8")
        assert "hatago-src" not in body
        assert "pnpm add -g file:" not in body
        assert "git clone" not in body

    def test_write_derived_dockerfile_no_longer_takes_a_hatago_override(self, tmp_path):
        # The kwarg is gone rather than accepted-and-ignored: a stale caller must fail loudly.
        with pytest.raises(TypeError):
            write_derived_dockerfile(
                tmp_path, "s", "claude", [], hatago={"repo": "github:o/r", "ref": "x"}  # type: ignore[call-arg]  # intentional stale kwarg to verify TypeError
            )


class TestLegacyOverrideFailsLoudly:
    """A stack.yaml still carrying `hatago:` must not be silently ignored (D-14 tolerates unknown
    fields, which would turn a removed feature into a no-op the author cannot see)."""

    def _stack(self, tmp_path, extra: str):
        d = tmp_path / "stacks" / "s"
        d.mkdir(parents=True)
        (d / "stack.yaml").write_text(
            f"name: s\nrecipes: []\n{extra}", encoding="utf-8"
        )
        return d

    def test_legacy_hatago_block_is_rejected_with_a_migration_message(self, tmp_path):
        manifest = self._stack(
            tmp_path, 'hatago:\n  repo: "github:drmikecrowe/hatago-mcp-hub"\n  ref: "feat/x"\n'
        )
        with pytest.raises(SchemaError) as exc:
            load_stack(manifest)
        message = str(exc.value)
        assert "hatago" in message
        assert HATAGO_PKG in message  # tells the author where hatago comes from now

    def test_a_stack_without_the_block_still_loads(self, tmp_path):
        assert load_stack(self._stack(tmp_path, "")).name == "s"
