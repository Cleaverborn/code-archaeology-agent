#!/usr/bin/env python3
"""
Demo script showing the Code Archaeology & Refactoring Agent System in action.

Run:
    python examples/demo.py
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from code_archaeology import Orchestrator


def main():
    sample_dir = Path(__file__).parent / "sample_project"

    print("=" * 60)
    print("  Code Archaeology Agent System — Demo")
    print("=" * 60)

    # 1. Build the dependency graph
    print("\n[1] Building dependency graph...")
    orch = Orchestrator(str(sample_dir))
    stats = orch.build_graph()
    print(f"    Files:   {stats['total_files']}")
    print(f"    Symbols: {stats['total_symbols']}")
    print(f"    Edges:   {stats['total_edges']}")
    print(f"    Time:    {stats['elapsed_ms']:.0f}ms")

    # 2. Archaeology report
    print("\n[2] Archaeology report for 'validate_email'...")
    report = orch.archaeology("validate_email")
    print(f"    Risk:        {report.get('risk_assessment', {}).get('level', '?').upper()}")
    print(f"    Dependents:  {report.get('impact_summary', {}).get('direct_dependents', 0)}")
    print(f"    Dependencies:{report.get('impact_summary', {}).get('direct_dependencies', 0)}")
    if report.get('recommendation'):
        print(f"    Recommendation: {report['recommendation']}")

    # 3. Impact analysis for a central class
    print("\n[3] Impact analysis for 'User'...")
    impact = orch.impact_analysis("User")
    down = impact.get("downstream", {})
    print(f"    Direct dependents:     {down.get('direct_count', 0)}")
    print(f"    Transitive dependents: {down.get('transitive_count', 0)}")
    files = down.get("impacted_files", [])
    print(f"    Impacted files:        {len(files)}")
    for f in files[:5]:
        print(f"      - {f}")

    # 4. Trace call hierarchy
    print("\n[4] Call hierarchy for 'apply_bulk_discount'...")
    calls = orch.call_hierarchy("apply_bulk_discount")
    if "call_tree" in calls:
        def print_tree(node, indent=0):
            print(f"    {'  ' * indent}{node.get('name', '?')}")
            for child in node.get("children", []):
                print_tree(child, indent + 1)
        print_tree(calls["call_tree"])

    # 5. Find entry points
    print("\n[5] Entry points...")
    entries = orch.find_entry_points()
    print(f"    Entry points: {entries.get('entry_points', [])}")
    print(f"    Leaf files:   {entries.get('leaf_files', [])}")

    # 6. Hub symbols
    print("\n[6] Hub symbols (most connected)...")
    hubs = orch.get_hub_symbols(10)
    for sym, cent in hubs:
        bar = "#" * int(cent * 20)
        print(f"    {sym:<40} {cent:.3f} {bar}")

    # 7. Plan a rename
    print("\n[7] Planning rename: 'validate_email' -> 'is_valid_email'...")
    plan = orch.plan_rename("validate_email", "is_valid_email")
    print(f"    Risk:  {plan.risk_assessment}")
    print(f"    Files: {len(plan.impacted_files)} affected")
    print(f"    Steps: {plan.estimated_steps}")

    # 8. Dry-run the rename
    print("\n[8] Dry-run preview...")
    preview = orch.execute(plan, dry_run=True)
    for item in preview.get("preview", [])[:5]:
        print(f"    {item['file']}:{item['line']} [{item['risk']}] {item['description']}")

    # 9. Integrity check
    print("\n[9] Integrity check...")
    integrity = orch.integrity_check()
    print(f"    Status: {integrity.get('status', '?')}")
    for issue in integrity.get("issues", []):
        print(f"    [{issue['severity']}] {issue['message']}")

    # 10. Stats
    print("\n[10] Codebase stats...")
    for key, val in orch.get_stats().items():
        print(f"    {key.replace('_', ' ').title():<30} {val}")

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
