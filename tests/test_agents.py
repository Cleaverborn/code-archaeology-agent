"""Tests for the agent system."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_archaeology.core.types import (
    DependencyGraph, FileNode, Symbol, SymbolKind, Location, Reference,
    CallEdge, ImportEdge,
)
from code_archaeology.core.graph import GraphEngine
from code_archaeology.core.resolver import SymbolResolver
from code_archaeology.agents.base import AgentContext
from code_archaeology.agents.archaeologist import ArchaeologistAgent
from code_archaeology.agents.planner import PlannerAgent
from code_archaeology.agents.executor import ExecutorAgent
from code_archaeology.agents.verifier import VerifierAgent


@pytest.fixture
def sample_context():
    """Build a small sample graph for testing."""
    graph = DependencyGraph()

    # File A: defines helper()
    fA = FileNode(path="a.py", language="python")
    helper = Symbol(
        name="helper", kind=SymbolKind.FUNCTION,
        location=Location(file="a.py", line=1, column=0),
        qualified_name="helper",
        signature="def helper(x):",
        visibility="public",
    )
    fA.symbols["helper"] = helper
    graph.add_file_node(fA)

    # File B: defines main() which calls helper()
    fB = FileNode(path="b.py", language="python")
    main = Symbol(
        name="main", kind=SymbolKind.FUNCTION,
        location=Location(file="b.py", line=1, column=0),
        qualified_name="main",
        signature="def main():",
        visibility="public",
    )
    fB.symbols["main"] = main
    fB.references.append(Reference(
        source=main, target_qualified_name="helper",
        location=Location(file="b.py", line=3, column=4),
        ref_type="call",
    ))
    fB.imports.add("a")
    graph.add_file_node(fB)

    # Add import edge
    graph.add_import_edge(ImportEdge(
        importer="b.py", imported="a.py", symbols=["helper"],
    ))

    # Add call edge
    graph.add_call_edge(CallEdge(
        caller="main", callee="helper",
        location=Location(file="b.py", line=3, column=4),
    ))

    engine = GraphEngine(graph)
    engine.build_indices()
    resolver = SymbolResolver(graph)

    return AgentContext(
        graph=graph, engine=engine, resolver=resolver,
        root_dir="/test",
    )


class TestArchaeologistAgent:
    def test_trace_downstream(self, sample_context):
        agent = ArchaeologistAgent(sample_context)
        result = agent.execute(action="trace_downstream", symbol="helper")
        assert result.success
        data = result.data
        assert data["symbol"] == "helper"
        assert "main" in data["direct_dependents"]
        assert data["direct_count"] >= 1

    def test_trace_upstream(self, sample_context):
        agent = ArchaeologistAgent(sample_context)
        result = agent.execute(action="trace_upstream", symbol="main")
        assert result.success
        data = result.data
        assert "helper" in data["direct_dependencies"]

    def test_full_impact_chain(self, sample_context):
        agent = ArchaeologistAgent(sample_context)
        result = agent.execute(action="full_impact_chain", symbol="helper")
        assert result.success
        data = result.data
        assert "risk_assessment" in data
        assert data["downstream"]["direct_count"] >= 1

    def test_find_pattern(self, sample_context):
        agent = ArchaeologistAgent(sample_context)
        result = agent.execute(action="find_pattern", pattern="help")
        assert result.success
        data = result.data
        assert data["match_count"] >= 1
        match_names = [m["name"] for m in data["matches"]]
        assert "helper" in match_names

    def test_find_entry_points(self, sample_context):
        agent = ArchaeologistAgent(sample_context)
        result = agent.execute(action="find_entry_points")
        assert result.success


class TestPlannerAgent:
    def test_plan_rename(self, sample_context):
        agent = PlannerAgent(sample_context)
        result = agent.execute(
            action="plan_rename",
            symbol="helper", new_name="util_helper",
        )
        assert result.success
        plan = result.data
        assert plan.title.startswith("Rename")
        assert "helper" in plan.title
        assert "util_helper" in plan.title
        assert len(plan.impacted_files) >= 2  # a.py and b.py
        assert plan.estimated_steps >= 2       # definition + reference

    def test_plan_remove(self, sample_context):
        # Add an unused symbol
        fC = FileNode(path="c.py", language="python")
        unused = Symbol(
            name="unused_func", kind=SymbolKind.FUNCTION,
            location=Location(file="c.py", line=1, column=0),
            qualified_name="unused_func",
        )
        fC.symbols["unused_func"] = unused
        sample_context.graph.add_file_node(fC)

        agent = PlannerAgent(sample_context)
        result = agent.execute(action="plan_remove", symbol="unused_func")
        assert result.success
        plan = result.data
        assert "SAFE" in plan.risk_assessment.upper()

    def test_plan_rename_with_reason(self, sample_context):
        agent = PlannerAgent(sample_context)
        result = agent.execute(
            action="plan_rename",
            symbol="helper", new_name="utils",
            reason="Standardize naming",
        )
        assert result.success
        assert "Standardize" in result.data.description


class TestExecutorAgent:
    def test_dry_run(self, sample_context):
        planner = PlannerAgent(sample_context)
        plan_result = planner.execute(
            action="plan_rename", symbol="helper", new_name="utils",
        )
        plan = plan_result.data

        executor = ExecutorAgent(sample_context)
        result = executor.execute(action="dry_run", plan=plan)
        assert result.success
        data = result.data
        assert data["total_steps"] >= 2
        assert len(data["preview"]) >= 2

    def test_preview(self, sample_context):
        planner = PlannerAgent(sample_context)
        plan_result = planner.execute(
            action="plan_rename", symbol="helper", new_name="util",
        )
        plan = plan_result.data

        executor = ExecutorAgent(sample_context)
        result = executor.execute(action="preview", plan=plan)
        assert result.success


class TestVerifierAgent:
    def test_integrity_check(self, sample_context):
        agent = VerifierAgent(sample_context)
        result = agent.execute(action="integrity_check")
        assert result.success
        data = result.data
        assert "status" in data
        assert "stats" in data

    def test_find_tests(self, sample_context):
        agent = VerifierAgent(sample_context)
        result = agent.execute(action="find_tests", symbol="helper")
        assert result.success
        data = result.data
        assert "test_files" in data

    def test_verify_plan(self, sample_context):
        planner = PlannerAgent(sample_context)
        plan_result = planner.execute(
            action="plan_rename", symbol="helper", new_name="util",
        )
        plan = plan_result.data

        agent = VerifierAgent(sample_context)
        result = agent.execute(action="verify_plan", plan=plan)
        assert result.success
        data = result.data
        assert "checks" in data
