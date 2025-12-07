"""MU kernel deps command - Show dependencies of a node."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("deps")
@click.argument("node_name", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Depth of dependency traversal",
)
@click.option("--reverse", "-r", is_flag=True, help="Show dependents instead of dependencies")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_deps(
    node_name: str,
    path: Path,
    depth: int,
    reverse: bool,
    as_json: bool,
) -> None:
    """Show dependencies or dependents of a node.

    NODE_NAME can be a function, class, or module name.

    Examples:

        mu kernel deps MUbase

        mu kernel deps cli.py --depth 2

        mu kernel deps GraphBuilder --reverse
    """
    import json as json_module

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import console, print_error, print_info

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    # Find the node by name
    matching_nodes = db.find_by_name(f"%{node_name}%")

    if not matching_nodes:
        print_error(f"No node found matching '{node_name}'")
        db.close()
        sys.exit(ExitCode.CONFIG_ERROR)

    # Use the first match
    target_node = matching_nodes[0]
    if len(matching_nodes) > 1:
        print_info(
            f"Multiple matches found, using: {target_node.qualified_name or target_node.name}"
        )

    # Get dependencies or dependents
    if reverse:
        related = db.get_dependents(target_node.id, depth=depth)
        relation_type = "Dependents"
    else:
        related = db.get_dependencies(target_node.id, depth=depth)
        relation_type = "Dependencies"

    db.close()

    if as_json:
        result = {
            "node": target_node.to_dict(),
            "relation": "dependents" if reverse else "dependencies",
            "depth": depth,
            "related": [n.to_dict() for n in related],
        }
        console.print(json_module.dumps(result, indent=2))
        return

    print_info(
        f"{relation_type} of {target_node.qualified_name or target_node.name} (depth={depth}):"
    )

    if not related:
        print_info("  (none)")
        return

    for node in related:
        prefix = "  "
        type_str = f"[{node.type.value}]"
        name_str = node.qualified_name or node.name
        print_info(f"{prefix}{type_str} {name_str}")


__all__ = ["kernel_deps"]
