"""corepack is deleted from the base image rather than acknowledged (SPEC group D).

The supply-chain scan flagged corepack on every build. corepack ships inside the node@22 release
tarball; harnessed never uses it, because pnpm comes from mise. So the honest fix is to delete it
— the findings go away because the code does, which is strictly better than a suppression entry.

Deleting a binary out of the base image is the kind of change that is fine until something,
somewhere, shells out to it. These tests are the standing guard on that: they read the REPO at
test time and fail if anything starts depending on corepack again.

What they cannot do: prove the `rm` works, or that pnpm survives it. That needs a real
`podman build`, which this suite never runs (see EVIDENCE, structural blind spot). They pin the
two claims that are checkable from source — nothing invokes corepack, and pnpm's install path
does not go through it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_DOCKERFILE = ROOT / "catalog" / "base" / "Dockerfile.harnessed-base"

# Directories whose contents end up inside, or drive, a harnessed image.
SEARCH_ROOTS = ("catalog", "src")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".ruff_cache"}

# Only files that can EXECUTE something. A plan document naming `corepack enable` cannot break an
# image, and treating prose as a dependency makes this test fire on its own rationale — which is
# exactly how it failed the first time it ran.
EXECUTABLE_SUFFIXES = {".sh", ".bash", ".py", ".yaml", ".yml", ".toml", ""}


def is_executable_surface(path):
    if path.suffix in EXECUTABLE_SUFFIXES:
        return True
    return path.name.startswith("Dockerfile") or ".Dockerfile" in path.name


def repo_files():
    """Every text file under the search roots that could execute a command. Walks the tree rather
    than shelling out to git, so the test works in a worktree, a tarball, or a fresh clone alike."""
    for root in SEARCH_ROOTS:
        for path in (ROOT / root).rglob("*"):
            if not path.is_file():
                continue
            if SKIP_DIRS & set(path.parts):
                continue
            if not is_executable_surface(path):
                continue
            yield path


def strip_comments(text):
    """Drop `#` comment lines. The rationale for deleting corepack necessarily names corepack, so
    a check that reads comments flags the fix as the defect."""
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def logical_lines(text):
    """Join shell/Dockerfile backslash continuations into one logical line.

    The unit a reader reasons about is the command, not the physical line. The corepack removal
    spans four physical lines, so a per-physical-line check sees three fragments with no `rm` in
    them and reports the deletion itself as a dependency on corepack.
    """
    joined, buf = [], ""
    for line in strip_comments(text).splitlines():
        buf += line.rstrip()
        if buf.endswith("\\"):
            buf = buf[:-1] + " "
            continue
        joined.append(buf)
        buf = ""
    if buf:
        joined.append(buf)
    return joined


def mentions_corepack(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return [line.strip() for line in logical_lines(text) if "corepack" in line]


class TestNothingDependsOnCorepack:
    def test_the_only_corepack_references_are_the_removal_and_its_rationale(self):
        """D1. Any NEW hit here is the failure this test exists for: something started using a
        binary the base image no longer ships, and it would fail at runtime, not at build."""
        offenders = {}
        for path in repo_files():
            # The one legitimate user, on a different base image entirely (test below).
            if path == ROOT / "catalog" / "services" / "agentmemory" / "Dockerfile":
                continue
            hits = [
                line for line in mentions_corepack(path)
                if "rm -rf" not in line  # the Dockerfile layer that performs the deletion
            ]
            if hits:
                offenders[str(path.relative_to(ROOT))] = hits
        assert offenders == {}, offenders

    def test_the_agentmemory_service_does_not_build_on_the_harnessed_base(self):
        """The one place in the repo that genuinely runs `corepack enable`. It is only safe to
        delete corepack from the base image because this image does not derive from it — so that
        fact is a load-bearing assumption, and it gets a test rather than a comment."""
        dockerfile = ROOT / "catalog" / "services" / "agentmemory" / "Dockerfile"
        if not dockerfile.is_file():
            pytest.skip("agentmemory service not present in this checkout")
        text = dockerfile.read_text()
        assert "corepack" in text, "fixture drift: this test guards a corepack user that vanished"
        froms = re.findall(r"^FROM\s+(\S+)", text, re.M)
        assert froms, "no FROM line found"
        assert not any("harnessed-base" in f for f in froms), froms


class TestTheBaseImageStillProvidesPnpm:
    """N8. Deleting corepack must not take pnpm with it."""

    @pytest.fixture(scope="class")
    def dockerfile(self):
        assert BASE_DOCKERFILE.is_file(), BASE_DOCKERFILE
        return BASE_DOCKERFILE.read_text()

    def test_pnpm_is_installed_by_mise_not_by_corepack(self, dockerfile):
        """Read from the authority at test time. A pasted copy would agree with my reading of the
        Dockerfile forever, including after someone changes it."""
        mise_pins = re.findall(r"^\s+(pnpm@\S+)", dockerfile, re.M)
        assert mise_pins, "no `pnpm@<version>` pin found in the mise install block"
        # Comments stripped first: the rationale for the removal names `corepack prepare`, and
        # matching against raw text makes the explanation of the fix indistinguishable from the
        # thing it removed.
        assert not re.search(r"corepack\s+(enable|prepare)", strip_comments(dockerfile))

    def test_the_removal_layer_names_corepack_and_nothing_else(self, dockerfile):
        """The `rm` is the destructive half of this change. Pin exactly what it deletes, so a
        later edit that widens the glob fails here instead of in a broken image."""
        match = re.search(r"^RUN rm -rf (.*?)(?:&&\s*\\?\s*\n\s*mise reshim)", dockerfile,
                          re.M | re.S)
        assert match, "corepack removal layer not found or no longer ends in `mise reshim`"
        targets = re.findall(r'"([^"]+)"', match.group(1))
        assert targets, match.group(1)
        for target in targets:
            assert target.rstrip("/").endswith("corepack"), target

    def test_the_removal_runs_after_the_mise_install_that_provides_pnpm(self, dockerfile):
        """Ordering is load-bearing: `mise reshim` in the removal layer regenerates the shim dir,
        so it must come after the install that created it, or pnpm's shim is never rebuilt."""
        install = dockerfile.index("pnpm@")
        removal = dockerfile.index("RUN rm -rf")
        assert install < removal
