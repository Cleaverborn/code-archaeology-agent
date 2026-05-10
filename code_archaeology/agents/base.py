"""Base agent interface for the multi-agent system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.types import DependencyGraph
from ..core.graph import GraphEngine
from ..core.resolver import SymbolResolver


@dataclass
class AgentContext:
    """Shared context passed between agents."""
    graph: DependencyGraph
    engine: GraphEngine
    resolver: SymbolResolver
    root_dir: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Read file content if available in the graph."""
        node = self.graph.file_nodes.get(file_path)
        if node and node.lines:
            return "\n".join(node.lines)
        return None


@dataclass
class AgentResult:
    """Result returned by any agent."""
    success: bool
    data: Any = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    agent_name: str = ""


class BaseAgent(ABC):
    """Abstract base for all agents in the system."""

    name: str = "base"

    def __init__(self, context: AgentContext) -> None:
        self.context = context

    @abstractmethod
    def execute(self, **kwargs) -> AgentResult:
        """Execute the agent's primary task."""

    def log(self, message: str) -> None:
        """Log a message (can be overridden for custom logging)."""
        print(f"[{self.name}] {message}")

    def _ok(self, data: Any = None, **kwargs) -> AgentResult:
        return AgentResult(success=True, data=data, agent_name=self.name, **kwargs)

    def _err(self, errors: list[str], **kwargs) -> AgentResult:
        return AgentResult(success=False, errors=errors, agent_name=self.name, **kwargs)
