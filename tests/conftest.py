"""Shared pytest fixtures, and the accounting that keeps the live layer honest."""

import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

# WHY THIS EXISTS (bd harnessed-3x1). This suite carries a live-verification layer — tests that run
# real podman, real binaries — behind env gates. For a long time it ran NOWHERE: `tools/run-tests.sh`
# never set the gate and CI deliberately does not ("Hermetic: no podman on the runner"). Every run
# reported `N passed, 22 skipped`, which reads as healthy, and the 22 WERE the entire live layer.
#
# A skip count is not neutral information. It is the number of things nobody checked, and it looked
# identical whether the layer was thoughtfully deferred or silently broken. So the run now says, in
# words, what did not happen — and refuses to exit green when someone ASKED for live verification
# and did not get it.
#
# Matched on skip reason rather than a marker because the gates predate this and live in seven
# files, each declaring its own `skipif`. New live tests should keep saying "live", "HARNESSED_
# PODMAN", or "needs <thing>" in the reason, or carry the registered `live` marker.
_LIVE_SKIP_RE = re.compile(
    r"HARNESSED_PODMAN|live |needs the \w+ binary|is not installed", re.IGNORECASE
)

_PODMAN_REQUESTED = os.environ.get("HARNESSED_PODMAN") == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: exercises a real external binary; skipped unless its gate is open"
    )
    config.addinivalue_line(
        "markers",
        "live_podman: governed by HARNESSED_PODMAN=1. Applied by `support.podman`, and the thing "
        "the fail-closed check below counts — do not apply it by hand to a test the gate does not "
        "actually open, or an honest run will fail.",
    )


def _all_skips(terminalreporter) -> list[str]:
    """Every skip reason in the run, unfiltered."""
    reasons = []
    for report in terminalreporter.stats.get("skipped", []):
        # For a skip, longrepr is (path, lineno, "Skipped: <reason>").
        reasons.append(
            report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        )
    return reasons


def _live_skips(terminalreporter) -> list[str]:
    """Skips that look like a gate on a real external system — used for the REPORT only.

    Pattern-matching is acceptable here because the cost of missing one is an incomplete listing.
    The fail-closed decision below must not be built on it; see `_podman_skips`.
    """
    return [r for r in _all_skips(terminalreporter) if _LIVE_SKIP_RE.search(r)]


def _podman_skips(terminalreporter) -> list[str]:
    """Skips of tests the podman gate GOVERNS — identified by marker, never by wording.

    This asks the only question that matters when the gate is open: did the tests it governs
    actually run? A marker answers that exactly. Two earlier versions tried to answer it from skip
    reasons and both were wrong in opposite directions:

      - matching reasons containing "HARNESSED_PODMAN" missed the image-precondition skips
        ("<image> not built"), which fire only when the gate is OPEN — so a run could ask for live
        verification, skip them, and exit green. Fail-open, in the guard against fail-open.
      - inverting it to "anything not on an allowlist" caught those, and would also have failed
        the run for a platform skip, an optional-dependency skip, or a quarantined flaky test —
        none of which have anything to do with podman. Every false failure would have been
        answered by widening the allowlist, decaying it back into the first version.

    The marker has neither failure mode. Tests behind other gates (dolt, aoe) are not marked, so
    they are irrelevant here by construction rather than by exemption — there is no list to keep.
    """
    return [
        report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        for report in terminalreporter.stats.get("skipped", [])
        if "live_podman" in getattr(report, "keywords", {})
    ]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say plainly whether anything was verified against a real system this run."""
    skipped = _live_skips(terminalreporter)
    if not skipped:
        if _PODMAN_REQUESTED:
            terminalreporter.write_line("LIVE VERIFICATION: gate open, no live tests skipped.", green=True)
        return

    terminalreporter.write_sep("=", "live verification", red=_PODMAN_REQUESTED)
    terminalreporter.write_line(
        f"{len(skipped)} live test(s) did NOT run — nothing in this run exercised a real "
        f"podman, container, or external binary."
    )
    for reason in sorted(set(skipped)):
        terminalreporter.write_line(f"  - {reason}")
    if _PODMAN_REQUESTED and _podman_skips(terminalreporter):
        terminalreporter.write_line(
            "HARNESSED_PODMAN=1 was set, so the podman-gated tests above were expected to RUN. "
            "Failing this run: being asked for live verification and silently delivering none is "
            "the exact failure this guard exists to prevent."
        )
    else:
        terminalreporter.write_line(
            "Set HARNESSED_PODMAN=1 (with podman installed) to run them. See bd harnessed-3x1."
        )


def pytest_sessionfinish(session, exitstatus):
    """Fail closed: asking for the live layer and not getting it is not a pass.

    Without this, `HARNESSED_PODMAN=1 pytest` on a machine with no usable podman is
    indistinguishable from a clean run — the tests skip, the suite is green, and the CI job that
    exists specifically to exercise podman reports success having exercised nothing.
    """
    if not _PODMAN_REQUESTED or exitstatus != 0:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and _podman_skips(reporter):
        session.exitstatus = 1

# The REAL user config dir, captured before any fixture monkeypatches XDG_CONFIG_HOME away. Used to
# re-expose podman's own config inside the isolated root — see `_isolated_user_catalog`.
_REAL_XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")

# MODULE LEVEL, NOT A FIXTURE — and that is the whole point. `rich` reads FORCE_COLOR when a
# `Console` is CONSTRUCTED, and console.py builds `_out`/`_err` at module import. An autouse
# fixture runs after that import and is therefore too late; it was tried and did not work.
# conftest.py is imported before any test module, so popping it here is early enough.
#
# Why it matters: rich emits plain text when stdout is not a TTY, which is the case under typer's
# `CliRunner`. FORCE_COLOR overrides that check, so ANSI escapes land INSIDE the captured output and
# any assertion on a plain substring fails — `"no such stack 'x'"` is not in
# `"\x1b[1;31merror:\x1b[0m no such stack \x1b[32m'x'\x1b[0m"`. Terminal shell-integration sets it
# (Ghostty exports FORCE_COLOR=3), so a developer hits this having never opted in, while CI — a bare
# environment — is green the whole time. Same machine-dependence class as `_isolated_user_catalog`.
#
# NOT `NO_COLOR`: that would suppress color the tests never asked about, diverging from CI in the
# other direction. The goal is parity with a plain environment, not forced monochrome.
os.environ.pop("FORCE_COLOR", None)


_LINK_KINDS = ("agents", "recipes", "services", "stacks")


@contextmanager
def catalog_local_restored(checkout: Path) -> Generator[None, None, None]:
    """Leave `<checkout>/catalog-local/` exactly as it was found (bd harnessed-ng5).

    `harnessed build` maintains DX symlinks there against whatever `$XDG_CONFIG_HOME` is set when it
    runs, and `_isolated_user_catalog` below hands every test a fresh tmp one. The live tests shell
    out to the real binary in the real checkout, so without this a run ends with the developer's
    overlay links pointing into a `/tmp` tree pytest has already deleted — and nothing says so,
    because `catalog-local/` is gitignored and `git status` stays clean.

    Only ever unlinks a SYMLINK. A real file or directory at `catalog-local/<kind>` is content
    somebody put there on purpose; this helper's job is to be invisible, not tidy.

    LIVES HERE, NOT IN `support.py`, and uses nothing but the stdlib: `test_live_gate_accounting`
    copies this file verbatim into a `pytester` sandbox where `support` is not importable, so any
    import from it would break four unrelated tests. (It did — caught by the full suite.)
    """
    links = Path(checkout) / "catalog-local"
    existed = links.is_dir()
    # The RAW target, not the resolved one: what must go back is the link as it was written, and a
    # stale link's destination is routinely already deleted.
    before = {k: (os.readlink(links / k) if (links / k).is_symlink() else None) for k in _LINK_KINDS}
    try:
        yield
    finally:
        for kind, original in before.items():
            path = links / kind
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                continue  # real content — not ours to remove, and not ours to overwrite
            if original is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(original)
        if not existed and links.is_dir() and not any(links.iterdir()):
            links.rmdir()


@pytest.fixture(scope="session", autouse=True)
def _restore_catalog_local():
    """Apply `catalog_local_restored` to this checkout for the whole session.

    SESSION-SCOPED AND AUTOUSE ON PURPOSE. Per-module opt-in would be a rule the next live test can
    forget, and policing it needs a test asserting a `usefixtures` declaration — mechanics, not the
    property. This removes the failure mode instead. The cost is that the links do churn between tmp
    roots DURING a run; `catalogseed._points_at_a_harnessed_overlay` is what makes that safe.
    """
    with catalog_local_restored(Path(__file__).resolve().parents[1]):
        yield


@pytest.fixture(autouse=True)
def _isolated_user_catalog(monkeypatch, tmp_path_factory):
    """Point $XDG_CONFIG_HOME at an empty dir for every test, so the suite is hermetic.

    `paths.catalog_roots()` puts the user overlay ($XDG_CONFIG_HOME/harnessed/catalog) AHEAD of the
    repo catalog, and the overlay wins on a name clash. Without this fixture, any test that resolves
    a stack/recipe by name silently reads whatever the developer happens to have in
    ~/.config/harnessed/catalog — so the suite's result depends on the machine it runs on. A
    developer whose overlay defines a stack that shadows a repo stack name gets a phantom failure
    (the test discovers the name from the repo catalog, then resolves it out of the overlay and
    asserts against the wrong stack). CI, with no overlay, passes the whole time.

    An empty XDG root means `user_catalog()` doesn't exist, so `catalog_roots()` falls back to the
    repo catalog alone and name resolution is deterministic.

    Tests that *want* an overlay (test_ensure_local_catalog_links, test_persist_*) set
    XDG_CONFIG_HOME themselves; their own monkeypatch runs after this one and overrides it.

    PODMAN SHARES THIS VARIABLE (bd harnessed-vs8). Rootless podman reads
    `$XDG_CONFIG_HOME/containers/storage.conf`, which is where a custom `graphroot` is declared. With
    the root blanked, podman falls back to the DEFAULT graphroot, finds an empty image store, and
    tries to PULL a `localhost/…` image from a registry literally named `localhost` — reported as
    `dial tcp [::1]:443: connect: connection refused`, which looks like a network fault and is not
    one. Every HARNESSED_PODMAN=1 test is affected on a machine whose graphroot is non-default.

    So `containers/` is SYMLINKED back in. Deliberately not "restore the real XDG_CONFIG_HOME when
    podman is in play": that would hand those tests the developer's catalog overlay again and
    reinstate the exact machine-dependence this fixture exists to remove. Linking one subdirectory
    keeps both properties — podman sees its config, `harnessed/catalog` stays absent.

    LATENT TRAP for whoever adds the next live test: a test that sets its OWN XDG_CONFIG_HOME loses
    this symlink with it, and podman goes back to the wrong graphroot. No test does both today (the
    overriding tests in test_persist_mounts are not podman-gated), but a podman-gated test that
    needs its own overlay must re-link `containers/` into whatever root it points at.
    """
    xdg = tmp_path_factory.mktemp("xdg")
    real_containers = _REAL_XDG_CONFIG_HOME / "containers"
    if real_containers.is_dir():
        # A symlink, not a copy: podman may read several files here (containers.conf,
        # registries.conf, storage.conf) and a copy would silently go stale against the real one.
        (xdg / "containers").symlink_to(real_containers)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Give git a committer identity for every test.

    Several tests create throwaway repos and `git commit`. Locally that inherits
    the developer's `~/.gitconfig`, but CI runners have no global identity, so the
    commit fails with exit 128 ("Please tell me who you are"). Setting the GIT_*
    env vars satisfies git regardless of config and keeps the tests portable.
    """
    monkeypatch.setenv("GIT_AUTHOR_NAME", "harnessed-tests")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tests@harnessed.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "harnessed-tests")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tests@harnessed.local")


