"""Recipe-capability x backend matrix (bd harnessed-0tk.2, BACKENDS.md §4).

The matrix answers one question: does THIS backend honor what THIS recipe declared? Where it does
not, the stack still runs — so the failure mode is silence, not breakage, which is why a warning is
the whole feature.

Exactly one cell is DEGRADED today: `egress:` on a backend whose isolation is `none`.
`HostBackend.apply_isolation` does nothing by declaration, so a recipe's allowlist is simply not
applied. The one catalog recipe that declares `egress:` is `pulumi`, which is credential-bearing.

Two neighbouring gaps are deliberately NOT this module's job, and tests here pin that:
  * the container-only half of `install:` already has `install.system` — an author-written reason,
    linted by `validate_container_only_declared` and printed verbatim at host launch. A generic
    matrix warning would say less and fire alongside it.
  * `services:` is SUPPORTED on host (`HostBackend.wire_services`). §4's `✗ (yet)` is stale, and
    `test_services_are_supported_on_host` is what fails if anyone "restores" it.

The two conformance tests are the point of having a table at all: §4 went stale because no test
read it.
"""

from __future__ import annotations

import pytest

from harnessed import capmatrix
# Imported for its REGISTRATION side effect: HostBackend/ContainerBackend register themselves on
# import, and the conformance tests below read that registry. capmatrix itself must never import
# launcher (tests/test_module_boundaries.py enforces the direction).
from harnessed import launcher
from harnessed.backend import registered
from harnessed.schema import load_recipe


def _recipe(tmp_path, name, body=""):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(f"name: {name}\n{body}", encoding="utf-8")
    return load_recipe(d, strict=True)


class TestDeclaredPrimitives:
    def test_egress_is_detected(self, tmp_path):
        r = _recipe(tmp_path, "r", "egress:\n  - api.example.com\n")
        assert "egress" in capmatrix.declared_primitives(r)

    def test_a_recipe_declaring_nothing_declares_nothing(self, tmp_path):
        r = _recipe(tmp_path, "r")
        assert capmatrix.declared_primitives(r) == set()

    def test_services_are_detected(self, tmp_path):
        r = _recipe(tmp_path, "r", "services:\n  - beads-server\n")
        assert "services" in capmatrix.declared_primitives(r)


class TestEgressOnHost:
    def test_host_reports_a_gap_for_a_recipe_declaring_egress(self, tmp_path):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        found = capmatrix.gaps("host", [r])
        assert [(g.recipe, g.primitive) for g in found] == [("netty", "egress")]

    def test_the_gap_says_the_allowlist_is_not_enforced(self, tmp_path):
        """The message is the entire product here. A user who reads 'egress' and nothing else
        learns nothing; they need to know the declaration is INERT on this backend."""
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        detail = capmatrix.gaps("host", [r])[0].detail.lower()
        assert "not enforced" in detail
        assert "host" in detail

    def test_container_reports_no_gap_for_egress(self, tmp_path):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        assert capmatrix.gaps("container", [r]) == []

    def test_every_offending_recipe_is_named(self, tmp_path):
        """Reporting only the first would leave the user fixing one of two silent gaps."""
        a = _recipe(tmp_path, "one", "egress:\n  - a.example.com\n")
        b = _recipe(tmp_path, "two", "egress:\n  - b.example.com\n")
        assert sorted(g.recipe for g in capmatrix.gaps("host", [a, b])) == ["one", "two"]


class TestWhatMustStaySilent:
    def test_services_are_supported_on_host(self, tmp_path):
        """§4 says `service sidecars — host: ✗ (yet)`. That is STALE: HostBackend.wire_services
        calls _ensure_services. This test fails if the stale row is ever encoded."""
        r = _recipe(tmp_path, "beadsy", "services:\n  - beads-server\n")
        assert capmatrix.gaps("host", [r]) == []

    def test_a_plain_recipe_is_silent_on_every_backend(self, tmp_path):
        r = _recipe(tmp_path, "plain")
        assert capmatrix.gaps("host", [r]) == []
        assert capmatrix.gaps("container", [r]) == []

    def test_the_matrix_does_not_duplicate_install_system(self, tmp_path):
        """`install.system` is the author's own reason for what a host launch does not get, linted
        by validate_container_only_declared and printed at launch. A second, vaguer warning from
        the matrix would be strictly worse — and would train users to ignore both."""
        r = _recipe(
            tmp_path, "sysy",
            "install:\n  script: install.sh\n  system: needs root to apt-get install\n",
        )
        (tmp_path / "sysy" / "install.sh").write_text("#!/usr/bin/env bash\n")
        assert capmatrix.gaps("host", [r]) == []


class TestMatrixConformance:
    """§4 went stale because nothing read it. These are what stop that happening to the table."""

    def test_every_registered_backend_has_a_column(self):
        missing = sorted(set(registered()) - set(capmatrix.MATRIX))
        assert not missing, (
            f"backends registered with no capability column: {missing} — a new backend must "
            "declare what it honors, not inherit silence"
        )

    def test_every_primitive_has_a_cell_on_every_backend(self):
        holes = [
            (backend, primitive)
            for backend, column in capmatrix.MATRIX.items()
            for primitive in capmatrix.PRIMITIVES
            if primitive not in column
        ]
        assert holes == [], f"missing cells (fail closed, do not default): {holes}"

    def test_every_cell_is_a_known_level(self):
        bad = [
            (b, p, lvl)
            for b, column in capmatrix.MATRIX.items()
            for p, lvl in column.items()
            if lvl not in (capmatrix.SUPPORTED, capmatrix.DEGRADED)
        ]
        assert bad == [], f"cells with an unknown support level: {bad}"

    def test_an_unknown_backend_is_an_error_not_an_empty_result(self, tmp_path):
        """Silently returning [] for a typo'd backend would report 'no gaps' for a backend nobody
        ever checked — the exact failure this matrix exists to prevent."""
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        with pytest.raises(KeyError, match="microvm"):
            capmatrix.gaps("microvm", [r])


class TestTheWarningReachesTheUser:
    """A helper that exists but is never called warns nobody. These pin the wiring, which is the
    part a user actually experiences.

    An independent adversarial review showed the first version of these tests could not tell the
    difference: they matched source TEXT, so `if False:` around either call site left all 33 tests
    green while the feature was off. Fixed from both ends — one test now EXECUTES the host
    sequencer, and both call sites are checked for reachability rather than for a substring.
    """

    def test_the_host_launcher_prints_the_gap(self, tmp_path, capsys):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        launcher._warn_capability_gaps("host", [r])
        err = capsys.readouterr().err
        assert "netty" in err and "egress" in err
        assert "not enforced" in err.lower()

    def test_the_host_gap_does_not_cost_the_user_a_keypress(self, tmp_path, capsys):
        """#359. `_acknowledge_warnings` counts the word WARNING (console._WARN_MARKER) and holds
        the terminal for an Enter before the execvp handoff. This gap is not that kind of message:
        the user asked for `host-run`, egress cannot apply on a backend with no network boundary,
        and nothing about the launch is theirs to decide. At WARNING level every host-run of a
        stack declaring `egress:` charged a keypress for an unchanging, expected fact — which is
        how the gate stops being read at all. The line stays; the interruption goes.
        """
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        before = launcher._err.warnings
        launcher._warn_capability_gaps("host", [r])
        err = capsys.readouterr().err
        assert launcher._err.warnings == before, err
        assert "INFO" in err, err
        # Not merely absent from the count — absent from the TEXT, which is what the counter reads.
        assert "WARNING" not in err.upper(), err

    def test_the_container_launcher_is_silent(self, tmp_path, capsys):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        launcher._warn_capability_gaps("container", [r])
        assert capsys.readouterr().err == ""

    def test_the_host_sequencer_really_prints_the_gap(self, tmp_path, monkeypatch, capsys):
        """EXECUTES `_launch_host` far enough to prove the warning actually reaches stderr.

        This is the test that a source-text assertion cannot be: wrapping the call site in
        `if False:` leaves every `inspect.getsource` check below green while the user sees nothing
        (measured — the whole file passed 33/33 with the host call dead). Only genuine BOUNDARIES
        are stubbed: catalog lookup, assembly, the aoe mirror, launch-env resolution, and the stack
        load. `_warn_capability_gaps`, `capmatrix`, and the sequencer itself all run for real, so
        this is not a test of its own mocks.

        `load_stack_with_recipes` is patched on `launcher` ONLY, never with `patch_all`: `assemble`
        calls the same name internally, and handing it a fake stack is a known way to break other
        things (tests/support.py).
        """
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        stack_dir = tmp_path / "stk"
        stack_dir.mkdir()
        (stack_dir / "stack.yaml").write_text("name: stk\n", encoding="utf-8")

        class _ReachedTheBoundary(Exception):
            """The first thing after the warning. Raised to stop the launch there."""

        def _boundary(self, spec):
            raise _ReachedTheBoundary

        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a, **k: stack_dir)
        monkeypatch.setattr(launcher, "assemble", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_aoe_register", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_resolve_launch_env", lambda *a, **k: {})
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda *a, **k: (None, [r]))
        monkeypatch.setattr(launcher.HostBackend, "wire_services", _boundary)

        with pytest.raises(_ReachedTheBoundary):
            launcher._launch_host("stk", "claude", str(tmp_path))

        err = capsys.readouterr().err
        assert "netty" in err and "egress" in err, err
        assert "not enforced" in err.lower(), err

    @pytest.mark.parametrize("fn_name", ["_launch_host", "container_run"])
    def test_the_call_is_live_not_dead_code(self, fn_name):
        """Both call sites, checked for reachability rather than for the presence of a string.

        Strictly stronger than the `"_warn_capability_gaps(" in src` assertion it replaces: that one
        passed on `if False:`-guarded code. This parses the sequencer and rejects a call sitting
        under a constant-false guard.

        `container_run` gets only this static check, and the reason is structural, not laziness: NO
        test in this repo executes `container_run` — all nine files that mention it either read its
        source or stub it out — because reaching its body means faking podman, the runtime probe and
        the image checks, at which point the test would only exercise its own mocks. So the
        container call site is protected against deletion and against dead-code guards, and NOT
        against a runtime condition that skips it. That limit is real and is recorded in EVIDENCE.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(launcher, fn_name))))
        found: list[bool] = []

        def scan(node, dead: bool) -> None:
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_warn_capability_gaps":
                found.append(dead)
            if isinstance(node, ast.If):
                unreachable = isinstance(node.test, ast.Constant) and not node.test.value
                scan(node.test, dead)
                for stmt in node.body:
                    scan(stmt, dead or unreachable)
                for stmt in node.orelse:
                    scan(stmt, dead)
                return
            for child in ast.iter_child_nodes(node):
                scan(child, dead)

        scan(tree, False)
        assert found, f"{fn_name} never calls _warn_capability_gaps"
        assert not any(found), f"{fn_name} calls _warn_capability_gaps inside a constant-false guard"

    def test_the_host_warning_precedes_materialization(self):
        """Told while the user can still switch to `container-run`, not after the agent is up.

        SOURCE ORDER ONLY. That the call actually runs is
        `test_the_host_sequencer_really_prints_the_gap`; this pins where it sits relative to
        materialization, which that test does not reach.
        """
        import inspect

        src = inspect.getsource(launcher._launch_host)
        assert src.index("_warn_capability_gaps(") < src.index("backend.materialize_config(")


class TestEveryPrimitiveIsDetected:
    """`declared_primitives` maps each primitive to a specific FIELD, and those mappings are the
    silent-breakage risk: rename or re-nest a field and detection returns False forever, so the
    matrix reports "no gaps" for a recipe that declares one. Coverage showed four of the seven
    branches unexercised, which is exactly the shape that rot hides in.

    `setup_script` is the one worth naming: it maps to `recipe.setup.script`, NOT to `recipe.setup`
    — a recipe can carry a `setup:` notice with no executable script at all.
    """

    @pytest.mark.parametrize(
        "primitive,body",
        [
            ("skills", "skills:\n  - my-skill.md\n"),
            ("tools", "tools:\n  - ripgrep@14.1.1\n"),
            ("servers", "mcp:\n  servers:\n    - name: sv\n      command: sv\n      transport: stdio\n"),
            ("services", "services:\n  - beads-server\n"),
            ("egress", "egress:\n  - api.example.com\n"),
        ],
    )
    def test_primitive_is_detected(self, tmp_path, primitive, body):
        r = _recipe(tmp_path, "r", body)
        assert primitive in capmatrix.declared_primitives(r)

    def test_install_is_detected(self, tmp_path):
        r = _recipe(tmp_path, "r", "install:\n  script: install.sh\n")
        (tmp_path / "r" / "install.sh").write_text("#!/usr/bin/env bash\n")
        assert "install" in capmatrix.declared_primitives(r)

    def test_setup_script_is_detected(self, tmp_path):
        r = _recipe(tmp_path, "r", "setup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n")
        (tmp_path / "r" / "setup.sh").write_text("#!/usr/bin/env bash\n")
        assert "setup_script" in capmatrix.declared_primitives(r)

    def test_a_setup_notice_without_a_script_is_not_setup_script(self, tmp_path):
        """The distinction the mapping exists for: `setup:` alone is a user-facing NOTICE, not
        executable setup, so it declares no capability the backend has to honor."""
        r = _recipe(tmp_path, "r", "setup:\n  summary: do a thing\n  reference: http://x\n")
        assert "setup_script" not in capmatrix.declared_primitives(r)


class TestAllGapsPerRecipeAreReported:
    """`gaps()` promises EVERY unhonored declaration, not the first one.

    Today that promise is untestable against the real matrix: only `egress` is DEGRADED, so a
    truncating bug returns the same answer as correct code. A mutation confirmed it —
    `[:1]` over each recipe's primitives survived the entire suite. The contract is what is being
    tested here, so the matrix is temporarily extended to make a second gap exist; otherwise this
    hole reopens silently the day bwrap or devcontainer adds a DEGRADED cell.
    """

    def test_two_degraded_primitives_in_one_recipe_are_both_reported(self, tmp_path, monkeypatch):
        monkeypatch.setitem(capmatrix.MATRIX["host"], "services", capmatrix.DEGRADED)
        monkeypatch.setitem(
            capmatrix._DETAIL, ("host", "services"), "pretend services are degraded here"
        )
        r = _recipe(
            tmp_path, "both",
            "egress:\n  - api.example.com\nservices:\n  - beads-server\n",
        )
        found = capmatrix.gaps("host", [r])
        assert sorted(g.primitive for g in found) == ["egress", "services"]

    def test_the_real_matrix_is_restored_afterwards(self):
        """monkeypatch.setitem must not leak into the conformance tests above."""
        assert capmatrix.MATRIX["host"]["services"] == capmatrix.SUPPORTED


class TestFindingsFromAdversarialReview:
    """Three holes an independent reviewer found in the first cut of this module."""

    def test_every_degraded_cell_has_a_detail(self):
        """CONFIRMED finding. The three conformance tests above check the MATRIX and say nothing
        about `_DETAIL`, so adding a DEGRADED cell without a detail string passed every one of them
        and then produced a bare KeyError at launch. The cell and its explanation are one unit."""
        missing = [
            (backend, primitive)
            for backend, column in capmatrix.MATRIX.items()
            for primitive, level in column.items()
            if level == capmatrix.DEGRADED and (backend, primitive) not in capmatrix._DETAIL
        ]
        assert missing == [], (
            f"DEGRADED cells with no explanation: {missing} — a warning that cannot say what the "
            "user loses is not worth emitting"
        )

    def test_a_missing_detail_never_aborts_a_launch(self, tmp_path, monkeypatch):
        """The other half of the same finding. The test above catches it in CI; this guarantees the
        runtime consequence is a vaguer warning, not a dead launch. Killing someone's launch because
        the WARNING about their launch is incomplete inverts the whole point of the feature."""
        monkeypatch.setitem(capmatrix.MATRIX["host"], "tools", capmatrix.DEGRADED)
        monkeypatch.delitem(capmatrix._DETAIL, ("host", "tools"), raising=False)
        r = _recipe(tmp_path, "toolsy", "tools:\n  - ripgrep@14.1.1\n")
        found = capmatrix.gaps("host", [r])  # must not raise
        assert [g.primitive for g in found] == ["tools"]
        assert "tools" in found[0].detail and "host" in found[0].detail

    def test_a_service_reached_only_by_an_mcp_ref_counts_as_services(self, tmp_path):
        """`svcstate._service_refs` unions THREE sources, and an `mcp.servers[].service` ref is one
        of them — `catalog/recipes/ping` declares its sidecar that way and has no `services:` list
        at all. Checking only `recipe.services` made this module disagree with the launcher about
        the same recipe: harmless while services is SUPPORTED everywhere, wrong the moment it is
        not."""
        r = _recipe(
            tmp_path, "pingy",
            "mcp:\n  servers:\n    - name: ping\n      service: ping\n      transport: http\n",
        )
        assert not r.services, "fixture must declare the service ONLY via the mcp ref"
        assert "services" in capmatrix.declared_primitives(r)

    def test_the_real_ping_recipe_is_detected_as_needing_a_service(self):
        """The fixture above proves the rule; the shipped recipe proves the rule has a subject."""
        from pathlib import Path

        from harnessed.schema import load_recipe

        # Anchored to THIS file, not to the CWD. `Path("catalog/...")` only resolved because
        # tools/run-tests.sh happens to run from the repo root; from anywhere else the test died on
        # a missing directory instead of asserting anything.
        repo_root = Path(__file__).resolve().parents[1]
        ping = load_recipe(repo_root / "catalog" / "recipes" / "ping", strict=True)
        assert "services" in capmatrix.declared_primitives(ping)

    def test_the_container_warning_precedes_the_setup_prompt(self):
        """_prompt_setup_notices can BLOCK on a user answer. Being asked to approve setup before
        being told what the backend will not honor is the wrong order to learn things in.

        SOURCE ORDER ONLY, and unlike the host path there is no behavioral counterpart — nothing in
        this suite executes `container_run`. `test_the_call_is_live_not_dead_code` adds reachability
        on top of this; a runtime condition that skipped the call would still pass both.
        """
        import inspect

        src = inspect.getsource(launcher.container_run)
        assert src.index("_warn_capability_gaps(") < src.index("_prompt_setup_notices(")
