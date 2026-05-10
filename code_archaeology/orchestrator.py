"""
Orchestrator — the central coordinator that ties together all agents,
parsers, and refactoring operations into a unified workflow.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from .core.types import DependencyGraph, RefactoringPlan
from .core.graph import GraphEngine
from .core.parser import ParserEngine
from .core.resolver import SymbolResolver
from .agents.base import AgentContext
from .agents.archaeologist import ArchaeologistAgent
from .agents.planner import PlannerAgent
from .agents.executor import ExecutorAgent
from .agents.verifier import VerifierAgent


class Orchestrator:
    """Central orchestrator for code archaeology and refactoring workflows.

    Usage:
        orch = Orchestrator("/path/to/project")
        orch.build_graph()

        # Archaeology
        report = orch.archaeology("my_function")
        impact = orch.impact_analysis("MyClass")

        # Refactoring
        plan = orch.plan_rename("old_name", "new_name")
        orch.execute(plan, dry_run=True)     # Preview
        orch.execute(plan, create_backup=True)  # Apply
    """

    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.graph: DependencyGraph = DependencyGraph()
        self.engine: GraphEngine = GraphEngine(self.graph)
        self.resolver: SymbolResolver = SymbolResolver(self.graph)
        self.parser_engine = ParserEngine()

        self._context: Optional[AgentContext] = None
        self._archaeologist: Optional[ArchaeologistAgent] = None
        self._planner: Optional[PlannerAgent] = None
        self._executor: Optional[ExecutorAgent] = None
        self._verifier: Optional[VerifierAgent] = None

        self._latest_plan: Optional[RefactoringPlan] = None

    # ── Graph Construction ───────────────────────────────────────────

    def build_graph(
        self,
        progress: bool = False,
        max_files: int = 0,
    ) -> dict:
        """Parse the entire project and build the dependency graph."""
        start = time.time()

        def progress_cb(current: int, total: int, file_path: str) -> None:
            if progress:
                pct = (current / max(total, 1)) * 100
                print(f"\r  Parsing [{current}/{total}] {pct:.0f}% — {file_path}", end="")

        self.graph = self.parser_engine.parse_directory(
            str(self.root_dir),
            progress_callback=progress_cb if progress else None,
        )
        if progress:
            print()  # Newline after progress

        self.engine = GraphEngine(self.graph)
        self.engine.build_indices()
        self.resolver = SymbolResolver(self.graph)

        # Initialize agents
        self._init_agents()

        elapsed = (time.time() - start) * 1000
        stats = self.engine.get_stats()

        return {
            "elapsed_ms": elapsed,
            **stats,
        }

    def build_graph_for_files(self, file_paths: list[str]) -> dict:
        """Build graph for a specific set of files."""
        self.graph = self.parser_engine.parse_files(file_paths)
        self.engine = GraphEngine(self.graph)
        self.engine.build_indices()
        self.resolver = SymbolResolver(self.graph)
        self._init_agents()
        return self.engine.get_stats()

    # ── Archaeology ──────────────────────────────────────────────────

    def archaeology(self, symbol: str) -> dict:
        """Generate a comprehensive archaeology report for a symbol."""
        self._ensure_agents()
        result = self._archaeologist.execute(
            action="archaeology_report", symbol=symbol,
        )
        return result.data if result.success else {"error": result.errors}

    def trace(self, symbol: str, direction: str = "downstream") -> dict:
        """Trace dependencies upstream or downstream."""
        self._ensure_agents()
        action = f"trace_{direction}"
        result = self._archaeologist.execute(action=action, symbol=symbol)
        return result.data if result.success else {"error": result.errors}

    def impact_analysis(self, symbol: str) -> dict:
        """Full impact analysis for a symbol."""
        self._ensure_agents()
        result = self._archaeologist.execute(action="full_impact_chain", symbol=symbol)
        return result.data if result.success else {"error": result.errors}

    def find_entry_points(self) -> dict:
        """Find all entry points in the codebase."""
        self._ensure_agents()
        return self._archaeologist.execute(action="find_entry_points").data

    def find_circular_deps(self) -> dict:
        """Find all circular dependencies."""
        self._ensure_agents()
        return self._archaeologist.execute(action="find_circular_deps").data

    def find_symbol(self, pattern: str) -> dict:
        """Search for symbols matching a pattern."""
        self._ensure_agents()
        return self._archaeologist.execute(action="find_pattern", pattern=pattern).data

    def trace_data_flow(self, var_name: str, scope: str = "") -> dict:
        """Trace the data flow for a variable."""
        self._ensure_agents()
        return self._archaeologist.execute(
            action="trace_data_flow", var_name=var_name, scope=scope,
        ).data

    def call_hierarchy(self, func_name: str) -> dict:
        """Get the call hierarchy for a function."""
        self._ensure_agents()
        return self.resolver.get_call_hierarchy(func_name)

    def inheritance_chain(self, class_name: str) -> dict:
        """Get the inheritance chain for a class."""
        self._ensure_agents()
        return self.resolver.get_inheritance_chain(class_name)

    # ── Refactoring Planning ─────────────────────────────────────────

    def plan_rename(self, symbol: str, new_name: str, reason: str = "") -> RefactoringPlan:
        """Plan a cross-file rename."""
        self._ensure_agents()
        result = self._planner.execute(
            action="plan_rename",
            symbol=symbol, new_name=new_name, reason=reason,
        )
        self._latest_plan = result.data
        return result.data

    def plan_extract(
        self, file_path: str, start_line: int, end_line: int,
        new_func_name: str, target_file: str = "",
    ) -> RefactoringPlan:
        """Plan extracting a code block into a function."""
        self._ensure_agents()
        result = self._planner.execute(
            action="plan_extract",
            file_path=file_path, start_line=start_line, end_line=end_line,
            new_func_name=new_func_name, target_file=target_file,
        )
        self._latest_plan = result.data
        return result.data

    def plan_move(self, symbol: str, target_file: str) -> RefactoringPlan:
        """Plan moving a symbol to a different file."""
        self._ensure_agents()
        result = self._planner.execute(
            action="plan_move", symbol=symbol, target_file=target_file,
        )
        self._latest_plan = result.data
        return result.data

    def plan_change_signature(
        self, func_name: str, new_params: list[str],
    ) -> RefactoringPlan:
        """Plan changing a function's signature."""
        self._ensure_agents()
        result = self._planner.execute(
            action="plan_change_signature",
            func_name=func_name, new_params=new_params,
        )
        self._latest_plan = result.data
        return result.data

    def plan_remove(self, symbol: str) -> RefactoringPlan:
        """Plan removing an unused symbol."""
        self._ensure_agents()
        result = self._planner.execute(action="plan_remove", symbol=symbol)
        self._latest_plan = result.data
        return result.data

    def plan_inline(self, func_name: str) -> RefactoringPlan:
        """Plan inlining a function."""
        self._ensure_agents()
        result = self._planner.execute(action="plan_inline", func_name=func_name)
        self._latest_plan = result.data
        return result.data

    # ── Execution ────────────────────────────────────────────────────

    def execute(
        self,
        plan: Optional[RefactoringPlan] = None,
        dry_run: bool = True,
        create_backup: bool = False,
    ) -> dict:
        """Execute a refactoring plan.

        Args:
            plan: The plan to execute. Uses latest plan if None.
            dry_run: If True, preview changes without applying.
            create_backup: If True, create backups before applying.
        """
        self._ensure_agents()
        plan = plan or self._latest_plan
        if plan is None:
            return {"error": "No plan to execute"}

        if dry_run:
            return self._executor.execute(action="dry_run", plan=plan).data
        else:
            return self._executor.execute(
                action="apply", plan=plan, create_backup=create_backup,
            ).data

    def preview(self, plan: Optional[RefactoringPlan] = None) -> dict:
        """Preview a plan as a diff."""
        self._ensure_agents()
        plan = plan or self._latest_plan
        if plan is None:
            return {"error": "No plan to preview"}
        return self._executor.execute(action="preview", plan=plan).data

    def rollback(self) -> dict:
        """Rollback the last executed plan."""
        self._ensure_agents()
        return self._executor.execute(action="rollback").data

    # ── Verification ─────────────────────────────────────────────────

    def verify(self, plan: Optional[RefactoringPlan] = None) -> dict:
        """Verify a refactoring plan or the codebase integrity."""
        self._ensure_agents()
        if plan:
            return self._verifier.execute(action="verify_plan", plan=plan).data
        return self._verifier.execute(action="integrity_check").data

    def integrity_check(self) -> dict:
        """Run a full codebase integrity check."""
        self._ensure_agents()
        return self._verifier.execute(action="integrity_check").data

    def find_tests(self, symbol: str = "") -> dict:
        """Find tests related to a symbol."""
        self._ensure_agents()
        return self._verifier.execute(action="find_tests", symbol=symbol).data

    def run_tests(self, paths: list[str] | None = None) -> dict:
        """Run discovered tests."""
        self._ensure_agents()
        return self._verifier.execute(action="run_tests", test_paths=paths).data

    # ── Graph Access ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get graph statistics."""
        return self.engine.get_stats()

    def get_hub_symbols(self, n: int = 20) -> list[tuple[str, float]]:
        """Get the most-connected symbols."""
        return self.engine.find_hub_symbols(n)

    # ── Internal ─────────────────────────────────────────────────────

    def _init_agents(self) -> None:
        self._context = AgentContext(
            graph=self.graph,
            engine=self.engine,
            resolver=self.resolver,
            root_dir=str(self.root_dir),
        )
        self._archaeologist = ArchaeologistAgent(self._context)
        self._planner = PlannerAgent(self._context)
        self._executor = ExecutorAgent(self._context)
        self._verifier = VerifierAgent(self._context)

    def _ensure_agents(self) -> None:
        if self._context is None:
            self._init_agents()
