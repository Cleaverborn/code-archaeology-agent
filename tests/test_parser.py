"""Tests for the Python parser."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_archaeology.languages.python import PythonParser
from code_archaeology.core.types import SymbolKind


class TestPythonParser:
    def test_parse_simple_function(self):
        parser = PythonParser()
        result = parser.parse_source("""
def hello(name: str) -> str:
    return f"Hello, {name}"
""")
        assert result.success
        fn = result.file_node
        # Should find the function
        func_syms = [s for s in fn.symbols.values() if s.kind == SymbolKind.FUNCTION]
        assert len(func_syms) >= 1
        func = func_syms[0]
        assert func.name == "hello"
        assert func.signature is not None
        assert "name" in func.signature

    def test_parse_class_with_methods(self):
        parser = PythonParser()
        result = parser.parse_source("""
class MyClass:
    def __init__(self, x):
        self.x = x

    def get_x(self) -> int:
        return self.x
""")
        assert result.success
        fn = result.file_node
        classes = [s for s in fn.symbols.values() if s.kind == SymbolKind.CLASS]
        assert len(classes) >= 1
        assert classes[0].name == "MyClass"

        methods = [s for s in fn.symbols.values() if s.kind == SymbolKind.METHOD]
        assert len(methods) >= 2

    def test_parse_imports(self):
        parser = PythonParser()
        result = parser.parse_source("""
import os
from typing import List, Optional
from .utils import helper
""")
        assert result.success
        fn = result.file_node
        assert "os" in fn.imports
        assert any("typing.List" in imp or "List" in imp for imp in fn.imports)

        import_syms = [s for s in fn.symbols.values() if s.kind == SymbolKind.IMPORT]
        assert len(import_syms) >= 3

    def test_parse_calls(self):
        parser = PythonParser()
        result = parser.parse_source("""
def foo():
    bar()
    baz.qux()
""")
        assert result.success
        fn = result.file_node
        # Should have references to bar and baz.qux
        call_refs = [r for r in fn.references if r.ref_type == "call"]
        assert len(call_refs) >= 2
        targets = [r.target_qualified_name for r in call_refs]
        assert "bar" in targets or any("bar" in t for t in targets)

    def test_parse_decorators(self):
        parser = PythonParser()
        result = parser.parse_source("""
@staticmethod
def my_method():
    pass
""")
        assert result.success
        fn = result.file_node
        decorator_refs = [r for r in fn.references if r.ref_type == "decorator"]
        assert len(decorator_refs) >= 1

    def test_parse_variables(self):
        parser = PythonParser()
        result = parser.parse_source("""
DEBUG = True
MAX_SIZE: int = 100
name = "test"
""")
        assert result.success
        fn = result.file_node
        consts = [s for s in fn.symbols.values() if s.kind == SymbolKind.CONSTANT]
        assert len(consts) >= 2
        const_names = [c.name for c in consts]
        assert "DEBUG" in const_names
        assert "MAX_SIZE" in const_names

    def test_parse_syntax_error(self):
        parser = PythonParser()
        result = parser.parse_source("def broken( ")
        assert not result.success

    def test_parse_visibility(self):
        parser = PythonParser()
        result = parser.parse_source("""
def _private():
    pass

def __very_private():
    pass

def public():
    pass
""")
        assert result.success
        fn = result.file_node
        syms = {s.name: s for s in fn.symbols.values() if s.kind == SymbolKind.FUNCTION}
        assert syms["_private"].visibility == "protected"
        assert syms["__very_private"].visibility == "private"
        assert syms["public"].visibility == "public"
