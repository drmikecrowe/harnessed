"""harnessed-tools — the build-time assembler package (emit-only).

Reads recipe.yaml/stack.yaml and emits a committed profile + hatago.config.json into a
mounted build dir. It never invokes podman/docker; the host runs `podman build` on the
emitted artifacts (design §15, D-12).
"""

__version__ = "0.1.0"
