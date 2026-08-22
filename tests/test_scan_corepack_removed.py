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

    @pytest.fixture(scope="class")
    def layers(self, dockerfile):
        """The Dockerfile as LOGICAL lines: comments dropped, continuations joined.

        Every assertion below goes through this rather than through the raw text, and the reason
        is not tidiness. Three earlier versions of these tests each matched the wrong thing for
        the same underlying reason — a regex found an unrelated `rm -rf` from the apt layer, an
        `index()` found another one, and a "this must never appear" check fired on the sentence
        explaining why it must never appear. The meaningful unit in a Dockerfile is the command,
        not the physical line, and matching anything else keeps producing tests that fail on
        their own rationale."""
        return logical_lines(dockerfile)

    @pytest.fixture(scope="class")
    def removal(self, layers):
        """The one logical command that deletes corepack."""
        found = [line for line in layers if "rm -rf" in line and "corepack" in line]
        assert len(found) == 1, found
        return found[0]

    def test_pnpm_is_installed_by_mise_not_by_corepack(self, dockerfile, layers):
        """Read from the authority at test time. A pasted copy would agree with my reading of the
        Dockerfile forever, including after someone changes it."""
        mise_pins = re.findall(r"^\s+(pnpm@\S+)", dockerfile, re.M)
        assert mise_pins, "no `pnpm@<version>` pin found in the mise install block"
        assert not any(re.search(r"corepack\s+(enable|prepare)", line) for line in layers)

    def test_the_removal_layer_names_corepack_and_nothing_else(self, removal):
        """The `rm` is the destructive half of this change. Pin exactly what it deletes, so a
        later edit that widens the glob fails here instead of in a broken image."""
        targets = re.findall(r'"([^"]+)"', removal.split("rm -rf", 1)[1].split("&&")[0])
        assert targets, removal
        for target in targets:
            assert target.rstrip("/").endswith("corepack"), target

    def test_the_removal_fails_closed_when_node_cannot_be_resolved(self, removal):
        """`mise where` writes errors to stderr and nothing to stdout, so an inline
        `"$(mise where node@22)/lib/..."` would collapse to an absolute system path that does not
        exist — making `rm -rf` a silent no-op that returns 0. The layer would go green while
        corepack survived, which is the exact failure the scan was meant to stop reporting."""
        assert 'NODE_DIR="$(mise where node@22)"' in removal
        assert '[ -n "$NODE_DIR" ]' in removal
        # The command substitution must never be interpolated straight into a delete path again.
        assert "rm -rf \"$(mise where" not in removal

    def test_the_layer_verifies_corepack_is_actually_gone(self, removal):
        """A delete that reports success without checking is the same fail-open shape one step
        later. The layer proves its own effect or fails the build."""
        assert "mise reshim" in removal
        assert "! command -v corepack" in removal

    def test_the_removal_runs_after_the_mise_install_that_provides_pnpm(self, layers):
        """Ordering is load-bearing: `mise reshim` in the removal layer regenerates the shim dir,
        so it must come after the install that created it, or pnpm's shim is never rebuilt."""
        install = next(i for i, line in enumerate(layers) if "pnpm@" in line)
        removal = next(i for i, line in enumerate(layers)
                       if "rm -rf" in line and "corepack" in line)
        assert install < removal
