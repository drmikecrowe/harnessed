"""`tools/pin-upgrade.sh`, the scheduled pin upgrade (GH-582), run against stubs.

The script's whole job is the sequence of `gh` calls it makes and the git state it leaves, so the
tests run the real script in a throwaway repository whose `origin` is a local bare repo, with stub
`gh` and `harnessed` programs first on PATH. Each stub appends one JSON array per call to a log;
the assertions read that log. Nothing here reaches GitHub or a registry.

Scenario ids (S1.1 ...) are the ones in spec-evidence/2026-10-12-GH-582/SPEC.md.
"""

import base64
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pin-upgrade.sh"
REPO = "octo/harnessed"

STUB_GH = textwrap.dedent('''\
    import json, os, pathlib, sys
    d = pathlib.Path(os.environ["STUB_DIR"])
    args = sys.argv[1:]
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write(json.dumps(["gh", *args]) + "\\n")

    def opt(name):
        return args[args.index(name) + 1] if name in args else None

    if args[:2] == ["api", "graphql"]:
        n = len(list(d.glob("graphql-*.json"))) + 1
        (d / f"graphql-{n}.json").write_text(pathlib.Path(opt("--input")).read_text())
        if (d / "fail-graphql").exists():
            print("GraphQL: expected head oid did not match", file=sys.stderr)
            sys.exit(1)
        if (d / "lose-graphql-response").exists():
            # The commit landed on the server, but the reply never arrived.
            (d / "branch-sha").write_text("c" * 40)
            print("connection reset by peer", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({"data": {"createCommitOnBranch": {"commit": {"oid": "c" * 40}}}}))
    elif args[:1] == ["api"] and "POST" in args and args[3].endswith("/git/refs"):
        # The ref now exists at the sha the script asked for, as GitHub would record it.
        (d / "branch-sha").write_text([a for a in args if a.startswith("sha=")][0][4:])
        print("{}")
    elif args[:1] == ["api"] and "-X" in args:
        print("{}")
    elif args[:1] == ["api"] and "/git/ref/heads/" in args[1]:
        if (d / "branch-sha").exists():
            print(json.dumps({"object": {"sha": (d / "branch-sha").read_text().strip()}}))
        else:
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            sys.exit(1)
    elif args[:2] == ["pr", "list"]:
        # open-prs / merged-prs / closed-prs each hold a JSON list of {"number": n}.
        def prs(name, state):
            f = d / name
            return [{**p, "state": state} for p in json.loads(f.read_text())] if f.exists() else []
        if opt("--state") == "open":
            print(json.dumps(prs("open-prs", "OPEN")))
        else:  # --state all
            # merged-later-prs appears from the second `--state all` query on: a PR merged by a
            # person while the run was busy in `harnessed update`.
            seen = d / "state-all-calls"
            n = int(seen.read_text()) + 1 if seen.exists() else 1
            seen.write_text(str(n))
            later = prs("merged-later-prs", "MERGED") if n > 1 else []
            print(json.dumps(prs("open-prs", "OPEN") + prs("merged-prs", "MERGED")
                             + prs("closed-prs", "CLOSED") + later))
    elif args[:2] == ["workflow", "run"] and (d / "fail-workflow-run").exists():
        print("HTTP 500", file=sys.stderr)
        sys.exit(1)
    ''')

STUB_HARNESSED = textwrap.dedent('''\
    import json, os, pathlib, shutil, subprocess, sys
    d = pathlib.Path(os.environ["STUB_DIR"])
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    sys.stdin.read()
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write(json.dumps(["harnessed", *sys.argv[1:], head]) + "\\n")
    writes = d / "writes"
    if writes.is_dir():
        for src in writes.rglob("*"):
            if src.is_file():
                dst = pathlib.Path(src.relative_to(writes))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    deletes = d / "deletes"
    if deletes.exists():
        for line in deletes.read_text().splitlines():
            if line.strip():
                pathlib.Path(line.strip()).unlink()
    ''')


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Run:
    """One prepared repository plus its stubs. `run()` executes the script once."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        self.stub = tmp_path / "stub"
        self.bin = tmp_path / "bin"
        self.log = tmp_path / "stub.log"
        for p in (self.stub, self.bin, self.work):
            p.mkdir()
        _git(tmp_path, "init", "--bare", "-b", "main", str(self.origin))
        _git(self.work, "init", "-b", "main")
        (self.work / "catalog" / "recipes" / "pulumi").mkdir(parents=True)
        (self.work / "catalog" / "recipes" / "pulumi" / "recipe.yaml").write_text(
            "name: pulumi\ntools:\n  - pulumi@3.266.0\n"
        )
        (self.work / "mise.toml").write_text('[tools]\njq = "1.8.2"\n')
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-m", "init")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        _git(self.work, "push", "-q", "origin", "main")
        self.main = _git(self.work, "rev-parse", "HEAD")
        self.branch = f"upgrade-{_today()}"
        for name, body in (("gh", STUB_GH), ("harnessed", STUB_HARNESSED)):
            exe = self.bin / name
            exe.write_text(f"#!{sys.executable}\n{body}")
            exe.chmod(0o755)

    def write(self, rel, text):
        p = self.stub / "writes" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def remote_branch(self):
        """Put upgrade-<date> on origin one commit after main; return its sha (B)."""
        _git(self.work, "switch", "-q", "-c", self.branch)
        (self.work / "catalog" / "recipes" / "pulumi" / "recipe.yaml").write_text(
            "name: pulumi\ntools:\n  - pulumi@3.267.0\n"
        )
        _git(self.work, "commit", "-qam", "first upgrade")
        sha = _git(self.work, "rev-parse", "HEAD")
        _git(self.work, "push", "-q", "origin", self.branch)
        _git(self.work, "switch", "-q", "main")
        _git(self.work, "branch", "-q", "-D", self.branch)
        (self.stub / "branch-sha").write_text(sha)
        return sha

    def run(self):
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(self.stub),
            "STUB_LOG": str(self.log),
            "GITHUB_REPOSITORY": REPO,
            "HARNESSED_CMD": "harnessed",
        }
        # stdin is a pipe whose write end stays open for the whole run: a step that reads it (the
        # stub `harnessed` reads to the end) blocks until the timeout instead of seeing EOF. Only
        # the script's own `< /dev/null` lets the run finish (S5.4).
        rd, wr = os.pipe()
        try:
            self.result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=self.work, env=env, stdin=rd,
                capture_output=True, text=True, timeout=60,
            )
        finally:
            os.close(rd)
            os.close(wr)
        self.out = self.result.stdout + self.result.stderr
        return self.result

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def gh(self, *prefix):
        return [c for c in self.calls() if c[0] == "gh" and c[1:1 + len(prefix)] == list(prefix)]

    def graphql(self, n=1):
        return json.loads((self.stub / f"graphql-{n}.json").read_text())["variables"]["input"]

    def origin_refs(self):
        return _git(self.tmp, "--git-dir", str(self.origin), "for-each-ref", "--format=%(refname) %(objectname)")


@pytest.fixture
def r(tmp_path):
    return Run(tmp_path)


def _ref_posts(r):
    return [c for c in r.gh("api") if "POST" in c]


class TestNothingEligible:
    """S1: AC-1."""

    def test_s1_1_no_change_exits_clean_and_calls_nothing(self, r):
        assert r.run().returncode == 0, r.out
        assert "no pin changed; nothing to do" in r.out
        assert r.gh("api", "graphql") == []
        assert _ref_posts(r) == []
        assert r.gh("pr", "create") == []
        assert r.gh("workflow", "run") == []

    def test_s1_3_no_branch_reaches_origin(self, r):
        r.run()
        assert r.branch not in r.origin_refs()


class TestOneSignedCommitPR:
    """S2: AC-2."""

    def test_s2_1_ref_then_commit_then_pr_in_order(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "name: pulumi\ntools:\n  - pulumi@3.267.0\n")
        assert r.run().returncode == 0, r.out
        kinds = []
        for c in r.calls():
            if c[0] != "gh":
                continue
            if c[1] == "api" and "POST" in c:
                kinds.append("ref")
            elif c[1:3] == ["api", "graphql"]:
                kinds.append("graphql")
            elif c[1:3] == ["pr", "create"]:
                kinds.append("pr")
        assert kinds == ["ref", "graphql", "pr"]
        (post,) = _ref_posts(r)
        assert f"repos/{REPO}/git/refs" in post
        assert f"ref=refs/heads/{r.branch}" in post and f"sha={r.main}" in post
        (pr,) = r.gh("pr", "create")
        assert pr[pr.index("--base") + 1] == "main"
        assert pr[pr.index("--head") + 1] == r.branch

    def test_s2_2_the_commit_carries_the_staged_file(self, r):
        body = "name: pulumi\ntools:\n  - pulumi@3.267.0\n"
        r.write("catalog/recipes/pulumi/recipe.yaml", body)
        r.run()
        inp = r.graphql()
        assert inp["expectedHeadOid"] == r.main
        assert inp["branch"] == {"repositoryNameWithOwner": REPO, "branchName": r.branch}
        (add,) = inp["fileChanges"]["additions"]
        assert add["path"] == "catalog/recipes/pulumi/recipe.yaml"
        assert base64.b64decode(add["contents"]).decode() == body

    def test_s2_3_nothing_is_pushed_with_git(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.run()
        assert r.branch not in r.origin_refs()
        text = SCRIPT.read_text()
        assert "git push" not in text and "git commit" not in text

    def test_a_large_change_is_not_limited_by_argument_length(self, r):
        """PR #593 review: Linux caps one argv string at 128 KiB; 300 KB of contents (400 KB
        as base64) must still reach the API commit intact."""
        big = "".join(f"line {i:06d} {'x' * 50}\n" for i in range(5000))
        r.write("catalog/recipes/pulumi/mise.lock", big)
        assert r.run().returncode == 0, r.out
        (add,) = r.graphql()["fileChanges"]["additions"]
        assert base64.b64decode(add["contents"]).decode() == big

    def test_s2_4_two_files_one_commit(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        r.run()
        assert len(r.gh("api", "graphql")) == 1
        paths = {a["path"] for a in r.graphql()["fileChanges"]["additions"]}
        assert paths == {"catalog/recipes/pulumi/recipe.yaml", "mise.toml"}

    def test_s2_5_a_deletion_is_refused(self, r):
        (r.stub / "deletes").write_text("catalog/recipes/pulumi/recipe.yaml\n")
        assert r.run().returncode == 1
        assert "pin-upgrade: refusing a deletion: catalog/recipes/pulumi/recipe.yaml" in r.out
        assert r.gh("api", "graphql") == []


    def test_every_refused_deletion_is_named(self, r):
        """PR #593 review: the refusal names each deleted path, not only the first."""
        (r.stub / "deletes").write_text("catalog/recipes/pulumi/recipe.yaml\nmise.toml\n")
        assert r.run().returncode == 1
        assert "pin-upgrade: refusing a deletion: catalog/recipes/pulumi/recipe.yaml" in r.out
        assert "pin-upgrade: refusing a deletion: mise.toml" in r.out


    def test_a_tracked_file_changed_outside_the_pin_paths_fails_the_run(self, r):
        """PR #593 review: committing part of `update`'s output is worse than failing."""
        (r.work / "uv.lock").write_text("version = 1\n")
        _git(r.work, "add", "uv.lock")
        _git(r.work, "commit", "-qm", "lock")
        _git(r.work, "push", "-q", "origin", "main")
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.write("uv.lock", "version = 2\n")
        assert r.run().returncode == 1
        assert "pin-upgrade: harnessed update changed files outside catalog/ and mise.toml:" in r.out
        assert "uv.lock" in r.out
        assert r.gh("api", "graphql") == []


class TestSameDayRerun:
    """S3: AC-3, and Decide 5 B."""

    def test_s3_1_rerun_stacks_on_the_branch_head(self, r):
        b = r.remote_branch()
        (r.stub / "open-prs").write_text('[{"number":7}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        (h,) = [c for c in r.calls() if c[0] == "harnessed"]
        assert h[-1] == b, "harnessed ran before the branch was checked out"
        assert r.graphql()["expectedHeadOid"] == b
        assert _ref_posts(r) == []
        assert r.gh("pr", "create") == []

    def test_s3_2_rerun_with_nothing_new_touches_nothing(self, r):
        r.remote_branch()
        (r.stub / "open-prs").write_text('[{"number":7}]')
        assert r.run().returncode == 0, r.out
        assert "no pin changed; nothing to do" in r.out
        assert r.gh("api", "graphql") == [] and r.gh("pr", "create") == []
        assert r.gh("workflow", "run") == []

    def test_s3_3_the_earlier_commit_is_not_rewritten(self, r):
        b = r.remote_branch()
        (r.stub / "open-prs").write_text('[{"number":7}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        r.run()
        assert f"refs/heads/{r.branch} {b}" in r.origin_refs()

    def test_s3_4_branch_without_open_pr_gets_one(self, r):
        b = r.remote_branch()
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        assert r.graphql()["expectedHeadOid"] == b
        assert _ref_posts(r) == []
        assert len(r.gh("pr", "create")) == 1

    @pytest.mark.parametrize("done", ["merged-prs", "closed-prs"])
    def test_s3_5_a_merged_or_closed_pr_today_skips_the_run(self, r, done):
        """Decide 5 B, widened after PR #593 review: a closed PR is someone's decision about
        today's bumps too, and must not be reopened or answered with a second PR."""
        (r.stub / done).write_text('[{"number":6}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        assert f"{r.branch} already closed or merged today; the next run picks up new bumps" in r.out
        assert [c for c in r.calls() if c[0] == "harnessed"] == []
        assert r.gh("api", "graphql") == [] and r.gh("pr", "create") == []
        assert r.gh("workflow", "run") == []

    def test_a_pr_finished_during_the_update_stops_the_commit(self, r):
        """PR #593 review: re-check just before the commit, so a merge made while
        `harnessed update` ran does not get a second same-date PR."""
        (r.stub / "merged-later-prs").write_text('[{"number":6}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        assert f"{r.branch} already closed or merged today" in r.out
        assert [c for c in r.calls() if c[0] == "harnessed"], "the first check passed"
        assert r.gh("api", "graphql") == [] and _ref_posts(r) == []
        assert r.gh("pr", "create") == []

    def test_an_open_pr_is_not_a_finished_one(self, r):
        r.remote_branch()
        (r.stub / "open-prs").write_text('[{"number":7}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        assert len(r.gh("api", "graphql")) == 1


class TestFailedCommit:
    """PR #593 review: a failed API commit must not leave a ref this run created."""

    def _deletes(self, r):
        return [c for c in r.gh("api") if "DELETE" in c]

    def test_a_ref_this_run_created_is_removed(self, r):
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        (r.stub / "fail-graphql").write_text("")
        assert r.run().returncode != 0
        assert self._deletes(r) == [["gh", "api", "-X", "DELETE", f"repos/{REPO}/git/refs/heads/{r.branch}"]]
        assert r.gh("pr", "create") == []

    def test_a_commit_that_landed_without_a_reply_is_kept(self, r):
        """PR #593 review: the ref moved off the sha we created it at, so the commit is real."""
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        (r.stub / "lose-graphql-response").write_text("")
        assert r.run().returncode != 0
        assert self._deletes(r) == []

    def test_a_branch_that_already_existed_is_kept(self, r):
        r.remote_branch()
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        (r.stub / "fail-graphql").write_text("")
        assert r.run().returncode != 0
        assert self._deletes(r) == []

    def test_a_good_commit_keeps_its_ref(self, r):
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        assert r.run().returncode == 0, r.out
        assert self._deletes(r) == []


class TestChecksStart:
    """S4: AC-4."""

    def test_s4_1_test_yml_is_dispatched_after_the_commit(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.run()
        calls = [c for c in r.calls() if c[0] == "gh"]
        gql = calls.index(r.gh("api", "graphql")[0])
        runs = r.gh("workflow", "run")
        assert runs == [["gh", "workflow", "run", "test.yml", "--repo", REPO, "--ref", r.branch]]
        assert calls.index(runs[0]) > gql

    def test_s4_2_a_live_trigger_file_also_dispatches_live(self, r):
        r.write("catalog/base/Dockerfile.harnessed-base", "FROM scratch\n")
        assert r.run().returncode == 0, r.out
        files = {c[3] for c in r.gh("workflow", "run")}
        assert files == {"test.yml", "live.yml"}
        assert all(c[c.index("--ref") + 1] == r.branch for c in r.gh("workflow", "run"))

    def test_s4_4_a_rerun_dispatches_again(self, r):
        r.remote_branch()
        (r.stub / "open-prs").write_text('[{"number":7}]')
        r.write("mise.toml", '[tools]\njq = "1.8.3"\n')
        r.run()
        assert [c[3] for c in r.gh("workflow", "run")] == ["test.yml"]

    def test_s4_5_a_failed_dispatch_fails_the_run(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        (r.stub / "fail-workflow-run").write_text("")
        assert r.run().returncode != 0
        assert "gh workflow run" in r.out


class TestNoInput:
    """S5.4: AC-5 and AC-6 (S6.3)."""

    def test_s5_4_harnessed_gets_exactly_these_args_and_no_stdin(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.run()
        (h,) = [c for c in r.calls() if c[0] == "harnessed"]
        assert h[1:-1] == ["update", "--yes", "--no-rebuild"]


class TestFeatTitle:
    """S7.1: AC-7."""

    def test_s7_1_commit_headline_and_pr_title(self, r):
        r.write("catalog/recipes/pulumi/recipe.yaml", "x: 1\n")
        r.run()
        want = f"feat(catalog): upgrade pins {_today()}"
        assert r.graphql()["message"]["headline"] == want
        (pr,) = r.gh("pr", "create")
        assert pr[pr.index("--title") + 1] == want
