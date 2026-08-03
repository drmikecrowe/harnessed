"""Where harnessed keeps things on disk, and what it names them.

Small derivations shared by nearly every other module: the harnessed home, the stacks dir, the
per-stack profile dir, and the image tags built from a stack/harness pair. They are grouped here
because they are the answers a module needs BEFORE it can do anything else, so importing them from
launcher.py would point the dependency the wrong way.
"""
from __future__ import annotations

import os

from pathlib import Path

from . import paths
from .paths import profile_dir
from .schema import load_agent

def _harnessed_dir() -> Path:
    """harnessed's home (honors HARNESSED_DIR). Build context + catalog live under it.

    Never the CWD — see `paths.harnessed_home`. Resolves to the repo root in a source checkout and
    to the installed package dir in a wheel; both really contain `catalog/`.
    """
    return paths.harnessed_home()


def _stacks_dir() -> Path:
    """Repo catalog stacks dir — where `new` scaffolds. Enumeration goes through
    `paths.list_catalog_stacks` (unifies the user overlay), not this repo-only dir."""
    return _harnessed_dir() / "catalog" / "stacks"


def _agent_image(harness: str) -> str:
    """Resolve the agent's container image from catalog/agents/<harness>/agent.yaml (+ :latest)."""
    img = load_agent(harness).image
    return img if ":" in img else f"{img}:latest"


def _ensure_profile_dir(stack: str, harness: str) -> Path:
    """Ensure the XDG profile directory exists and return it."""
    p = profile_dir(stack, harness)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _catalog_base(rt_path: str) -> Path:
    return _harnessed_dir() / "catalog" / "base" / rt_path


def _derived_image(stack: str, harness: str) -> str:
    return f"harnessed-{harness}-{stack}:latest"
