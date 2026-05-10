"""Tests for core types and graph engine."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from code_archaeology.core.types import (
    Symbol, SymbolKind, Reference, Location,
    FileNode, DependencyGraph, ImportEdge, CallEdge,
)
from code_archaeology.core.graph import GraphEngine
from code_archaeology.languages.python import PythonParser


class TestSymbolAndReference:
    def test_symbol_creation(self):
        loc = Location(file="test.py", line=10, column=5)
        sym = Symbol(
            name="my_func", kind=SymbolKind.FUNCTION,
            location=loc, qualified_name="mymod.my_func",
            signature="def my_func(x: int) -> str",
        )
        assert sym.name == "my_func"
        assert sym.kind == SymbolKind.FUNCTION
        assert sym.location.line == 10
        assert sym.qualified_name == "mymod.my_func"

    def test_symbol_equality(self):
        loc1 = Location(file="a.py", line=1, column=0)
        loc2 = Location(file="a.py", line=1, column=0)
        s1 = Symbol(name="f", kind=SymbolKind.FUNCTION, location=loc1, qualified_name="a.f")
        s2 = Symbol(name="f", kind=SymbolKind.FUNCTION, location=loc2, qualified_name="a.f")
        assert s1 == s2

    def test_reference_creation(self):
        loc = Location(file="caller.py", line=20, column=10)
        source = Symbol(name="caller", kind=SymbolKind.FUNCTION, location=loc,
                        qualified_name="m.caller")
        ref = Reference(
            source=source,
            target_qualified_name="m.callee",
            location=loc,
            ref_type="call",
        )
        assert ref.target_qualified_name == "m.callee"
        assert ref.ref_type == "call"


class TestDependencyGraph:
    def test_add_file_node(self):
        g = DependencyGraph()
        fn = FileNode(path="test.py", language="python")
        sym = Symbol(name="f", kind=SymbolKind.FUNCTION,
                     location=Location(file="test.py", line=1, column=0),
                     qualified_name="f")
        fn.symbols["f"] = sym
        g.add_file_node(fn)
        assert g.get_symbol("f") == sym

    def test_find_references(self):
        g = DependencyGraph()
        fn = FileNode(path="test.py")
        sym = Symbol(name="caller", kind=SymbolKind.FUNCTION,
                     location=Location(file="test.py", line=1, column=0),
                     qualified_name="caller")
        ref = Reference(source=sym, target_qualified_name="callee",
                        location=Location(file="test.py", line=2, column=4))
        fn.references.append(ref)
        fn.symbols["caller"] = sym
        g.add_file_node(fn)

        found = g.find_references("callee")
        assert len(found) == 1
        assert found[0].target_qualified_name == "callee"

    def test_get_impacted_files(self):
        g = DependencyGraph()
        fn1 = FileNode(path="a.py")
        s1 = Symbol(name="target", kind=SymbolKind.FUNCTION,
                    location=Location(file="a.py", line=1, column=0),
                    qualified_name="target")
        fn1.symbols["target"] = s1

        fn2 = FileNode(path="b.py")
        s2 = Symbol(name="caller", kind=SymbolKind.FUNCTION,
                    location=Location(file="b.py", line=1, column=0),
                    qualified_name="caller")
        r2 = Reference(source=s2, target_qualified_name="target",
                       location=Location(file="b.py", line=5, column=4))
        fn2.references.append(r2)
        fn2.symbols["caller"] = s2

        g.add_file_node(fn1)
        g.add_file_node(fn2)

        impacted = g.get_impacted_files("target")
        assert "a.py" in impacted
        assert "b.py" in impacted

    def test_transitive_dependents(self):
        g = DependencyGraph()
        # A -> B -> C
        for name, refs in [("a", ["b"]), ("b", ["c"]), ("c", [])]:
            fn = FileNode(path=f"{name}.py")
            sym = Symbol(name=name, kind=SymbolKind.FUNCTION,
                         location=Location(file=f"{name}.py", line=1, column=0),
                         qualified_name=name)
            fn.symbols[name] = sym
            for t in refs:
                fn.references.append(Reference(
                    source=sym, target_qualified_name=t,
                    location=Location(file=f"{name}.py", line=2, column=0),
                ))
            g.add_file_node(fn)

        deps = g.transitive_dependents("c")
        assert "b" in deps
        assert "a" in deps


class TestGraphEngine:
    def test_find_hub_symbols(self):
        g = DependencyGraph()
        fn1 = FileNode(path="hub.py")
        hub = Symbol(name="hub", kind=SymbolKind.FUNCTION,
                     location=Location(file="hub.py", line=1, column=0),
                     qualified_name="hub")
        fn1.symbols["hub"] = hub
        g.add_file_node(fn1)

        for i in range(5):
            fn = FileNode(path=f"leaf{i}.py")
            sym = Symbol(name=f"leaf{i}", kind=SymbolKind.FUNCTION,
                         location=Location(file=f"leaf{i}.py", line=1, column=0),
                         qualified_name=f"leaf{i}")
            fn.symbols[f"leaf{i}"] = sym
            fn.references.append(Reference(
                source=sym, target_qualified_name="hub",
                location=Location(file=f"leaf{i}.py", line=2, column=0),
            ))
            g.add_file_node(fn)

        engine = GraphEngine(g)
        engine.build_indices()
        hubs = engine.find_hub_symbols(5)
        assert hubs[0][0] == "hub"
        assert hubs[0][1] > 0

    def test_detect_cycles(self):
        g = DependencyGraph()
        # A -> B -> C -> A
        for src, tgt in [("A", "B"), ("B", "C"), ("C", "A")]:
            g.add_call_edge(CallEdge(
                caller=src, callee=tgt,
                location=Location(file="x.py", line=1, column=0),
            ))

        engine = GraphEngine(g)
        engine.build_indices()
        cycles = engine.detect_cycles()
        assert len(cycles) > 0

    def test_shortest_path(self):
        g = DependencyGraph()
        for src, tgt in [("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")]:
            g.add_call_edge(CallEdge(
                caller=src, callee=tgt,
                location=Location(file="x.py", line=1, column=0),
            ))

        engine = GraphEngine(g)
        engine.build_indices()
        path = engine.shortest_path("A", "D")
        assert path is not None
        assert path[0] == "A"
        assert path[-1] == "D"
        # Shortest should be direct A->D
        assert path == ["A", "D"]
