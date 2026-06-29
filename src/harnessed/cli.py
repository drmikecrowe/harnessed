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
from .scan import ScanError, run_image_scan, run_image_scan_online, run_snyk_container_scan, run_source_scan
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
    asm.add_argument(
        "--build-dir",
        required=True,
        help="directory the profile is emitted under (profiles/<stack>/)",
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
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the structured result as JSON (for CI) instead of the rich table",
    )

    scn = sub.add_parser(
        "scan",
        help="supply-chain source/Python scan of a stack's recipe dirs + emitted profile (BLD-02)",
    )
    scn.add_argument("stack", help="stack name (stacks/<stack>/stack.yaml)")
    scn.add_argument(
        "--root",
        default=None,
        help="directory holding stacks/ and recipes/ (default: current dir)",
    )
    scn.add_argument(
        "--build-dir",
        required=True,
        help="directory the profile is emitted under (profiles/<stack>/) — scoped to this build",
    )

    sci = sub.add_parser(
        "scan-image",
        help="supply-chain image scan of a saved image archive via osv-scanner (BLD-02)",
    )
    sci.add_argument("archive", help="path to a podman/docker image archive tar (from `podman save`)")
    sci_online = sub.add_parser(
        "scan-image-online",
        help="ONLINE supply-chain image scan (fresh DB; nightly re-scan / SEC-04)",
    )
    sci_online.add_argument("archive", help="path to a podman/docker image archive tar (from `podman save`)")

    snyk_ctr = sub.add_parser(
        "scan-snyk-container",
        help="snyk container test on a built image (SC-03; token-gated, warn-and-skip without SNYK_TOKEN)",
    )
    snyk_ctr.add_argument(
        "image_name",
        help="container image name to scan, e.g. harnessed-gstack-time:latest",
    )
    return parser

def _run_assemble(args: argparse.Namespace, out: Console, err: Console) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        result = assemble(root, args.stack, Path(args.build_dir))
    except (CollisionError, SchemaError, RecipeLintError) as exc:
        err.print(f"[bold red]assemble failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Assembled[/bold green] stack [bold]{result.stack.name}[/bold]")
    out.print(f"  profile:  {result.profile_dir}")
    out.print(f"  harness:  {result.stack.harness}")
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
            project_path=args.project,
            harnessed_bin=args.harnessed_bin,
            keep=args.keep,
        )
    except (CapabilityError, SchemaError) as exc:
        err.print(f"[bold red]capability test failed:[/bold red] {exc}", highlight=False)
        return 1
    return report.emit(report_result, as_json=args.as_json, console=out)


def _run_scan(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the SCOPED source/Python supply-chain scan; exit 1 on any HIGH+ finding (BLD-02).

    One structured result drives the rendered warnings AND the exit code: ScanError (CVSS >= HIGH)
    → red; low/medium findings render as warnings and never red-line (the severity gate, not the
    raw scanner exit code — Pitfall 3).
    """
    root = Path(args.root) if args.root else Path.cwd()
    try:
        result = run_source_scan(root, args.stack, Path(args.build_dir))
    except ScanError as exc:
        err.print(f"[bold red]supply-chain scan failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Supply-chain scan clean[/bold green] (HIGH < CVSS {7.0:.1f}) for "
              f"[bold]{args.stack}[/bold]")
    for warning in sorted(set(result.warnings)):
        out.print(f"  [yellow]warning:[/yellow] {warning}")
    return 0


def _run_scan_image(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the image-archive supply-chain scan; exit 1 on any HIGH+ finding (BLD-02)."""
    try:
        result = run_image_scan(Path(args.archive))
    except ScanError as exc:
        err.print(f"[bold red]supply-chain image scan failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Supply-chain image scan clean[/bold green] (HIGH < CVSS {7.0:.1f})")
    for warning in sorted(set(result.warnings)):
        out.print(f"  [yellow]warning:[/yellow] {warning}")
    return 0


def _run_scan_image_online(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the ONLINE image-archive scan (SEC-04 nightly re-scan); exit 1 on any HIGH+ finding.

    Mirrors _run_scan_image but calls run_image_scan_online (fresh osv.dev DB — catches CVEs
    disclosed after the image was built; the whole point of the nightly timer).
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


def _run_scan_snyk_container(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run snyk container test on a built image; exit 1 on HIGH+ finding (SC-03).

    Warns-and-skips without a SNYK_TOKEN so the build stays non-interactive.
    """
    try:
        result = run_snyk_container_scan(args.image_name)
    except ScanError as exc:
        err.print(f"[bold red]snyk container scan failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]snyk container scan clean[/bold green] for [bold]{args.image_name}[/bold]")
    for warning in sorted(set(result.warnings)):
        out.print(f"  [yellow]warning:[/yellow] {warning}")
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
    if args.command == "scan":
        return _run_scan(args, out, err)
    if args.command == "scan-image":
        return _run_scan_image(args, out, err)
    if args.command == "scan-image-online":
        return _run_scan_image_online(args, out, err)
    if args.command == "scan-snyk-container":
        return _run_scan_snyk_container(args, out, err)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
