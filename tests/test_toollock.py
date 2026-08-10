"""Per-recipe `mise.lock` merge — the mechanism NC-7 depends on.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` NC-7 and Phase 2. tokensave's move onto
`tools:` is only allowed if its per-arch sha256 survives, and S1 established that the successor to
a hand-written sha256 is a committed lockfile.

The design decision (human, 2026-08-10) is one lockfile per RECIPE, merged at assembly. This file
tests the merge. Wiring it into the two install paths is the next unit — the merge is where all the
design risk sits, so it lands and gets reviewed on its own.

`test_real_mise_enforces_a_merged_lockfile` is the one that matters: everything else could pass
against a mechanism mise ignores.
"""

import os
import shutil
import subprocess
import tomllib

import pytest

from harnessed.toollock import ToolLockError, merge_locks, read_lock, recipe_lock_path

TOKENSAVE_SHA = "sha256:d35519fe698a24d2e2bb5622e94b3bdb4794dc1e36acffc980260b50afb40460"
TOKENSAVE_URL = (
    "https://github.com/aovestdipaperino/tokensave/releases/download/v7.0.2/"
    "tokensave-v7.0.2-x86_64-linux.tar.gz"
)


def _lock(spec: str, version: str = "7.0.2", checksum: str = TOKENSAVE_SHA,
          url: str = TOKENSAVE_URL) -> str:
    return (
        "# @generated\n\n"
        f'[[tools."{spec}"]]\n'
        f'version = "{version}"\n'
        f'backend = "{spec}"\n\n'
        f'[tools."{spec}"."platforms.linux-x64"]\n'
        f'checksum = "{checksum}"\n'
        f'url = "{url}"\n'
    )


def _write(tmp_path, name: str, body: str):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "mise.lock"
    p.write_text(body)
    return p


class TestReadingOneLockfile:
    def test_blocks_are_keyed_by_spec(self, tmp_path):
        blocks = read_lock(_write(tmp_path, "r", _lock("github:o/tokensave")))
        assert set(blocks) == {"github:o/tokensave"}

    def test_a_block_is_carried_VERBATIM(self, tmp_path):
        """Including fields this module knows nothing about. mise owns the format; re-serialising
        it here would silently drop whatever mise adds next."""
        body = _lock("github:o/tokensave").replace(
            'url = "', 'some_future_field = "unknown"\nurl = "', 1)
        blocks = read_lock(_write(tmp_path, "r", body))
        assert "some_future_field" in blocks["github:o/tokensave"]

    def test_two_tools_split_into_two_blocks(self, tmp_path):
        body = _lock("github:o/tokensave") + "\n" + _lock("npm:ccstatusline", version="2.2.27")
        assert set(read_lock(_write(tmp_path, "r", body))) == {"github:o/tokensave", "npm:ccstatusline"}

    def test_invalid_toml_is_rejected_rather_than_concatenated(self, tmp_path):
        """A broken lockfile merged into the stack's file would break every tool in it, not only
        its own. Caught at read time, naming the file."""
        with pytest.raises(ToolLockError, match="not valid TOML"):
            read_lock(_write(tmp_path, "r", '[[tools."x"]]\nversion = "unclosed\n'))


class TestMerging:
    def test_disjoint_recipes_union(self, tmp_path):
        merged = merge_locks({
            "tokensave": _write(tmp_path, "a", _lock("github:o/tokensave")),
            "ccstatusline": _write(tmp_path, "b", _lock("npm:ccstatusline", version="2.2.27")),
        })
        assert 'tools."github:o/tokensave"' in merged
        assert 'tools."npm:ccstatusline"' in merged

    def test_the_same_tool_locked_IDENTICALLY_by_two_recipes_appears_once(self, tmp_path):
        """Ordinary: the stack's tool set is deduped, so two recipes pinning `pulumi` is normal."""
        merged = merge_locks({
            "a": _write(tmp_path, "a", _lock("pulumi")),
            "b": _write(tmp_path, "b", _lock("pulumi")),
        })
        assert merged.count('[[tools."pulumi"]]') == 1

    def test_the_same_tool_locked_DIFFERENTLY_is_a_hard_error(self, tmp_path):
        """Fail closed. Two recipes claiming different bytes for one tool cannot both be satisfied,
        and picking a winner would let one recipe install what its own lockfile denies."""
        with pytest.raises(ToolLockError, match="different content"):
            merge_locks({
                "a": _write(tmp_path, "a", _lock("pulumi", checksum="sha256:" + "a" * 64)),
                "b": _write(tmp_path, "b", _lock("pulumi", checksum="sha256:" + "b" * 64)),
            })

    def test_the_error_names_BOTH_recipes(self, tmp_path):
        """One name sends the reader hunting for the other half of a disagreement."""
        with pytest.raises(ToolLockError) as exc:
            merge_locks({
                "alpha": _write(tmp_path, "a", _lock("pulumi", checksum="sha256:" + "a" * 64)),
                "beta": _write(tmp_path, "b", _lock("pulumi", checksum="sha256:" + "b" * 64)),
            })
        assert "alpha" in str(exc.value) and "beta" in str(exc.value)

    def test_no_sources_produces_no_file_content(self):
        """Every recipe shipping no lockfile must yield nothing to write — not an empty lockfile,
        which would claim to lock a tool set it says nothing about."""
        assert merge_locks({}) == ""

    def test_the_merge_is_order_independent(self, tmp_path):
        a = _write(tmp_path, "a", _lock("github:o/tokensave"))
        b = _write(tmp_path, "b", _lock("npm:ccstatusline", version="2.2.27"))
        assert merge_locks({"a": a, "b": b}) == merge_locks({"b": b, "a": a})

    def test_the_merged_output_is_VALID_TOML(self, tmp_path):
        """The property every formatting detail actually serves.

        Mutation testing found the joins, `rstrip` and `keepends` all unasserted — the tests
        checked that content was PRESENT, never that the result was a file mise can read. Any of
        those mutants produces a merged lockfile that is subtly malformed, which fails at install
        time in whatever way TOML happens to fail, far from here.
        """
        merged = merge_locks({
            "a": _write(tmp_path, "a", _lock("github:o/tokensave")),
            "b": _write(tmp_path, "b", _lock("npm:ccstatusline", version="2.2.27")),
        })
        parsed = tomllib.loads(merged)
        assert set(parsed["tools"]) == {"github:o/tokensave", "npm:ccstatusline"}

    def test_the_checksum_survives_the_merge_intact(self, tmp_path):
        """A lockfile that parses but loses the checksum would verify nothing while looking fine."""
        merged = merge_locks({"a": _write(tmp_path, "a", _lock("github:o/tokensave"))})
        # `[[tools."x"]]` is an array-of-tables, so a tool's entry is a LIST and its platform
        # tables nest inside the first element. Asserted at the real shape rather than the one I
        # assumed — the first version of this test indexed it as a dict and failed.
        entry = tomllib.loads(merged)["tools"]["github:o/tokensave"][0]
        assert entry["platforms.linux-x64"]["checksum"] == TOKENSAVE_SHA
        assert entry["platforms.linux-x64"]["url"] == TOKENSAVE_URL

    def test_a_single_tool_merge_is_valid_too(self, tmp_path):
        """N=1 is where a join-based builder differs from a loop, and every N>1 test still passes."""
        merged = merge_locks({"a": _write(tmp_path, "a", _lock("pulumi"))})
        assert tomllib.loads(merged)["tools"]["pulumi"]

    def test_the_output_says_not_to_edit_it(self, tmp_path):
        merged = merge_locks({"a": _write(tmp_path, "a", _lock("pulumi"))})
        assert "@generated" in merged and "never this file" in merged


class TestRecipeLockDiscovery:
    def test_a_recipe_without_a_lockfile_is_not_an_error(self, tmp_path):
        """No recipe ships one today. Absent means 'installs unverified, as now' — requiring one
        would break every stack at once and make adoption impossible."""
        (tmp_path / "r").mkdir()
        assert recipe_lock_path(tmp_path / "r") is None

    def test_a_recipe_with_one_is_found(self, tmp_path):
        p = _write(tmp_path, "r", _lock("pulumi"))
        assert recipe_lock_path(p.parent) == p


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("HARNESSED_PODMAN") != "1" or shutil.which("mise") is None,
    reason="live: needs the mise binary and network (set HARNESSED_PODMAN=1)",
)
def test_real_mise_enforces_a_merged_lockfile(tmp_path):
    """THE test. Everything above could pass against a mechanism mise ignores.

    Feeds a MERGED lockfile — this module's own output — to the real binary and asserts the install
    fails on a corrupted checksum. Measured facts this pins, each of which was a live hazard:
    the file must be named `mise.lock` (a `config.lock` beside the config is silently ignored, and
    install then exits 0), and enforcement is real rather than advisory.

    Deliberately asserts the FAILURE direction. A test that only proves a correct checksum installs
    cannot tell a working check from an absent one.
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text(
        '[tools]\n"github:aovestdipaperino/tokensave" = "7.0.2"\n'
    )
    corrupt = _write(tmp_path, "recipe", _lock(
        "github:aovestdipaperino/tokensave", checksum="sha256:" + "0" * 64))
    (cfg / "mise.lock").write_text(merge_locks({"tokensave": corrupt}))

    env = {
        "PATH": "/usr/bin:/bin:" + str(tmp_path),
        "HOME": str(tmp_path),
        "MISE_CONFIG_DIR": str(cfg),
        "MISE_DATA_DIR": str(tmp_path / "data"),
        "MISE_CACHE_DIR": str(tmp_path / "cache"),
        "MISE_GLOBAL_CONFIG_FILE": str(cfg / "config.toml"),
        "MISE_YES": "1",
    }
    mise = shutil.which("mise")
    assert mise is not None  # guarded by the skipif above; narrows for the type checker
    proc = subprocess.run(
        [mise, "install"], env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode != 0, (
        "mise accepted a corrupted checksum from the merged lockfile — the merge is decorative"
    )
    assert "hecksum" in (proc.stderr + proc.stdout)
