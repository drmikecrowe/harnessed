"""harnessed-tools CLI — the emit-only assembler + capability-test entrypoint.

Usage:
  harnessed-tools assemble <stack> --build-dir <dir> [--root <dir>]

Runs on the host (in-process from `harnessed build`, or standalone). It only reads the catalog and
writes the profile under `--build-dir`; it NEVER invokes podman/docker (the host runs `podman build`
on the emitted artifacts).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import report
from .assemble import assemble
from .capability import CapabilityError, run_capability_test
from .emit import HATAGO_ENDPOINT
from .persist_gc import _fmt_size, list_entries, prune_project
from .scan import ScanError, run_image_scan_online
from .schema import RecipeLintError, SchemaError
from .synclinks import CollisionError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessed-tools",
        description="harnessed build-time assembler (emit-only; never drives the daemon)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    asm = sub.add_parser(
        "assemble",
        help="assemble a stack into a committed profile + hatago config",
    )
    asm.add_argument("stack", help="stack name (stacks/<stack>/stack.yaml)")
    asm.add_argument("harness", help="harness to assemble for (claude|omp|opencode|antigravity|codex)")
    asm.add_argument(
        "--build-dir",
        required=True,
        help="directory the profile is emitted under (profiles/<stack>/<harness>/)",
    )
    asm.add_argument(
        "--root",
        default=None,
        help="directory holding stacks/ and recipes/ (default: current dir)",
    )

    tst = sub.add_parser(
        "test",
        help="capability test: launch <stack> --fresh headless, assert declared capabilities",
    )
    tst.add_argument("stack", help="stack name (stacks/<stack>/stack.yaml)")
    tst.add_argument("harness", help="harness to test against (claude|omp|opencode|antigravity|codex)")
    tst.add_argument(
        "--root",
        default=None,
        help="directory holding stacks/ and recipes/ (default: current dir)",
    )
    tst.add_argument(
        "--project",
        default=None,
        help="scratch project path for the --fresh instance (default: a temp dir)",
    )
    tst.add_argument(
        "--harnessed-bin",
        default=None,
        dest="harnessed_bin",
        help="path to the `harnessed` launcher (default: $HARNESSED_DIR/harnessed or PATH)",
    )
    tst.add_argument(
        "--keep",
        action="store_true",
        help="do not tear the instance down after the test (debugging)",
    )
    tst.add_argument(
        "--no-tests",
        action="store_true",
        dest="no_tests",
        help="skip recipe-authored tests/*.sh scripts (run only the expect: presence oracle)",
    )
    tst.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the structured result as JSON (for CI) instead of the rich table",
    )

    sci_online = sub.add_parser(
        "scan-image-online",
        help="ONLINE supply-chain image scan (fresh DB; nightly re-scan / SEC-04)",
    )
    sci_online.add_argument("archive", help="path to a podman/docker image archive tar (from `podman save`)")

    sub.add_parser(
        "persist-list",
        help="list all persist dirs under persist_root() with recipe, project hash, name, and disk usage",
    )

    prn = sub.add_parser(
        "persist-prune",
        help="remove persist dir(s) for a specific recipe + project (requires --yes; irreversible)",
    )
    prn.add_argument("--recipe", required=True, help="recipe name (e.g. context-mode)")
    prn.add_argument(
        "--project",
        required=True,
        metavar="PATH",
        help="project path — the hash is re-derived from this path, matching what was used at launch",
    )
    prn.add_argument(
        "--name",
        default=None,
        metavar="NAME",
        help="persist entry name to remove; if omitted ALL entries for this recipe+project are removed",
    )
    prn.add_argument(
        "--scope",
        choices=["workspace", "project"],
        default="workspace",
        help=(
            "which scope's hash to use when finding the persist dir: "
            "'workspace' (default, keyed by the exact project path) or "
            "'project' (keyed by git-common-dir, matching scope: project entries launched "
            "from any worktree of the same checkout)"
        ),
    )
    prn.add_argument(
        "--yes",
        action="store_true",
        help="confirm the destructive removal (required; harnessed refuses to delete without it)",
    )
    return parser

def _run_assemble(args: argparse.Namespace, out: Console, err: Console) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        result = assemble(root, args.stack, Path(args.build_dir), args.harness)
    except (CollisionError, SchemaError, RecipeLintError) as exc:
        err.print(f"[bold red]assemble failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Assembled[/bold green] stack [bold]{result.stack.name}[/bold]")
    out.print(f"  profile:  {result.profile_dir}")
    out.print(f"  harness:  {result.harness}")
    out.print(f"  mcp:      {', '.join(s.name for s in result.servers) or '(none)'} "
              f"→ {HATAGO_ENDPOINT}")
    out.print(f"  baked:    {', '.join(s.name for s in result.baked) or '(none)'} (stdio children, in-container hatago)")
    return 0


def _run_test(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the per-stack capability test, render the report, return the test status as exit code.

    The SAME structured result drives the report and the exit code (design §18 / D-11): non-zero
    propagates so `harnessed test` (and CI) goes red when a declared capability is missing.
    """
    root = Path(args.root) if args.root else Path.cwd()
    try:
        report_result = run_capability_test(
            root,
            args.stack,
            args.harness,
            project_path=args.project,
            harnessed_bin=args.harnessed_bin,
            keep=args.keep,
            run_tests=not args.no_tests,
        )
    except (CapabilityError, SchemaError) as exc:
        err.print(f"[bold red]capability test failed:[/bold red] {exc}", highlight=False)
        return 1
    return report.emit(report_result, as_json=args.as_json, console=out)


def _run_scan_image_online(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the ONLINE image-archive scan (SEC-04 nightly re-scan); exit 1 on any HIGH+ finding.

    Calls run_image_scan_online (fresh osv.dev DB — catches CVEs disclosed after the image was
    built; the whole point of the nightly timer).
    """
    try:
        result = run_image_scan_online(Path(args.archive))
    except ScanError as exc:
        err.print(f"[bold red]supply-chain image scan failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Supply-chain image scan clean[/bold green] (HIGH < CVSS {7.0:.1f}; online)")
    for warning in sorted(set(result.warnings)):
        out.print(f"  [yellow]warning:[/yellow] {warning}")
    return 0


def _run_persist_list(_args: argparse.Namespace, out: Console, _err: Console) -> int:
    """List all persist dirs: recipe / project_hash / name + disk usage."""
    entries = list_entries()
    if not entries:
        out.print("[dim]No persist dirs found.[/dim]")
        return 0
    for e in entries:
        size = _fmt_size(e.size_bytes)
        out.print(
            f"  [bold]{e.recipe}[/bold] / [cyan]{e.project_hash}[/cyan] / {e.name}  "
            f"[dim]({size})[/dim]  {e.host_dir}",
            highlight=False,
        )
    return 0


def _run_persist_prune(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Remove persist dir(s) for a specific recipe + project; requires --yes."""
    if not args.yes:
        err.print(
            "[bold red]error:[/bold red] persist-prune is irreversible — re-run with [bold]--yes[/bold] to confirm.",
            highlight=False,
        )
        return 1
    removed = prune_project(args.recipe, args.project, name=args.name, scope=args.scope)
    if not removed:
        out.print("[dim]Nothing to remove (no matching persist dir found).[/dim]")
        return 0
    for d in removed:
        out.print(f"[bold red]removed[/bold red] {d}", highlight=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = Console()
    err = Console(stderr=True)
    if args.command == "assemble":
        return _run_assemble(args, out, err)
    if args.command == "test":
        return _run_test(args, out, err)
    if args.command == "scan-image-online":
        return _run_scan_image_online(args, out, err)
    if args.command == "persist-list":
        return _run_persist_list(args, out, err)
    if args.command == "persist-prune":
        return _run_persist_prune(args, out, err)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
