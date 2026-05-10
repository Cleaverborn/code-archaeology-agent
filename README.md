# Code Archaeology & Cross-File Refactoring Agent System

A multi-agent system for tracing long dependency chains across files, understanding code structure, and performing safe cross-file refactoring operations.

## Architecture

```
┌─────────────────────────────────────────────┐
│              Orchestrator                    │
│    (Central coordinator for all agents)      │
└──────────────┬──────────────────────────────┘
               │
   ┌───────────┼────────────┬────────────┐
   ▼           ▼            ▼            ▼
┌──────┐  ┌──────┐    ┌──────┐    ┌──────────┐
│Archae│  │Plan- │    │Exec- │    │Verifier  │
│ologist│  │ner   │    │utor  │    │          │
└──┬───┘  └──┬───┘    └──┬───┘    └────┬─────┘
   │         │            │             │
   └─────────┴────────────┴─────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   ┌────────┐  ┌──────────┐  ┌──────────┐
   │Parser  │  │Graph     │  │Symbol    │
   │Engine  │  │Engine    │  │Resolver  │
   └────────┘  └──────────┘  └──────────┘
```

### Agents

| Agent | Role |
|-------|------|
| **Archaeologist** | Traces long dependency chains, reconstructs code structure, maps call graphs |
| **Planner** | Designs safe multi-file refactoring plans with risk assessment |
| **Executor** | Applies refactoring plans with backup/rollback, dry-run preview |
| **Verifier** | Validates correctness via AST analysis, reference integrity, test discovery |

### Refactoring Operations

| Operation | Description |
|-----------|-------------|
| **Rename** | Cross-file symbol renaming, updating all references |
| **Extract** | Extract code blocks into new functions with parameter inference |
| **Move** | Move symbols between files, updating all imports |
| **Change Signature** | Modify function signatures, adapt all call sites |
| **Remove** | Safe removal of unused symbols |
| **Inline** | Inline function calls with their body |

## Quick Start

### Installation

```bash
pip install -e .
```

### Command Line

```bash
# Build the dependency graph and run archaeology on a symbol
code-archaeology --dir /path/to/project archaeology my_function

# Trace downstream impact (who depends on this?)
code-archaeology --dir /path/to/project trace my_function --direction downstream

# Full impact analysis
code-archaeology --dir /path/to/project impact my_function

# Dry-run a cross-file rename
code-archaeology --dir /path/to/project rename old_name new_name

# Apply a rename with backup
code-archaeology --dir /path/to/project rename old_name new_name --execute --backup

# Extract a code block to a function
code-archaeology --dir . extract src/main.py 42 58 new_helper

# Move a symbol to another file
code-archaeology --dir . move MyClass src/new_module.py

# Change a function signature
code-archaeology --dir . change-sig process_data name age email

# Find circular dependencies
code-archaeology --dir . circular

# Full integrity check
code-archaeology --dir . integrity

# Codebase statistics
code-archaeology --dir . stats
```

### Python API

```python
from code_archaeology import Orchestrator

# Initialize and build the graph
orch = Orchestrator("/path/to/project")
orch.build_graph()

# Archaeology
report = orch.archaeology("my_function")
impact = orch.impact_analysis("MyClass")

# Trace dependencies
downstream = orch.trace("my_function", direction="downstream")
upstream = orch.trace("my_function", direction="upstream")

# Plan a rename
plan = orch.plan_rename("old_name", "new_name")

# Preview changes
preview = orch.execute(plan, dry_run=True)

# Apply with backup
result = orch.execute(plan, dry_run=False, create_backup=True)

# Verify
check = orch.verify(plan)

# Integrity check
integrity = orch.integrity_check()

# Find tests
tests = orch.find_tests("my_function")
```

## Run the Demo

```bash
python examples/demo.py
```

## Run Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Supported Languages

- **Python** (.py, .pyi) — full AST-based parsing with type annotations, decorators, import resolution
- Architecture supports adding more languages via the `LanguageParser` interface

## Core Concepts

### Dependency Graph

The system builds a directed graph where:
- **Nodes** = symbols (functions, classes, variables) and files
- **Edges** = calls, imports, inheritance, type references

### Chain Tracing

- **Downstream** (impact): "Who depends on this symbol?"
- **Upstream** (dependencies): "What does this symbol depend on?"
- **Transitive closure**: Full chains up to configurable depth

### Risk Assessment

Each refactoring operation is assigned a risk level:
- **SAFE** — no external references, isolated change
- **LOW** — private/protected symbol, few references
- **MEDIUM** — public API, moderate reference count
- **HIGH** — widely-used interface, many references
- **CRITICAL** — core framework API, very broad impact

## License

MIT
