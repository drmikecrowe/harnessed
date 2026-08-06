"""bd harnessed-1t4.2 — a layer cache MISS must not mean a re-download.

The baseline build hit 0 of 24 cached steps in the derived image and re-fetched every package from
the network, because no build in the project mounted a download cache of any kind. The requirement
is about what a rebuild costs, so the tests check the two build inputs an author never sees the
inside of — the base Dockerfile we ship and the Dockerfile the assembler emits — plus one live
podman build that proves the emitted syntax actually caches under rootless podman.
"""
from __future__ import annotations

import re
import subprocess

import pytest

from harnessed import paths
from harnessed.emit import write_derived_dockerfile
from harnessed.schema import InstallSpec, Recipe
from support import patch_all

from support import podman  # the one gate definition

# The downloaders every build path uses, and the cache each one must be given. Paths verified by
# probing the built base image (`pnpm store path`, `uv cache dir`, ~/.cache) — not assumed defaults.
DOWNLOADERS = {
    "mise install": "/home/harnessed/.cache/mise",
    "pnpm add": "/home/harnessed/.cache/pnpm",
    "uv tool install": "/home/harnessed/.cache/uv",
}
CACHE_TARGETS = set(DOWNLOADERS.values())
# pnpm's content-addressed store is NOT in that set, and must never be: see
# TestThePnpmStoreIsNeverCached.


def _run_instructions(body: str) -> list[str]:
    """Every RUN instruction in a Dockerfile, line-continuations joined."""
    joined = re.sub(r"\\\n", " ", body)
    return [
        ln for ln in joined.splitlines()
        if ln.lstrip().upper().startswith("RUN ") and not ln.lstrip().startswith("#")
    ]


def _cache_targets(instruction: str) -> set[str]:
    return {
        m.group(1)
        for m in re.finditer(r"--mount=type=cache,[^\s]*?target=([^\s,]+)", instruction)
    }


def _shipped_image_dockerfiles() -> list:
    """Every image Dockerfile harnessed ships — the base AND each harness image built FROM it."""
    base_dir = paths.harnessed_home() / "catalog" / "base"
    files = sorted(base_dir.glob("Dockerfile.harnessed-*"))
    assert files, f"no shipped Dockerfiles under {base_dir}"
    return files


def _base_body() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _shipped_image_dockerfiles())


class TestShippedImagesCacheTheirDownloads:
    """The base is where mise/pnpm/uv first populate — an uncached base re-downloads for everyone,
    and each harness image adds its own CLI through the same three downloaders."""

    @pytest.mark.parametrize("downloader,cache", sorted(DOWNLOADERS.items()))
    def test_every_downloading_layer_mounts_its_cache(self, downloader, cache):
        offenders = [
            run for run in _run_instructions(_base_body())
            if downloader in run and cache not in _cache_targets(run)
        ]
        assert offenders == [], f"{downloader} without a {cache} cache mount: {offenders}"

    def test_cache_mounts_are_writable_by_the_user_the_layer_runs_as(self):
        # Every cached RUN in the base executes as `harnessed` (uid 1000). A root-owned cache mount
        # makes the layer fail outright, so this is a build-breaking detail, not a nicety.
        for run in _run_instructions(_base_body()):
            for mount in re.findall(r"--mount=type=cache,[^\s]+", run):
                assert "uid=1000" in mount and "gid=1000" in mount, mount

    def test_every_cache_target_is_pre_created_before_it_is_first_mounted(self):
        # Podman creates a missing mount point AND its parents as root. The pnpm store lives under
        # ~/.local/share, so an un-pre-created mount left that dir root-owned and every later
        # `mise install` failed with "Permission denied" — a real build failure, not a theory.
        base = (paths.harnessed_home() / "catalog" / "base" / "Dockerfile.harnessed-base").read_text(
            encoding="utf-8"
        )
        for target in sorted(CACHE_TARGETS):
            mkdir_at = base.find(target.replace("/home/harnessed", "/home/${USERNAME}"))
            first_mount = base.find(f"target={target},")
            assert mkdir_at != -1, f"{target} is never created for the image user"
            assert mkdir_at < first_mount, f"{target} is mounted before it is created as the user"

    def test_no_cache_mount_hides_content_the_image_must_ship(self):
        # A cache mount is NOT part of the image: anything written under its target vanishes at
        # COMMIT. Mounting e.g. $PNPM_HOME (which holds the global bin dir) would silently ship an
        # image whose binaries are missing.
        must_ship = (
            "/home/harnessed/.local/share/pnpm/bin",
            "/home/harnessed/.local/share/pnpm/global",
            "/home/harnessed/.local/bin",
            "/home/harnessed/.local/share/mise/installs",
            "/home/harnessed/.local/share/mise/shims",
            "/home/harnessed/.claude",
        )
        targets = {t for run in _run_instructions(_base_body()) for t in _cache_targets(run)}
        for target in targets:
            for shipped in must_ship:
                assert not shipped.startswith(target.rstrip("/") + "/"), (
                    f"cache mount {target} would hide {shipped}, which must ship in the image"
                )


class TestThePnpmStoreIsNeverCached:
    """The store looks like the obvious thing to cache. Caching it ships a broken image.

    pnpm v11 does not copy out of the store — a global install is a symlink into
    `store/v11/links/…`, and mise's `npm:` backend links the same way. With the store mounted as a
    build cache the links dangle at COMMIT, so the image builds green and then dies at RUNTIME with
    MODULE_NOT_FOUND. Verified by building it: `hatago --version` failed exactly that way.
    """

    STORE = "/home/harnessed/.local/share/pnpm/store"

    def test_no_shipped_dockerfile_mounts_the_store(self):
        for path in _shipped_image_dockerfiles():
            assert self.STORE not in path.read_text(encoding="utf-8"), path.name

    def test_no_emitted_layer_mounts_the_store(self, tmp_path):
        from harnessed.emit import CACHE_MOUNTS

        assert self.STORE not in CACHE_MOUNTS


class TestContainerExecutorCachesDownloads:
    """The same requirement as the build-time cache mounts, after bd harnessed-8px.21.4 moved
    `tools:`/`install:` out of image layers. Those `--mount=type=cache` mounts died with the layers;
    without a replacement the container's ~/.cache would be ephemeral and every reinstall would
    re-fetch from the network — making the runtime executor SLOWER than the build it replaces.
    """

    def _steps(self, tmp_path, monkeypatch, stack="s"):
        from harnessed import launcher

        recipe = tmp_path / "r"
        recipe.mkdir(parents=True)
        (recipe / "install.sh").write_text("echo hi\n", encoding="utf-8")
        r = Recipe(name="r", root=recipe, tools=["npm:context-mode@1.0.169"])
        r.install = InstallSpec(script="install.sh")
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        launcher._run_container_installs(
            "podman", stack, "claude", "img", [r], "cfgvol", "toolsvol",
        )
        return calls

    def _cache_mount(self, cmd):
        return [a for a in cmd if a.endswith("/home/harnessed/.cache")]

    def test_the_install_step_mounts_the_download_cache(self, tmp_path, monkeypatch):
        # An install.sh may reach for any of pnpm/uv/mise, so it gets the whole ~/.cache rather than
        # a guess per recipe.
        run = [c for c in self._steps(tmp_path, monkeypatch) if "install.sh" in " ".join(c)]
        assert len(run) == 1
        assert self._cache_mount(run[0])

    def test_the_merged_tool_step_mounts_the_download_cache(self, tmp_path, monkeypatch):
        # `mise use -g` fans out to backends that shell out to pnpm (npm:) and uv (pipx:).
        run = [c for c in self._steps(tmp_path, monkeypatch) if "mise use -g" in " ".join(c)]
        assert len(run) == 1
        assert self._cache_mount(run[0])

    def test_a_stack_with_no_recipes_emits_no_cache_mounts(self, tmp_path):
        body = write_derived_dockerfile(tmp_path, "s", "claude", []).read_text(encoding="utf-8")
        assert "type=cache" not in body

    def test_the_download_cache_is_shared_across_stacks(self, tmp_path, monkeypatch):
        # The mount must carry nothing stack-specific, or every stack gets its own cache and the
        # sharing it exists for never happens. This is STRONGER than the emitted-text check it
        # replaces: it compares two different STACK NAMES, not two temp dirs.
        a = self._cache_mount(self._steps(tmp_path / "a", monkeypatch, stack="stack-one")[0])
        b = self._cache_mount(self._steps(tmp_path / "b", monkeypatch, stack="stack-two")[0])
        assert a == b and a


@podman
class TestLiveCacheBehaviour:
    """The syntax is only worth anything if this podman actually honours it."""

    def test_cache_survives_a_layer_miss(self, tmp_path):
        # Per-run BUST values: podman's LAYER cache is global and persists between test runs, so a
        # fixed one makes the second build a no-op replay of the PREVIOUS run's layer and the
        # assertion below stops testing anything. `tmp_path.parent.name` is pytest's per-invocation
        # counter (its basename is the same every run), which is what makes the markers unique.
        # The cache id stays fixed — that is the thing under test, and a per-run id would leave a
        # new cache dir behind on every run.
        run_id = tmp_path.parent.name
        mount = (
            "--mount=type=cache,target=/home/harnessed/.cache/probe,id=harnessed-probe,"
            "uid=1000,gid=1000,sharing=locked"
        )
        (tmp_path / "Dockerfile").write_text(
            "FROM docker.io/library/alpine:3.21\n"
            "RUN adduser -D -u 1000 harnessed\n"
            "USER harnessed\n"
            "ARG BUST\n"
            f'RUN {mount} sh -c \'echo "$BUST" >> /home/harnessed/.cache/probe/log; '
            "cat /home/harnessed/.cache/probe/log'\n",
            encoding="utf-8",
        )

        def build(bust: str) -> str:
            out = subprocess.run(
                ["podman", "build", "--quiet=false", "--build-arg", f"BUST={bust}",
                 "-t", "harnessed-cache-probe", str(tmp_path)],
                capture_output=True, text=True, check=True,
            )
            return out.stdout + out.stderr

        first, second = f"{run_id}-a", f"{run_id}-b"
        build(first)
        out = build(second)
        # The busted layer re-ran (it printed its own marker) and still saw what the first left.
        assert second in out, out
        assert re.search(rf"^{re.escape(first)}$", out, re.MULTILINE), out
