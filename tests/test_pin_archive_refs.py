"""Branch-pinned ARCHIVE URLs must fail the pin lint (bd harnessed-po7).

The floating-ref gate rejects `--branch main`, `:latest`, `@latest`, and (bd harnessed-1t4.6) any
clone ref that is not a tag or a full SHA. It never looked at a plain archive download:

    curl -fsSL https://github.com/owner/repo/archive/main.tar.gz | tar xz

`main` moves exactly as much there as it does behind `--branch`, so two builds a week apart produce
different images from identical inputs — precisely what the gate exists to stop. Proven when the
bead was filed: editing mikes-universal-setup/install.sh from a SHA to `archive/main.tar.gz` left
all 165 pin/lint tests green.

A git archive AT A 40-HEX SHA is effectively content-addressed, so requiring a SHA is both the pin
and a cheap integrity check.

ONE DELIBERATE DIVERGENCE from the clone gate, which fails closed on a ref it cannot resolve. The
catalog's own correct recipe passes the SHA through a shell FUNCTION PARAMETER:

    fetch() { curl -fsSL "https://github.com/$1/archive/$2.tar.gz" ... }
    fetch oakoss/agent-skills "$OAKOSS_SHA" "$tmp/oakoss"

`$2` cannot be resolved from the URL line, and failing closed there would reject a recipe that is
pinned correctly. So a positional parameter is treated as a pass-through. The residual gap is
recorded in the bead — the proven bug (a literal branch in the URL) is caught either way.
"""

import pytest

from harnessed.schema import PinValidationError, RecipeLintError, load_recipe, validate_install_script, validate_pin

SHA = "0283bed313563d5677a0838f4bf921b03296cf6c"


def _dockerfile(body: str) -> str:
    return f"FROM base\nRUN {body}\n"


class TestGithubArchiveRefs:
    @pytest.mark.parametrize("ref", ["main", "master", "HEAD", "develop", "next", "feat/x"])
    def test_a_branch_archive_is_rejected(self, ref):
        with pytest.raises(PinValidationError) as exc:
            validate_pin("r", _dockerfile(
                f"curl -fsSL https://github.com/o/r/archive/{ref}.tar.gz | tar xz"
            ))
        assert ref in str(exc.value), "the error must name the offending ref"

    def test_a_sha_archive_passes(self):
        validate_pin("r", _dockerfile(
            f"curl -fsSL https://github.com/o/r/archive/{SHA}.tar.gz | tar xz"
        ))

    @pytest.mark.parametrize("ref", ["v1.2.3", "1.2.3", "v6.0.3"])
    def test_a_version_tag_archive_passes(self, ref):
        """Consistent with the clone gate, which accepts a version-like tag as immutable enough."""
        validate_pin("r", _dockerfile(
            f"curl -fsSL https://github.com/o/r/archive/{ref}.tar.gz | tar xz"
        ))

    def test_a_zip_archive_is_gated_too(self):
        with pytest.raises(PinValidationError):
            validate_pin("r", _dockerfile(
                "curl -fsSL https://github.com/o/r/archive/main.zip -o s.zip"
            ))

    def test_refs_heads_form_is_rejected(self):
        """`archive/refs/heads/<branch>` is the fully-qualified spelling of the same moving ref."""
        with pytest.raises(PinValidationError):
            validate_pin("r", _dockerfile(
                "curl -fsSL https://github.com/o/r/archive/refs/heads/main.tar.gz | tar xz"
            ))

    def test_refs_tags_form_passes(self):
        validate_pin("r", _dockerfile(
            "curl -fsSL https://github.com/o/r/archive/refs/tags/v1.2.3.tar.gz | tar xz"
        ))


class TestCodeloadRefs:
    """codeload.github.com is the same download by another hostname — and it is already in the
    egress allowlist, so it is a reachable way to bypass a gate that only knew github.com."""

    @pytest.mark.parametrize("kind", ["tarball", "zipball"])
    def test_a_branch_is_rejected(self, kind):
        with pytest.raises(PinValidationError):
            validate_pin("r", _dockerfile(
                f"curl -fsSL https://codeload.github.com/o/r/{kind}/main -o s"
            ))

    def test_a_sha_passes(self):
        validate_pin("r", _dockerfile(
            f"curl -fsSL https://codeload.github.com/o/r/tarball/{SHA} -o s"
        ))

    def test_the_tar_gz_refs_heads_form_is_rejected(self):
        with pytest.raises(PinValidationError):
            validate_pin("r", _dockerfile(
                "curl -fsSL https://codeload.github.com/o/r/tar.gz/refs/heads/main -o s"
            ))


def _script_recipe(tmp_path, script_body, name="r"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text("name: r\ninstall:\n  script: install.sh\n")
    (d / "install.sh").write_text(script_body)
    return load_recipe(d, strict=True)


class TestVariableRefs:
    """One-hop resolution against a literal shell assignment — the same mechanism the clone gate
    uses. Exercised through install.sh, NOT a Dockerfile: `_SHELL_ASSIGN_RE` matches a bare
    `NAME=value` line, and a Dockerfile has none (assignments are ARG/ENV or inline in a RUN), so
    every Dockerfile variable ref fails closed instead. Testing this on a Dockerfile would pass for
    the wrong reason — rejected as unresolvable rather than resolved-and-judged.
    """

    def test_a_variable_resolving_to_a_branch_is_rejected(self, tmp_path):
        r = _script_recipe(tmp_path, (
            "REF=main\n"
            'curl -fsSL "https://github.com/o/r/archive/$REF.tar.gz" -o s.tgz\n'
        ))
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(r)
        assert "REF" in str(exc.value) and "main" in str(exc.value)

    def test_a_variable_resolving_to_a_sha_passes(self, tmp_path):
        r = _script_recipe(tmp_path, (
            f"REF={SHA}\n"
            'curl -fsSL "https://github.com/o/r/archive/$REF.tar.gz" -o s.tgz\n'
        ))
        validate_install_script(r)

    def test_a_braced_variable_is_resolved_too(self, tmp_path):
        r = _script_recipe(tmp_path, (
            "REF=main\n"
            'curl -fsSL "https://github.com/o/r/archive/${REF}.tar.gz" -o s.tgz\n'
        ))
        with pytest.raises(PinValidationError):
            validate_install_script(r)

    def test_an_unassigned_variable_fails_closed(self, tmp_path):
        """Same stance as the clone gate: "can't tell" and "moves" have the same build consequence."""
        r = _script_recipe(tmp_path, (
            'curl -fsSL "https://github.com/o/r/archive/$MYSTERY.tar.gz" -o s.tgz\n'
        ))
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(r)
        assert "MYSTERY" in str(exc.value)

    def test_a_dockerfile_arg_ref_fails_closed(self):
        """`ARG REF=<sha>` is NOT resolved: `_SHELL_ASSIGN_RE` reads shell assignments, not
        Dockerfile instructions. So it is reported as unprovable rather than waved through — the
        same fail-closed stance the clone gate already takes on an unresolvable variable. No
        catalog Dockerfile uses this shape (the sweep below would catch it); teaching the resolver
        about ARG/ENV would remove the false positive for BOTH gates, which is a change to the
        clone gate's tested behaviour and so deliberately out of scope here (bd harnessed-po7)."""
        body = f"FROM base\nARG REF={SHA}\nRUN curl -fsSL https://github.com/o/r/archive/$REF.tar.gz\n"
        with pytest.raises(PinValidationError) as exc:
            validate_pin("r", body)
        assert "cannot be shown immutable" in str(exc.value)

    def test_the_owner_repo_may_itself_be_one_variable(self, tmp_path):
        """THE REGRESSION THAT MATTERS. The catalog writes `github.com/$1/archive/$2.tar.gz`, where
        `$1` is the whole `owner/repo` — one textual segment, not two. The first version of this
        gate required two literal segments and therefore sailed straight past the exact file the
        bug was reported against; every synthetic `o/r` fixture passed while the real one was
        unguarded. Caught only by injecting a branch into the real install.sh."""
        r = _script_recipe(tmp_path, (
            'fetch() { curl -fsSL "https://github.com/$1/archive/main.tar.gz" -o "$3/s.tgz"; }\n'
        ))
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(r)
        assert "main" in str(exc.value)

    def test_a_positional_parameter_is_a_pass_through(self):
        """The catalog's own idiom. Failing closed here would reject a correctly-pinned recipe —
        see the module docstring."""
        validate_pin("r", _dockerfile(
            'curl -fsSL "https://github.com/$1/archive/$2.tar.gz" -o "$3/src.tgz"'
        ))


class TestCommentsDoNotSelfTrigger:
    def test_a_comment_naming_a_branch_archive_is_ignored(self):
        """The gate strips comments — a doc line explaining WHY we do not do this must not trip it,
        or the fix makes the codebase undocumentable."""
        validate_pin("r", (
            "FROM base\n"
            "# never: https://github.com/o/r/archive/main.tar.gz — main moves\n"
            f"RUN curl -fsSL https://github.com/o/r/archive/{SHA}.tar.gz | tar xz\n"
        ))


class TestInstallScriptsAreGatedTheSameWay:
    """An install.sh is where this actually happens — the bug was proven by editing one."""

    def _recipe(self, tmp_path, script_body):
        d = tmp_path / "r"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text("name: r\ninstall:\n  script: install.sh\n")
        (d / "install.sh").write_text(script_body)
        return load_recipe(d, strict=True)

    def test_a_branch_archive_in_install_sh_is_rejected(self, tmp_path):
        r = self._recipe(tmp_path, (
            "set -euo pipefail\n"
            "curl -fsSL https://github.com/o/r/archive/main.tar.gz -o src.tgz\n"
        ))
        # PinValidationError, not RecipeLintError: they are SIBLING subclasses of SchemaError, and
        # every pin gate raises the former — matching the clone-ref tests.
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(r)
        assert "main" in str(exc.value)

    def test_a_sha_archive_in_install_sh_passes(self, tmp_path):
        r = self._recipe(tmp_path, (
            "set -euo pipefail\n"
            f"curl -fsSL https://github.com/o/r/archive/{SHA}.tar.gz -o src.tgz\n"
        ))
        validate_install_script(r)

    def test_the_real_catalog_recipe_still_passes(self, tmp_path):
        """mikes-universal-setup fetches through a function parameter and IS correctly pinned. A
        gate that rejects it is wrong — this is the false-positive guard."""
        from harnessed import paths
        r = load_recipe(paths.find_in_catalog("recipes", "mikes-universal-setup"), strict=True)
        validate_install_script(r)


class TestTheWholeCatalogStillPasses:
    def test_every_install_and_setup_script_passes_the_new_gate(self):
        """Same sweep the clone-ref gate carries: a new lint that fails a shipped recipe is a
        breaking change, not a fix."""
        from harnessed import paths
        from harnessed.schema import validate_setup_script
        checked = 0
        for root in paths.catalog_roots():
            recipes = root / "recipes"
            if not recipes.is_dir():
                continue
            for manifest in sorted(recipes.rglob("recipe.yaml")):
                r = load_recipe(manifest.parent, strict=True)
                if r.install and r.install.script:
                    validate_install_script(r)
                    checked += 1
                if r.setup and r.setup.script:
                    validate_setup_script(r)
                    checked += 1
        assert checked > 0, "the sweep exercised nothing — it is not guarding anything"
