"""
Verifier Agent — validates refactoring correctness through AST analysis,
reference integrity checks, and test discovery.
"""

from __future__ import annotations

import ast
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BaseAgent, AgentResult
from ..core.types import RefactoringPlan, DependencyGraph, FileNode


class VerifierAgent(BaseAgent):
    """Agent that verifies refactoring correctness."""

    name = "verifier"

    def execute(self, **kwargs) -> AgentResult:
        action = kwargs.get("action", "verify_plan")
        start = time.time()

        actions = {
            "verify_plan": self._verify_plan,
            "check_syntax": self._check_syntax,
            "check_references": self._check_references,
            "find_tests": self._find_tests,
            "run_tests": self._run_tests,
            "integrity_check": self._integrity_check,
        }

        handler = actions.get(action)
        if handler is None:
            return self._err([f"Unknown action: {action}"])

        try:
            result_data = handler(**kwargs)
            return AgentResult(
                success=True,
                data=result_data,
                agent_name=self.name,
                execution_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return self._err([f"Verifier error: {e}"])

    def _verify_plan(self, plan: RefactoringPlan, **kwargs) -> dict:
        """Run all verifications against a plan."""
        results: dict[str, Any] = {
            "plan_title": plan.title,
            "checks": {},
            "all_passed": True,
        }

        # Check 1: All impacted files exist
        missing_files = [
            f for f in plan.impacted_files
            if not os.path.exists(f) and f not in self.context.graph.file_nodes
        ]
        results["checks"]["files_exist"] = {
            "passed": len(missing_files) == 0,
            "missing": missing_files,
        }

        # Check 2: References are resolvable
        ref_check = self._check_references()
        results["checks"]["references"] = {
            "passed": ref_check["unresolved_count"] == 0,
            **ref_check,
        }

        # Check 3: No circular dependencies introduced
        cycles = self.context.engine.detect_cycles()
        results["checks"]["cycles"] = {
            "passed": len(cycles) == 0,
            "cycle_count": len(cycles),
            "cycles": cycles[:10] if cycles else [],
        }

        # Check 4: Syntax check on all modified files (AST parse)
        syntax_results: dict[str, bool] = {}
        for file_path in plan.impacted_files:
            if file_path.endswith(".py"):
                syntax_results[file_path] = self._check_python_syntax(file_path)
        results["checks"]["syntax"] = {
            "passed": all(syntax_results.values()),
            "details": syntax_results,
        }

        # Check 5: Symmetry (every reference has a definition or external import)
        unresolved = self.context.resolver.find_unresolved_references()
        relevant_unresolved = [
            r for r in unresolved
            if r.target_qualified_name in plan.impacted_symbols
        ]
        results["checks"]["unresolved_references"] = {
            "passed": len(relevant_unresolved) == 0,
            "count": len(relevant_unresolved),
            "details": [
                {"target": r.target_qualified_name, "file": r.location.file}
                for r in relevant_unresolved[:20]
            ],
        }

        results["all_passed"] = all(c["passed"] for c in results["checks"].values())
        return results

    def _check_syntax(self, file_paths: list[str] = None, **kwargs) -> dict:
        """Check syntax of given files or all files in the graph."""
        if file_paths is None:
            file_paths = list(self.context.graph.file_nodes.keys())

        results: dict[str, dict] = {}
        for fp in file_paths:
            if fp.endswith(".py"):
                passed, error = self._parse_with_error(fp)
                results[fp] = {"passed": passed, "error": error}
            else:
                results[fp] = {"passed": True, "error": None}

        return {
            "total": len(results),
            "passed": sum(1 for r in results.values() if r["passed"]),
            "failed": sum(1 for r in results.values() if not r["passed"]),
            "details": {fp: r for fp, r in results.items() if not r["passed"]},
        }

    def _check_references(self, **kwargs) -> dict:
        """Check all references in the graph for integrity."""
        unresolved = self.context.resolver.find_unresolved_references()
        dead = self.context.resolver.find_dead_code()
        dupes = self.context.resolver.find_duplicate_definitions()

        return {
            "unresolved_count": len(unresolved),
            "unresolved_top": [
                {"target": r.target_qualified_name, "file": r.location.file, "line": r.location.line}
                for r in unresolved[:20]
            ],
            "dead_code_count": len(dead),
            "dead_code": [
                {"name": s.qualified_name, "file": s.location.file, "line": s.location.line}
                for s in dead[:20]
            ],
            "duplicate_count": len(dupes),
            "duplicate_definitions": {
                k: [s.qualified_name for s in v]
                for k, v in list(dupes.items())[:10]
            },
        }

    def _find_tests(self, symbol: str = "", **kwargs) -> dict:
        """Find test files and test functions related to a symbol."""
        test_files: list[str] = []
        test_functions: list[dict] = []

        # Search for test files near the symbol's definition
        if symbol:
            sym = self.context.graph.get_symbol(symbol)
            if sym:
                search_dir = os.path.dirname(sym.location.file) or self.context.root_dir
                test_files = self._discover_test_files(search_dir)

        # Scan graph for test symbols
        for file_node in self.context.graph.file_nodes.values():
            for sym_name, sym_obj in file_node.symbols.items():
                if sym_name.startswith("test_") or "test" in file_node.path.lower():
                    test_functions.append({
                        "name": sym_obj.name,
                        "qualified_name": sym_obj.qualified_name,
                        "file": sym_obj.location.file,
                        "line": sym_obj.location.line,
                    })

        return {
            "symbol": symbol or "(all)",
            "test_files": test_files[:50],
            "test_file_count": len(test_files),
            "test_functions": test_functions[:100],
            "test_function_count": len(test_functions),
        }

    def _run_tests(self, test_paths: list[str] = None, **kwargs) -> dict:
        """Run tests related to the refactoring."""
        if test_paths is None:
            test_files = self._discover_test_files(self.context.root_dir)
            test_paths = test_files[:20]  # Limit

        if not test_paths:
            return {"status": "NO_TESTS_FOUND"}

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "-x", "--tb=short"] + test_paths,
                capture_output=True, text=True, timeout=120,
                cwd=self.context.root_dir,
            )
            return {
                "status": "PASSED" if result.returncode == 0 else "FAILED",
                "exit_code": result.returncode,
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "error": "Tests timed out after 120s"}
        except FileNotFoundError:
            return {"status": "SKIPPED", "error": "pytest not found"}

    def _integrity_check(self, **kwargs) -> dict:
        """Run a full integrity check on the codebase."""
        syntax = self._check_syntax()
        refs = self._check_references()
        cycles = self.context.engine.detect_cycles()
        circular_imports = self.context.engine.detect_circular_imports()
        stats = self.context.engine.get_stats()

        issues: list[dict] = []
        if refs["unresolved_count"] > 0:
            issues.append({
                "severity": "WARNING",
                "type": "unresolved_references",
                "count": refs["unresolved_count"],
                "message": f"{refs['unresolved_count']} references point to undefined symbols",
            })
        if refs["dead_code_count"] > 0:
            issues.append({
                "severity": "INFO",
                "type": "dead_code",
                "count": refs["dead_code_count"],
                "message": f"{refs['dead_code_count']} symbols appear to be unused",
            })
        if len(cycles) > 0:
            issues.append({
                "severity": "ERROR",
                "type": "circular_dependencies",
                "count": len(cycles),
                "message": f"{len(cycles)} circular dependency chains detected",
            })
        if len(circular_imports) > 0:
            issues.append({
                "severity": "ERROR",
                "type": "circular_imports",
                "count": len(circular_imports),
                "message": f"{len(circular_imports)} circular import chains detected",
            })
        if syntax["failed"] > 0:
            issues.append({
                "severity": "CRITICAL",
                "type": "syntax_errors",
                "count": syntax["failed"],
                "message": f"{syntax['failed']} files have syntax errors",
            })

        return {
            "status": "HEALTHY" if not issues else "ISSUES_FOUND",
            "issues": issues,
            "issue_count": len(issues),
            "stats": stats,
            "references": refs,
        }

    # ── Helpers ──────────────────────────────────────────────────────

    def _check_python_syntax(self, file_path: str) -> bool:
        passed, _ = self._parse_with_error(file_path)
        return passed

    def _parse_with_error(self, file_path: str) -> tuple[bool, str]:
        """Attempt to parse a Python file, returning success and error."""
        try:
            source = Path(file_path).read_text(encoding="utf-8")
            ast.parse(source, filename=file_path)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)

    def _discover_test_files(self, start_dir: str) -> list[str]:
        """Discover test files near a directory."""
        test_files: list[str] = []
        # Walk up to find tests directory
        search_dirs = [start_dir]

        # Add parent directories up to root_dir
        current = start_dir
        while current and current != self.context.root_dir:
            parent = os.path.dirname(current)
            if parent and parent != current:
                search_dirs.append(parent)
                current = parent
            else:
                break

        for d in search_dirs:
            tests_dir = os.path.join(d, "tests")
            if os.path.isdir(tests_dir):
                for root, _, files in os.walk(tests_dir):
                    for f in files:
                        if f.startswith("test_") and f.endswith(".py"):
                            test_files.append(os.path.join(root, f))

        return sorted(set(test_files))
