"""harnessed — host Python CLI: composes catalog recipes onto an agent and launches the pod.

The package owns all assembly + launch logic. Assembly (assemble/emit/schema) is emit-only and never
invokes podman; the launcher drives podman on the host. See ARCHITECTURE.md.
"""

__version__ = "0.1.0"
