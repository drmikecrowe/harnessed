"""Loading catalog manifests must be safe from several threads at once.

`harnessed build -j N` assembles N stacks concurrently, and every worker loads the recipes its
stack declares. A ruamel `YAML` instance carries scanner/parser/constructor state across `load()`
calls and is NOT thread-safe, so a module-level instance shared by those workers interleaves.

The symptom is not a clean crash — it is *nonsense*: a parse error citing a position in one file
and a position in a completely different file, `in "None", line 1`, or (worse, because it looks
like a real authoring bug) a mapping that loads "successfully" with fields missing:

    stack.yaml: required field 'name' is missing      # ... when `name:` is plainly there
"""

import threading

import pytest

from harnessed import schema


def _recipe_names(root):
    return sorted(p.name for p in (root / "recipes").iterdir() if (p / "recipe.yaml").is_file())


@pytest.fixture
def catalog_root():
    from harnessed import paths

    return paths.repo_root() / "catalog"


class TestConcurrentManifestLoads:
    def test_recipes_load_correctly_under_concurrency(self, catalog_root):
        """Every thread must get its OWN recipe back, fully populated — not a neighbour's."""
        names = _recipe_names(catalog_root)
        assert len(names) >= 4, "need a few real recipes to interleave"

        results: dict[str, object] = {}
        errors: list[Exception] = []
        lock = threading.Lock()
        start = threading.Barrier(len(names) * 3)

        def load(name):
            try:
                start.wait(timeout=10)  # maximise overlap inside the parser
                for _ in range(8):
                    recipe = schema.load_recipe(catalog_root / "recipes" / name)
                    with lock:
                        results[name] = recipe.name
            except Exception as exc:  # noqa: BLE001 — the whole point is to catch the garbage
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=load, args=(n,)) for n in names for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent manifest loads failed: {errors[:3]}"
        # Each recipe parsed as ITSELF — a shared parser can hand back another file's mapping.
        assert {k: v for k, v in results.items()} == {n: n for n in names}

    def test_the_same_stack_loads_consistently_from_many_threads(self, catalog_root):
        """A half-built mapping shows up as a *missing required field*, not as a parse error."""
        stacks = sorted(
            p.name for p in (catalog_root / "stacks").iterdir() if (p / "stack.yaml").is_file()
        )
        assert stacks, "need at least one real stack"
        target = stacks[0]

        seen: list[tuple[str, tuple[str, ...]]] = []
        errors: list[Exception] = []
        lock = threading.Lock()
        start = threading.Barrier(12)

        def load():
            try:
                start.wait(timeout=10)
                for _ in range(8):
                    stack = schema.load_stack(catalog_root / "stacks" / target)
                    with lock:
                        seen.append((stack.name, tuple(stack.recipes)))
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=load) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent stack loads failed: {errors[:3]}"
        assert len(set(seen)) == 1, f"the same stack parsed differently across threads: {set(seen)}"
