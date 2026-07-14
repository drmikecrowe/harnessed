"""Tests for _ensure_docs_wiki_clone (docs/ live-clone bootstrap run on every `harnessed build`).

Keyed to harnessed's OWN source checkout (paths.source_checkout), never the CWD.
"""

import subprocess

from harnessed import launcher


def _init_bare(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "-q", str(path)], check=True)
    return path


def _commit_file(bare_repo, tmp_path, name, filename, content):
    """Push one commit with a single file into a bare repo via a throwaway clone."""
    scratch = tmp_path / f"_scratch_{name}"
    subprocess.run(["git", "clone", "-q", str(bare_repo), str(scratch)], check=True)
    (scratch / filename).write_text(content)
    subprocess.run(["git", "-C", str(scratch), "add", filename], check=True)
    subprocess.run(
        ["git", "-C", str(scratch), "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        check=True,
    )
    subprocess.run(["git", "-C", str(scratch), "push", "-q", "origin", "HEAD:master"], check=True)
    subprocess.run(["git", "-C", str(bare_repo), "symbolic-ref", "HEAD", "refs/heads/master"], check=True)


def _setup_repo(monkeypatch, tmp_path, with_catalog=True, with_origin=True, name="repo"):
    """A harnessed source checkout (pyproject.toml + src/harnessed) with an origin + wiki.

    Pointed at via HARNESSED_DIR, so `paths.source_checkout()` finds it regardless of the CWD.
    """
    origin = _init_bare(tmp_path / f"{name}-origin.git")
    if with_origin:
        wiki = _init_bare(tmp_path / f"{name}-origin.wiki.git")
        _commit_file(wiki, tmp_path, f"wiki-{name}", "Home.md", "hello wiki\n")

    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "src" / "harnessed").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'harnessed'\n")
    if with_origin:
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(origin)], check=True)
    if with_catalog:
        (repo / "catalog").mkdir()
    monkeypatch.setenv("HARNESSED_DIR", str(repo))
    return repo


class TestEnsureDocsWikiClone:
    def test_clones_wiki_when_missing(self, monkeypatch, tmp_path):
        repo = _setup_repo(monkeypatch, tmp_path)

        launcher._ensure_docs_wiki_clone()

        docs_dir = repo / "docs"
        assert docs_dir.is_dir()
        assert (docs_dir / "Home.md").read_text() == "hello wiki\n"
        assert (docs_dir / ".git").is_dir(), "docs/ should be a plain clone, not a submodule gitlink"

    def test_existing_docs_dir_is_left_alone(self, monkeypatch, tmp_path):
        repo = _setup_repo(monkeypatch, tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "sentinel.md").write_text("do not touch\n")

        launcher._ensure_docs_wiki_clone()

        assert (repo / "docs" / "sentinel.md").read_text() == "do not touch\n"
        assert not (repo / "docs" / "Home.md").exists()

    def test_no_origin_remote_is_noop(self, monkeypatch, tmp_path):
        repo = _setup_repo(monkeypatch, tmp_path, with_origin=False)

        launcher._ensure_docs_wiki_clone()

        assert not (repo / "docs").exists()

    def test_not_a_source_checkout_is_noop(self, monkeypatch, tmp_path):
        """A wheel install (home is site-packages) → no wiki clone attempted."""
        installed = tmp_path / "site-packages" / "harnessed"
        (installed / "catalog").mkdir(parents=True)
        monkeypatch.setenv("HARNESSED_DIR", str(installed))

        launcher._ensure_docs_wiki_clone()

        assert not (installed / "docs").exists()

    def test_ignores_unrelated_repo_in_cwd(self, monkeypatch, tmp_path):
        """REGRESSION: standing in another project must not clone ITS wiki into ITS docs/.

        Keyed to the CWD, this helper read whatever repo you were standing in — it would resolve
        that project's `origin`, derive `<origin>.wiki.git`, and clone it into that project's docs/,
        purely because the directory happened to contain a `catalog/`.
        """
        _setup_repo(monkeypatch, tmp_path, name="harnessed_checkout")

        # An unrelated project that also has a catalog/ and its own origin + wiki.
        other = _init_bare(tmp_path / "other-origin.git")
        other_wiki = _init_bare(tmp_path / "other-origin.wiki.git")
        _commit_file(other_wiki, tmp_path, "otherwiki", "Home.md", "SHOULD NOT BE CLONED\n")
        victim = tmp_path / "someone_elses_project"
        victim.mkdir()
        subprocess.run(["git", "init", "-q", str(victim)], check=True)
        subprocess.run(["git", "-C", str(victim), "remote", "add", "origin", str(other)], check=True)
        (victim / "catalog").mkdir()
        monkeypatch.chdir(victim)

        launcher._ensure_docs_wiki_clone()

        assert not (victim / "docs").exists(), "must not clone a wiki into an unrelated project"
