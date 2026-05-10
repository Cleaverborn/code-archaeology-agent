"""
Code Archaeology & Cross-File Refactoring Agent System.

A multi-agent system for tracing long dependency chains across files,
understanding code evolution, and performing safe cross-file refactoring.
"""

__version__ = "1.0.0"
__author__ = "Code Archaeology Team"

from .orchestrator import Orchestrator
from .core.types import Symbol, Reference, FileNode, DependencyGraph
from .core.graph import GraphEngine

__all__ = [
    "Orchestrator",
    "Symbol",
    "Reference",
    "FileNode",
    "DependencyGraph",
    "GraphEngine",
]
