"""Tests for _ensure_docs_wiki_clone (docs/ live-clone bootstrap run on every `harnessed build`)."""

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


def _setup_repo(tmp_path, with_catalog=True, with_origin=True):
    origin = _init_bare(tmp_path / "origin.git")
    if with_origin:
        wiki = _init_bare(tmp_path / "origin.wiki.git")
        _commit_file(wiki, tmp_path, "wiki", "Home.md", "hello wiki\n")

    cwd = tmp_path / "repo"
    cwd.mkdir()
    subprocess.run(["git", "init", "-q", str(cwd)], check=True)
    if with_origin:
        subprocess.run(["git", "-C", str(cwd), "remote", "add", "origin", str(origin)], check=True)
    if with_catalog:
        (cwd / "catalog").mkdir()
    return cwd


class TestEnsureDocsWikiClone:
    def test_no_catalog_dir_is_noop(self, monkeypatch, tmp_path):
        cwd = _setup_repo(tmp_path, with_catalog=False)
        monkeypatch.chdir(cwd)

        launcher._ensure_docs_wiki_clone()

        assert not (cwd / "docs").exists()

    def test_clones_wiki_when_missing(self, monkeypatch, tmp_path):
        cwd = _setup_repo(tmp_path)
        monkeypatch.chdir(cwd)

        launcher._ensure_docs_wiki_clone()

        docs_dir = cwd / "docs"
        assert docs_dir.is_dir()
        assert (docs_dir / "Home.md").read_text() == "hello wiki\n"
        assert (docs_dir / ".git").is_dir(), "docs/ should be a plain clone, not a submodule gitlink"

    def test_existing_docs_dir_is_left_alone(self, monkeypatch, tmp_path):
        cwd = _setup_repo(tmp_path)
        (cwd / "docs").mkdir()
        (cwd / "docs" / "sentinel.md").write_text("do not touch\n")
        monkeypatch.chdir(cwd)

        launcher._ensure_docs_wiki_clone()

        assert (cwd / "docs" / "sentinel.md").read_text() == "do not touch\n"
        assert not (cwd / "docs" / "Home.md").exists()

    def test_no_origin_remote_is_noop(self, monkeypatch, tmp_path):
        cwd = _setup_repo(tmp_path, with_origin=False)
        (cwd / "catalog").mkdir(exist_ok=True)
        monkeypatch.chdir(cwd)

        launcher._ensure_docs_wiki_clone()

        assert not (cwd / "docs").exists()
