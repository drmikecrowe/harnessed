"""Recipe-capability × backend matrix (bd harnessed-0tk.2, BACKENDS.md §4).

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
from harnessed import launcher  # noqa: F401
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
    part a user actually experiences."""

    def test_the_host_launcher_prints_the_gap(self, tmp_path, capsys):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        launcher._warn_capability_gaps("host", [r])
        err = capsys.readouterr().err
        assert "netty" in err and "egress" in err
        assert "not enforced" in err.lower()

    def test_the_container_launcher_is_silent(self, tmp_path, capsys):
        r = _recipe(tmp_path, "netty", "egress:\n  - api.example.com\n")
        launcher._warn_capability_gaps("container", [r])
        assert capsys.readouterr().err == ""

    def test_both_sequencers_call_it(self):
        """One sequencer wired and the other forgotten is the likely regression, and it would be
        invisible: the container backend has no DEGRADED cell today, so a missing call there
        produces identical output until the day someone adds one."""
        import inspect

        for fn in (launcher._launch_host, launcher.container_run):
            src = inspect.getsource(fn)
            assert "_warn_capability_gaps(" in src, f"{fn.__name__} does not warn about capability gaps"

    def test_the_host_warning_precedes_materialization(self):
        """Told while the user can still switch to `container-run`, not after the agent is up."""
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
