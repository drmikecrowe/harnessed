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


_BARE_AND_QUOTED = '''\
# @generated

[[tools."npm:ccstatusline"]]
version = "2.2.27"
backend = "npm:ccstatusline"

[[tools.pulumi]]
version = "3.255.0"
backend = "pulumi"

[tools.pulumi."platforms.linux-x64"]
checksum = "sha256:pulumichecksum"
url = "https://example/pulumi"
'''


class TestBareToolKeys:
    """mise writes `[[tools.pulumi]]` — BARE, no quotes — for a registered tool.

    Raised in review of PR #341 and reproduced against real `mise lock` output: the first pattern
    required a quoted key, so `pulumi` and all seven of its platform checksums were DROPPED from
    the merge. The merged lockfile would then omit the very tool it claims to verify, and mise
    would install it unverified while every test here still passed.

    `pulumi@3.255.0` is in the catalog today, so this was live, not theoretical — and it is a
    fail-open inside the security mechanism itself, which is the worst place for one.
    """

    def test_a_bare_key_is_captured(self, tmp_path):
        blocks = read_lock(_write(tmp_path, "r", _BARE_AND_QUOTED))
        assert "pulumi" in blocks

    def test_its_checksum_survives(self, tmp_path):
        blocks = read_lock(_write(tmp_path, "r", _BARE_AND_QUOTED))
        assert "sha256:pulumichecksum" in blocks["pulumi"]

    def test_bare_and_quoted_keys_coexist(self, tmp_path):
        assert set(read_lock(_write(tmp_path, "r", _BARE_AND_QUOTED))) == {
            "npm:ccstatusline", "pulumi"}

    def test_a_bare_key_merges_and_stays_valid_TOML(self, tmp_path):
        merged = merge_locks({"a": _write(tmp_path, "a", _BARE_AND_QUOTED)})
        parsed = tomllib.loads(merged)
        assert parsed["tools"]["pulumi"][0]["platforms.linux-x64"]["checksum"] == "sha256:pulumichecksum"

    def test_a_bare_key_conflict_still_fails_closed(self, tmp_path):
        other = _BARE_AND_QUOTED.replace("sha256:pulumichecksum", "sha256:different")
        with pytest.raises(ToolLockError, match="different content"):
            merge_locks({
                "a": _write(tmp_path, "a", _BARE_AND_QUOTED),
                "b": _write(tmp_path, "b", other),
            })


class TestNonToolSections:
    """A top-level table that is not a tool must not be swallowed into the preceding tool's block.

    Raised in the same review. Swallowed, it would be duplicated once per recipe that ships one and
    the merged file would contain two copies of the same top-level table — invalid TOML, which
    fails at install time rather than here. I found no such table in real `mise lock` output today,
    so this is defence against a format that is mise's to change, handled by the same rule as
    tools: identical merges once, differing fails closed.
    """

    AUX = _BARE_AND_QUOTED + '\n[some-future-table]\nkey = "value"\n'

    def test_it_is_its_own_block_not_part_of_the_tool_above_it(self, tmp_path):
        blocks = read_lock(_write(tmp_path, "r", self.AUX))
        assert "some-future-table" in blocks
        assert "some-future-table" not in blocks["pulumi"]

    def test_two_recipes_shipping_an_IDENTICAL_aux_table_merge_to_one(self, tmp_path):
        merged = merge_locks({
            "a": _write(tmp_path, "a", self.AUX),
            "b": _write(tmp_path, "b", self.AUX),
        })
        assert merged.count("[some-future-table]") == 1
        tomllib.loads(merged)  # must still parse — a duplicate table would not

    def test_two_recipes_DISAGREEING_about_an_aux_table_fail_closed(self, tmp_path):
        other = self.AUX.replace('key = "value"', 'key = "other"')
        with pytest.raises(ToolLockError, match="different content"):
            merge_locks({
                "a": _write(tmp_path, "a", self.AUX),
                "b": _write(tmp_path, "b", other),
            })


class TestRootLevelAssignments:
    """Content before the first section header — TOML's root document.

    Raised in review of PR #341. `current` stays None until a section starts, so a root assignment
    was DROPPED: it parses fine, contributes to the file's meaning, and vanished from the merge.

    Not reproduced against mise today — real `mise lock` output has only a comment preamble, and
    this says so rather than dressing a latent hole as a live one. It matters because the format is
    mise's to change: the day it adds `lockfile_version`, a silently-dropped root key turns every
    merged lockfile into something mise may reject or, worse, read differently than intended.

    Root assignments must also come FIRST in the output — TOML puts them before any table.
    """

    ROOT = 'lockfile_version = 1\n\n' + _BARE_AND_QUOTED

    def test_a_root_assignment_survives_the_merge(self, tmp_path):
        merged = merge_locks({"a": _write(tmp_path, "a", self.ROOT)})
        assert tomllib.loads(merged)["lockfile_version"] == 1

    def test_it_is_emitted_before_any_table(self, tmp_path):
        """A root key after a table belongs to that table, not the document — the file would parse
        and mean something else entirely."""
        merged = merge_locks({"a": _write(tmp_path, "a", self.ROOT)})
        assert merged.index("lockfile_version") < merged.index("[[tools")

    def test_two_recipes_agreeing_merge_to_one(self, tmp_path):
        merged = merge_locks({
            "a": _write(tmp_path, "a", self.ROOT),
            "b": _write(tmp_path, "b", self.ROOT),
        })
        assert merged.count("lockfile_version") == 1
        assert tomllib.loads(merged)["lockfile_version"] == 1

    def test_two_recipes_DISAGREEING_fail_closed(self, tmp_path):
        with pytest.raises(ToolLockError, match="different content"):
            merge_locks({
                "a": _write(tmp_path, "a", self.ROOT),
                "b": _write(tmp_path, "b", self.ROOT.replace("= 1", "= 2")),
            })

    def test_a_comment_only_preamble_is_not_carried_through(self, tmp_path):
        """mise's own `# @generated by mise lock` header is not content to merge — this file writes
        its own, and copying N recipes' headers in would be noise claiming several origins."""
        merged = merge_locks({"a": _write(tmp_path, "a", _BARE_AND_QUOTED)})
        assert merged.count("@generated") == 1
        assert "auto-generated by `mise lock`" not in merged


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
