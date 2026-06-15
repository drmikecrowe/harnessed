"""harnessed-tools CLI — the emit-only assembler entrypoint.

Usage:
  harnessed-tools assemble <stack> --build-dir <dir> [--root <dir>]

Run inside the `harnessed-tools` image (or locally with deps) by `harnessed build`.
It only reads recipes/stacks under `--root` and writes the profile under `--build-dir`;
it NEVER invokes podman/docker (the host runs `podman build` on the emitted artifacts).
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
    out.print(f"  skills:   {', '.join(result.skills) or '(none)'}")
    out.print(f"  commands: {', '.join(result.commands) or '(none)'}")
    out.print(f"  mcp:      {', '.join(s.name for s in result.servers) or '(none)'} "
              f"→ {HATAGO_ENDPOINT}")
    out.print(f"  baked:    {', '.join(s.name for s in result.baked) or '(none)'} (hatago image)")
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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = Console()
    err = Console(stderr=True)
    if args.command == "assemble":
        return _run_assemble(args, out, err)
    if args.command == "test":
        return _run_test(args, out, err)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
