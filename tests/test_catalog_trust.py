"""`harnessed catalog trust` and `untrust` (HF-20261122-private-catalogs-add-two, AC-3 and AC-13)."""

from __future__ import annotations

import pytest
from catalog_env import install, project
from typer.testing import CliRunner

from harnessed import catalogsources, launcher, paths

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(launcher, "_broker_report", lambda *_: None)
    yield e
    catalogsources.reset()


def _record_bytes() -> bytes | None:
    f = catalogsources.trust_file()
    return f.read_bytes() if f.exists() else None


def _list(proj) -> str:
    catalogsources.reset()
    return runner.invoke(launcher.app, ["list", "--project", str(proj)]).output


class TestTrust:
    def test_s3_1_records_and_silences_the_warning(self, env, tmp_path):
        proj = project(tmp_path)
        result = runner.invoke(launcher.app, ["catalog", "trust", str(proj)])
        cat = str((proj / ".harnessed" / "catalog").resolve())
        assert result.exit_code == 0
        assert cat in result.output
        assert catalogsources.trusted_paths() == [cat]
        assert "harnessed catalog trust" not in _list(proj)

    def test_s3_2_no_argument_uses_the_cwd(self, env, tmp_path, monkeypatch):
        proj = project(tmp_path)
        monkeypatch.chdir(proj)
        assert runner.invoke(launcher.app, ["catalog", "trust"]).exit_code == 0
        assert catalogsources.trusted_paths() == [str((proj / ".harnessed" / "catalog").resolve())]

    def test_s3_3_trust_belongs_to_the_path(self, env, tmp_path):
        proj = project(tmp_path)
        catalogsources.trust(proj)
        moved = tmp_path / "moved"
        proj.rename(moved)
        out = _list(moved)
        assert str((moved / ".harnessed" / "catalog").resolve()) in out
        assert "harnessed catalog trust" in out

    def test_s3_4_nothing_to_trust(self, env, tmp_path):
        empty = tmp_path / "empty"
        (empty / ".git").mkdir(parents=True)
        before = _record_bytes()
        result = runner.invoke(launcher.app, ["catalog", "trust", str(empty)])
        assert result.exit_code != 0
        assert "error" in result.output
        assert _record_bytes() == before

    def test_s3_5_a_subfolder_trusts_the_catalog_discovery_finds(self, env, tmp_path):
        proj = project(tmp_path)
        (proj / "src").mkdir()
        result = runner.invoke(launcher.app, ["catalog", "trust", str(proj / "src")])
        cat = str((proj / ".harnessed" / "catalog").resolve())
        assert result.exit_code == 0 and cat in result.output
        assert catalogsources.trusted_paths() == [cat]

    def test_trusting_twice_records_once(self, env, tmp_path):
        proj = project(tmp_path)
        catalogsources.trust(proj)
        catalogsources.trust(proj)
        assert len(catalogsources.trusted_paths()) == 1


class TestUntrust:
    def test_s13_1_removes_one_path(self, env, tmp_path):
        proj, other = project(tmp_path), project(tmp_path, "other")
        catalogsources.trust(proj)
        catalogsources.trust(other)
        result = runner.invoke(launcher.app, ["catalog", "untrust", str(proj)])
        assert result.exit_code == 0
        assert catalogsources.trusted_paths() == [str((other / ".harnessed" / "catalog").resolve())]
        assert "harnessed catalog trust" in _list(proj)

    def test_s13_2_others_stay_trusted(self, env, tmp_path):
        proj, other = project(tmp_path), project(tmp_path, "other")
        catalogsources.trust(proj)
        catalogsources.trust(other)
        catalogsources.untrust(proj)
        catalogsources.reset()
        catalogsources.set_project_dir(other)
        assert (other / ".harnessed" / "catalog").resolve() in paths.catalog_roots()
        assert "harnessed catalog trust" not in _list(other)

    def test_s13_3_untrusting_an_untrusted_catalog_fails(self, env, tmp_path):
        proj = project(tmp_path)
        before = _record_bytes()
        result = runner.invoke(launcher.app, ["catalog", "untrust", str(proj)])
        assert result.exit_code != 0
        assert "error" in result.output
        assert _record_bytes() == before
