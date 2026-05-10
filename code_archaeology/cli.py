"""
Command-line interface for the Code Archaeology & Refactoring Agent System.

Usage:
    python -m code_archaeology.cli --dir /path/to/project archaeology my_func
    python -m code_archaeology.cli --dir /path/to/project rename old_name new_name
    python -m code_archaeology.cli --dir /path/to/project integrity
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Optional

from .orchestrator import Orchestrator
from .core.types import RefactoringPlan


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="code-archaeology",
        description="Code Archaeology & Cross-File Refactoring Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          %(prog)s --dir . archaeology my_function
          %(prog)s --dir . trace my_function --direction downstream
          %(prog)s --dir . impact my_function
          %(prog)s --dir . rename old_name new_name --execute
          %(prog)s --dir . extract src/main.py 42 58 new_helper
          %(prog)s --dir . move MyClass src/new_module.py
          %(prog)s --dir . change-sig process_data name age email
          %(prog)s --dir . integrity
          %(prog)s --dir . stats
        """),
    )
    p.add_argument("--dir", default=".", help="Project root directory (default: .)")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.add_argument("--no-color", action="store_true", help="Disable colored output")

    sub = p.add_subparsers(dest="command", help="Available commands")

    # ── Archaeology commands ─────────────────────────────────────────
    arch = sub.add_parser("archaeology", aliases=["arch"], help="Generate archaeology report")
    arch.add_argument("symbol", help="Symbol name to investigate")

    trace_p = sub.add_parser("trace", help="Trace dependency chains")
    trace_p.add_argument("symbol", help="Symbol to trace from")
    trace_p.add_argument("--direction", "-d", choices=["downstream", "upstream"],
                         default="downstream", help="Trace direction")
    trace_p.add_argument("--max-depth", type=int, default=100)

    impact_p = sub.add_parser("impact", help="Full impact analysis")
    impact_p.add_argument("symbol", help="Symbol to analyze")

    sub.add_parser("entry-points", aliases=["entries"],
                   help="Find entry points")
    sub.add_parser("circular", help="Find circular dependencies")
    sub.add_parser("hubs", help="Find hub symbols")

    find_p = sub.add_parser("find", help="Search for symbols")
    find_p.add_argument("pattern", help="Search pattern")

    flow_p = sub.add_parser("data-flow", help="Trace data flow")
    flow_p.add_argument("variable", help="Variable name")
    flow_p.add_argument("--scope", default="", help="Scope context")

    call_p = sub.add_parser("call-hierarchy", aliases=["calls"],
                            help="Show call hierarchy")
    call_p.add_argument("function", help="Function name")

    inherit_p = sub.add_parser("inheritance", aliases=["inherit"],
                               help="Show inheritance chain")
    inherit_p.add_argument("class_name", help="Class name")

    # ── Refactoring commands ─────────────────────────────────────────
    rename_p = sub.add_parser("rename", help="Plan/execute cross-file rename")
    rename_p.add_argument("old_name", help="Current symbol name")
    rename_p.add_argument("new_name", help="New symbol name")
    rename_p.add_argument("--execute", action="store_true",
                          help="Actually apply (default: dry-run)")
    rename_p.add_argument("--backup", action="store_true",
                          help="Create backup before applying")

    extract_p = sub.add_parser("extract", help="Extract code block to function")
    extract_p.add_argument("file", help="Source file")
    extract_p.add_argument("start_line", type=int, help="Start line")
    extract_p.add_argument("end_line", type=int, help="End line")
    extract_p.add_argument("new_name", help="New function name")
    extract_p.add_argument("--target", default="", help="Target file (default: same file)")
    extract_p.add_argument("--execute", action="store_true")

    move_p = sub.add_parser("move", help="Move symbol between files")
    move_p.add_argument("symbol", help="Symbol to move")
    move_p.add_argument("target_file", help="Destination file")
    move_p.add_argument("--execute", action="store_true")

    sig_p = sub.add_parser("change-sig", help="Change function signature")
    sig_p.add_argument("function", help="Function name")
    sig_p.add_argument("params", nargs="+", help="New parameter list")
    sig_p.add_argument("--execute", action="store_true")

    remove_p = sub.add_parser("remove", help="Remove unused symbol")
    remove_p.add_argument("symbol", help="Symbol to remove")
    remove_p.add_argument("--execute", action="store_true")

    # ── Verification commands ────────────────────────────────────────
    sub.add_parser("integrity", help="Run full integrity check")
    sub.add_parser("stats", help="Show codebase statistics")

    tests_p = sub.add_parser("find-tests", help="Find related tests")
    tests_p.add_argument("--symbol", default="", help="Find tests for symbol")

    return p


class CLI:
    """Rich CLI handler for the code archaeology system."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.orchestrator = Orchestrator(args.dir)
        self._use_color = not args.no_color
        self._json = args.json

    def run(self) -> int:
        """Run the CLI. Returns exit code."""
        cmd = self.args.command or ""

        # Commands that need graph build
        need_graph = {
            "archaeology", "arch", "trace", "impact", "find",
            "entry-points", "entries", "circular", "hubs",
            "data-flow", "call-hierarchy", "calls", "inheritance", "inherit",
            "rename", "extract", "move", "change-sig", "remove",
            "integrity", "stats", "find-tests",
        }

        if cmd in need_graph:
            self._print("Building dependency graph...", style="dim")
            stats = self.orchestrator.build_graph(progress=not self._json)
            if not self._json:
                self._print(f"  Indexed {stats['total_files']} files, "
                            f"{stats['total_symbols']} symbols, "
                            f"{stats['total_edges']} edges in "
                            f"{stats['elapsed_ms']:.0f}ms\n", style="dim")

        # Dispatch
        handlers = {
            "archaeology": self._handle_archaeology,
            "arch": self._handle_archaeology,
            "trace": self._handle_trace,
            "impact": self._handle_impact,
            "entry-points": self._handle_entry_points,
            "entries": self._handle_entry_points,
            "circular": self._handle_circular,
            "hubs": self._handle_hubs,
            "find": self._handle_find,
            "data-flow": self._handle_data_flow,
            "call-hierarchy": self._handle_call_hierarchy,
            "calls": self._handle_call_hierarchy,
            "inheritance": self._handle_inheritance,
            "inherit": self._handle_inheritance,
            "rename": self._handle_rename,
            "extract": self._handle_extract,
            "move": self._handle_move,
            "change-sig": self._handle_change_sig,
            "remove": self._handle_remove,
            "integrity": self._handle_integrity,
            "stats": self._handle_stats,
            "find-tests": self._handle_find_tests,
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        else:
            self._print("No command specified. Use --help for available commands.", style="yellow")
            return 1

        return 0

    # ── Command handlers ─────────────────────────────────────────────

    def _handle_archaeology(self) -> None:
        result = self.orchestrator.archaeology(self.args.symbol)
        self._output(result, title=f"Archaeology Report: {self.args.symbol}")

    def _handle_trace(self) -> None:
        result = self.orchestrator.trace(self.args.symbol, self.args.direction)
        self._output(result, title=f"Trace {self.args.direction}: {self.args.symbol}")

    def _handle_impact(self) -> None:
        result = self.orchestrator.impact_analysis(self.args.symbol)
        if not self._json:
            self._print_impact(result)

    def _handle_entry_points(self) -> None:
        result = self.orchestrator.find_entry_points()
        self._output(result, title="Entry Points & Leaves")

    def _handle_circular(self) -> None:
        result = self.orchestrator.find_circular_deps()
        if not self._json:
            self._print_circular(result)

    def _handle_hubs(self) -> None:
        hubs = self.orchestrator.get_hub_symbols(20)
        if self._json:
            print(json.dumps([{"symbol": s, "centrality": c} for s, c in hubs], indent=2))
        else:
            print("\n  Hub Symbols (most connected):")
            print(f"  {'Symbol':<50} {'Centrality'}")
            print(f"  {'-'*50} {'-'*10}")
            for sym, cent in hubs[:20]:
                bar = "█" * int(cent * 20)
                print(f"  {sym:<50} {cent:.3f}  {bar}")

    def _handle_find(self) -> None:
        result = self.orchestrator.find_symbol(self.args.pattern)
        self._output(result, title=f"Symbols matching '{self.args.pattern}'")

    def _handle_data_flow(self) -> None:
        result = self.orchestrator.trace_data_flow(self.args.variable, self.args.scope)
        self._output(result, title=f"Data Flow: {self.args.variable}")

    def _handle_call_hierarchy(self) -> None:
        result = self.orchestrator.call_hierarchy(self.args.function)
        self._output(result, title=f"Call Hierarchy: {self.args.function}")

    def _handle_inheritance(self) -> None:
        result = self.orchestrator.inheritance_chain(self.args.class_name)
        if not self._json and "chain" in result:
            print(f"\n  {result['chain']}\n  File: {result.get('file', '?')}")
            print(f"  Depth: {result.get('depth', 0)}")
        else:
            self._output(result)

    def _handle_rename(self) -> None:
        plan = self.orchestrator.plan_rename(self.args.old_name, self.args.new_name)
        self._handle_refactoring_plan(plan, self.args.execute, self.args.backup)

    def _handle_extract(self) -> None:
        plan = self.orchestrator.plan_extract(
            self.args.file, self.args.start_line, self.args.end_line,
            self.args.new_name, self.args.target,
        )
        self._handle_refactoring_plan(plan, self.args.execute)

    def _handle_move(self) -> None:
        plan = self.orchestrator.plan_move(self.args.symbol, self.args.target_file)
        self._handle_refactoring_plan(plan, self.args.execute)

    def _handle_change_sig(self) -> None:
        plan = self.orchestrator.plan_change_signature(
            self.args.function, self.args.params,
        )
        self._handle_refactoring_plan(plan, self.args.execute)

    def _handle_remove(self) -> None:
        plan = self.orchestrator.plan_remove(self.args.symbol)
        self._handle_refactoring_plan(plan, self.args.execute)

    def _handle_integrity(self) -> None:
        result = self.orchestrator.integrity_check()
        if not self._json:
            self._print_integrity(result)

    def _handle_stats(self) -> None:
        stats = self.orchestrator.get_stats()
        if self._json:
            print(json.dumps(stats, indent=2))
        else:
            print("\n  Codebase Statistics:")
            print(f"  {'─' * 40}")
            for key, val in stats.items():
                print(f"  {key.replace('_', ' ').title():<30} {val}")

    def _handle_find_tests(self) -> None:
        result = self.orchestrator.find_tests(self.args.symbol)
        self._output(result, title="Related Tests")

    # ── Refactoring execution ────────────────────────────────────────

    def _handle_refactoring_plan(
        self, plan: RefactoringPlan, execute: bool = False, backup: bool = False,
    ) -> None:
        """Display a plan and optionally execute it."""
        if self._json:
            print(json.dumps(self._plan_to_dict(plan), indent=2, default=str))
            return

        # Pretty print the plan
        print(f"\n  {'='*60}")
        print(f"  Plan: {plan.title}")
        print(f"  {'='*60}")
        print(f"  Risk:        {plan.risk_assessment}")
        print(f"  Files:       {len(plan.impacted_files)} affected")
        print(f"  Steps:       {plan.estimated_steps}")
        print(f"  Rollback:    {plan.rollback_plan[:80]}...")

        print(f"\n  Changes:")
        for cs in plan.change_sets:
            for step_group in cs.file_changes.values():
                for step in step_group:
                    risk_color = {
                        "safe": "green", "low": "blue", "medium": "yellow",
                        "high": "red", "critical": "red",
                    }.get(step.risk.value, "white")
                    print(f"    [{risk_color}]{step.risk.value.upper():<8}[/] "
                          f"{step.file}:{step.location.line}  "
                          f"{step.description}")

        if execute:
            result = self.orchestrator.execute(plan, dry_run=False, create_backup=backup)
            print(f"\n  Result: {result.get('status', 'UNKNOWN')}")
            if result.get("applied_count"):
                print(f"  Applied: {result['applied_count']} steps in "
                      f"{len(result.get('modified_files', []))} files")
            if result.get("failed"):
                for f in result["failed"]:
                    print(f"  FAILED: {f}")
        else:
            print(f"\n  [dim]Dry-run mode. Use --execute to apply changes.[/]")

    # ── Output formatting ────────────────────────────────────────────

    def _output(self, data, title: str = "") -> None:
        if self._json:
            print(json.dumps(data, indent=2, default=str))
        elif isinstance(data, dict):
            if title:
                print(f"\n  {title}")
                print(f"  {'─' * len(title)}")
            _pretty_dict(data, indent=2)

    def _print_impact(self, result: dict) -> None:
        print(f"\n  Impact Analysis: {result.get('symbol', '?')}")
        print(f"  {'='*50}")
        if "definition" in result:
            d = result["definition"]
            print(f"  Defined at: {d.get('file', '?')}:{d.get('line', '?')}")
            print(f"  Kind:       {d.get('kind', '?')}")
            if d.get("signature"):
                print(f"  Signature:  {d['signature']}")
        if "risk_assessment" in result:
            r = result["risk_assessment"]
            print(f"\n  Risk Level: {r.get('level', '?').upper()}")
            print(f"  Reason:     {r.get('reason', '?')}")
        if "downstream" in result:
            ds = result["downstream"]
            print(f"\n  Downstream Impact:")
            print(f"    Direct dependents:     {ds.get('direct_count', 0)}")
            print(f"    Transitive dependents: {ds.get('transitive_count', 0)}")
            print(f"    Impact depth:          {ds.get('total_impact_depth', 0)} levels")
            files = ds.get("impacted_files", [])
            if files:
                print(f"    Impacted files ({len(files)}):")
                for f in files[:15]:
                    print(f"      {f}")
                if len(files) > 15:
                    print(f"      ... and {len(files)-15} more")
        if "upstream" in result:
            us = result["upstream"]
            print(f"\n  Upstream Dependencies:")
            print(f"    Direct dependencies:     {us.get('direct_count', 0)}")
            print(f"    Transitive dependencies: {us.get('transitive_count', 0)}")

    def _print_circular(self, result: dict) -> None:
        print(f"\n  Circular Dependency Analysis")
        print(f"  {'='*40}")
        cycles = result.get("symbol_cycles", [])
        ci = result.get("circular_imports", [])
        print(f"  Symbol cycles:     {len(cycles)}")
        for c in cycles[:5]:
            print(f"    {' -> '.join(c)}")
        print(f"  Circular imports:  {len(ci)}")
        for c in ci[:5]:
            print(f"    {' -> '.join(c)}")

    def _print_integrity(self, result: dict) -> None:
        print(f"\n  Integrity Check: {result.get('status', '?')}")
        print(f"  {'='*40}")
        for issue in result.get("issues", []):
            icon = {"CRITICAL": "!", "ERROR": "!", "WARNING": "?", "INFO": "i"}.get(
                issue.get("severity", ""), "-")
            print(f"  [{issue.get('severity', '?').lower()}]{icon} "
                  f"{issue.get('type', '?')}: {issue.get('message', '?')}")
        if not result.get("issues"):
            print("  No issues found.")
        stats = result.get("stats", {})
        if stats:
            print(f"\n  Files: {stats.get('total_files', 0)}  "
                  f"Symbols: {stats.get('total_symbols', 0)}  "
                  f"Edges: {stats.get('total_edges', 0)}")

    def _plan_to_dict(self, plan: RefactoringPlan) -> dict:
        return {
            "title": plan.title,
            "description": plan.description,
            "kind": plan.kind.value,
            "primary_symbol": plan.primary_symbol,
            "impacted_files": sorted(plan.impacted_files),
            "impacted_symbols": sorted(plan.impacted_symbols),
            "risk_assessment": plan.risk_assessment,
            "estimated_steps": plan.estimated_steps,
            "rollback_plan": plan.rollback_plan,
            "change_sets": [
                {
                    "total_files": cs.total_files,
                    "total_symbols": cs.total_symbols,
                    "estimated_risk": cs.estimated_risk.value,
                    "steps": [
                        {
                            "kind": s.kind.value,
                            "description": s.description,
                            "file": s.file,
                            "line": s.location.line,
                            "risk": s.risk.value,
                        }
                        for s in cs.steps
                    ],
                }
                for cs in plan.change_sets
            ],
        }

    def _print(self, text: str, style: str = "") -> None:
        if self._json:
            return
        print(text)


def _pretty_dict(d: dict, indent: int = 2) -> None:
    """Recursively pretty-print a dict."""
    prefix = " " * indent
    for key, value in d.items():
        if isinstance(value, dict):
            print(f"{prefix}{key}:")
            _pretty_dict(value, indent + 4)
        elif isinstance(value, list) and len(value) > 20:
            print(f"{prefix}{key}: [{len(value)} items]")
            for item in value[:5]:
                print(f"{prefix}  - {_trunc(str(item), 80)}")
            print(f"{prefix}  ... and {len(value)-5} more")
        elif isinstance(value, list):
            print(f"{prefix}{key}: [{len(value)} items]")
            for item in value[:10]:
                print(f"{prefix}  - {_trunc(str(item), 80)}")
        else:
            print(f"{prefix}{key}: {value}")


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n-3] + "..."


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    cli = CLI(args)
    sys.exit(cli.run())


if __name__ == "__main__":
    main()
