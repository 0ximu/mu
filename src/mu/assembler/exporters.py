"""Output format exporters for assembled MU output."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from mu.assembler import AssembledOutput
from mu.reducer.generator import MUGenerator


def export_json(
    output: AssembledOutput,
    include_full_graph: bool = True,
    pretty: bool = True,
) -> str:
    """Export assembled output as JSON.

    Args:
        output: The assembled output to export
        include_full_graph: Include full module graph details
        pretty: Pretty-print with indentation

    Returns:
        JSON string
    """
    data: dict[str, Any] = {
        "version": "1.0",
        "format": "mu-json",
        "generated": datetime.now(UTC).isoformat(),
        "source": output.codebase.source,
        "stats": output.codebase.stats,
    }

    # Module graph summary
    data["module_graph"] = {
        "internal_dependencies": output.codebase.dependency_graph,
        "external_packages": sorted(output.external_packages),
        "topological_order": output.topological_order,
    }

    # Include dynamic dependencies if present
    if output.codebase.dynamic_dependencies:
        data["module_graph"]["dynamic_imports"] = [
            {
                "module": d.module_name,
                "pattern": d.pattern,
                "source": d.source,
                "line": d.line,
                "resolved_target": d.resolved_target,
            }
            for d in output.codebase.dynamic_dependencies
        ]

    # Full graph details if requested
    if include_full_graph:
        data["module_graph"]["nodes"] = {
            path: node.to_dict()
            for path, node in output.graph.nodes.items()
        }
        data["module_graph"]["edges"] = [
            {"from": f, "to": t, "type": d.value}
            for f, t, d in output.graph.edges
        ]

    # Modules
    data["modules"] = []
    for module in output.codebase.modules:
        mod_data = {
            "name": module.name,
            "path": module.path,
            "language": module.language,
            "imports": [imp.to_dict() for imp in module.imports],
            "classes": [cls.to_dict() for cls in module.classes],
            "functions": [func.to_dict() for func in module.functions],
        }

        # Add node info if available
        if module.path in output.graph.nodes:
            node = output.graph.nodes[module.path]
            mod_data["internal_deps"] = node.internal_deps
            mod_data["external_deps"] = node.external_deps
            mod_data["exports"] = node.exports

        if module.needs_llm:
            mod_data["needs_llm_summary"] = module.needs_llm
        if module.summaries:
            mod_data["summaries"] = module.summaries

        data["modules"].append(mod_data)

    indent = 2 if pretty else None
    return json.dumps(data, indent=indent)


def export_markdown(output: AssembledOutput) -> str:
    """Export assembled output as Markdown.

    Args:
        output: The assembled output to export

    Returns:
        Markdown string
    """
    lines: list[str] = []

    # Header
    lines.append("# MU Codebase Analysis")
    lines.append("")
    lines.append(f"**Source:** `{output.codebase.source}`")
    lines.append(f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")

    # Stats
    stats = output.codebase.stats
    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Modules | {stats.get('total_modules', 0)} |")
    lines.append(f"| Classes | {stats.get('total_classes', 0)} |")
    lines.append(f"| Functions | {stats.get('total_functions', 0)} |")
    lines.append(f"| Methods | {stats.get('total_methods', 0)} |")
    lines.append(f"| Internal Dependencies | {stats.get('internal_dependencies', 0)} |")
    lines.append(f"| External Packages | {stats.get('external_packages', 0)} |")
    lines.append(f"| Dynamic Imports | {stats.get('dynamic_imports', 0)} |")
    lines.append("")

    # External packages
    if output.external_packages:
        lines.append("## External Dependencies")
        lines.append("")
        packages = sorted(output.external_packages)
        for pkg in packages:
            lines.append(f"- `{pkg}`")
        lines.append("")

    # Module dependency graph
    if output.codebase.dependency_graph:
        lines.append("## Module Dependency Graph")
        lines.append("")
        lines.append("```")
        for module_name, deps in sorted(output.codebase.dependency_graph.items()):
            if deps:
                deps_str = ", ".join(deps)
                lines.append(f"{module_name} -> {deps_str}")
        lines.append("```")
        lines.append("")

    # Dynamic imports
    if output.codebase.dynamic_dependencies:
        lines.append("## Dynamic Imports")
        lines.append("")
        lines.append("⚠️ *These imports are resolved at runtime and may not be fully traceable.*")
        lines.append("")
        lines.append("| Module | Pattern | Source | Line |")
        lines.append("|--------|---------|--------|------|")
        for dyn in output.codebase.dynamic_dependencies:
            pattern = dyn.pattern or dyn.resolved_target or "-"
            source = dyn.source or "-"
            line = str(dyn.line) if dyn.line else "-"
            lines.append(f"| `{dyn.module_name}` | `{pattern}` | {source} | {line} |")
        lines.append("")

    # Modules
    lines.append("## Modules")
    lines.append("")

    for module in output.codebase.modules:
        lines.append(f"### {module.name}")
        lines.append("")
        lines.append(f"**File:** `{module.path}`")
        lines.append(f"**Language:** {module.language}")
        lines.append("")

        # Dependencies from graph
        if module.path in output.graph.nodes:
            node = output.graph.nodes[module.path]
            if node.internal_deps:
                dep_names = []
                for dep_path in node.internal_deps:
                    if dep_path in output.graph.nodes:
                        dep_names.append(output.graph.nodes[dep_path].name)
                if dep_names:
                    lines.append(f"**Internal deps:** {', '.join(dep_names)}")
            if node.external_deps:
                lines.append(f"**External deps:** {', '.join(node.external_deps)}")
            lines.append("")

        # Classes
        if module.classes:
            lines.append("#### Classes")
            lines.append("")
            for cls in module.classes:
                bases = f" < {', '.join(cls.bases)}" if cls.bases else ""
                lines.append(f"- **{cls.name}**{bases}")
                for method in cls.methods:
                    ret = f" -> {method.return_type}" if method.return_type else ""
                    params = ", ".join(p.name for p in method.parameters)
                    async_prefix = "async " if method.is_async else ""
                    lines.append(f"  - `{async_prefix}{method.name}({params}){ret}`")
            lines.append("")

        # Functions
        if module.functions:
            lines.append("#### Functions")
            lines.append("")
            for func in module.functions:
                ret = f" -> {func.return_type}" if func.return_type else ""
                params = ", ".join(p.name for p in func.parameters)
                async_prefix = "async " if func.is_async else ""
                lines.append(f"- `{async_prefix}{func.name}({params}){ret}`")
            lines.append("")

    return "\n".join(lines)


def export_mu(output: AssembledOutput, shell_safe: bool = False) -> str:
    """Export assembled output as MU format.

    Args:
        output: The assembled output to export
        shell_safe: Escape sigils for shell safety

    Returns:
        MU format string
    """
    generator = MUGenerator(shell_safe=shell_safe)
    return generator.generate(output.codebase)


__all__ = ["export_json", "export_markdown", "export_mu"]
