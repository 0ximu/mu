"""MU kernel export command - Export graph in various formats."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("export")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--format",
    "-f",
    "export_format",
    type=click.Choice(["mu", "json", "mermaid", "d2", "cytoscape"]),
    default="mu",
    help="Export format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
@click.option(
    "--nodes",
    "-n",
    type=str,
    help="Comma-separated node IDs to export",
)
@click.option(
    "--types",
    "-t",
    type=str,
    help="Comma-separated node types (module,class,function,external)",
)
@click.option(
    "--max-nodes",
    "-m",
    type=int,
    help="Maximum nodes to export",
)
@click.option(
    "--list-formats",
    is_flag=True,
    help="List available export formats",
)
@click.option(
    "--direction",
    type=str,
    help="Diagram direction: TB/LR for mermaid, right/down for d2",
)
@click.option(
    "--diagram-type",
    type=click.Choice(["flowchart", "classDiagram"]),
    default="flowchart",
    help="Mermaid diagram type",
)
@click.option(
    "--no-edges",
    is_flag=True,
    help="Exclude edges from export",
)
@click.option(
    "--pretty/--compact",
    default=True,
    help="Pretty-print JSON output",
)
def kernel_export(
    path: Path,
    export_format: str,
    output: Path | None,
    nodes: str | None,
    types: str | None,
    max_nodes: int | None,
    list_formats: bool,
    direction: str | None,
    diagram_type: str,
    no_edges: bool,
    pretty: bool,
) -> None:
    """Export the graph in various formats.

    Exports the MUbase graph to different output formats for visualization,
    integration, or LLM consumption.

    \b
    Examples:
        mu kernel export . --format mu > system.mu
        mu kernel export . --format json -o graph.json
        mu kernel export . --format mermaid --types class,function
        mu kernel export . --format d2 --max-nodes 50 --direction down
        mu kernel export . --format cytoscape -o viz.cyjs
        mu kernel export . --list-formats
    """
    from mu.errors import ExitCode
    from mu.kernel import MUbase, NodeType
    from mu.kernel.export import ExportOptions, get_default_manager
    from mu.logging import console, print_error, print_info, print_success, print_warning

    # Handle --list-formats
    if list_formats:
        manager = get_default_manager()
        print_info("Available export formats:")
        for fmt in manager.list_exporters():
            print_info(f"  {fmt['name']:12} - {fmt['description']} ({fmt['extension']})")
        return

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    try:
        # Parse node IDs
        node_ids = None
        if nodes:
            node_ids = [n.strip() for n in nodes.split(",") if n.strip()]

        # Parse node types
        node_types = None
        if types:
            type_strs = [t.strip().lower() for t in types.split(",") if t.strip()]
            node_types = []
            for ts in type_strs:
                try:
                    node_types.append(NodeType(ts))
                except ValueError:
                    print_warning(f"Unknown node type: {ts}")

        # Build extra options based on format
        extra: dict[str, str | bool] = {}

        if export_format == "mermaid":
            extra["diagram_type"] = diagram_type
            if direction:
                extra["direction"] = direction

        elif export_format == "d2":
            if direction:
                extra["direction"] = direction

        elif export_format == "json":
            extra["pretty"] = pretty

        # Build export options
        options = ExportOptions(
            node_ids=node_ids,
            node_types=node_types,
            max_nodes=max_nodes,
            include_edges=not no_edges,
            extra=extra,
        )

        # Export
        manager = get_default_manager()
        result = manager.export(db, export_format, options)

        if not result.success:
            print_error(f"Export failed: {result.error}")
            sys.exit(ExitCode.FATAL_ERROR)

        # Output
        if output:
            output.write_text(result.output)
            print_success(
                f"Exported {result.node_count} nodes, {result.edge_count} edges to {output}"
            )
        else:
            console.print(result.output)

    finally:
        db.close()


__all__ = ["kernel_export"]
