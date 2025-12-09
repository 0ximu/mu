"""mu deps - Show dependencies for a node (promoted from kernel deps)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


@click.command("deps")
@click.argument("node", type=str)
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Traversal depth",
)
@click.option(
    "--reverse",
    "-r",
    is_flag=True,
    help="Show dependents instead of dependencies",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase",
)
def deps(
    node: str,
    depth: int,
    reverse: bool,
    as_json: bool,
    path: Path,
) -> None:
    """Show what NODE depends on (or what depends on it with --reverse).

    NODE can be a function, class, or module name.

    \b
    Examples:
        mu deps AuthService           # What does AuthService depend on?
        mu deps cli.py --depth 2      # Dependencies 2 levels deep
        mu deps GraphBuilder -r       # What depends on GraphBuilder?
        mu deps MUbase --json         # Output as JSON
    """
    import json as json_module

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import console, print_error, print_info

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Try daemon first to avoid database locking
    client = DaemonClient()
    if client.is_running():
        try:
            direction = "incoming" if reverse else "outgoing"
            result = client.deps(node, depth=depth, direction=direction, cwd=str(path))

            if as_json:
                console.print(json_module.dumps(result, indent=2))
            else:
                relation_type = "Dependents" if reverse else "Dependencies"
                deps_list = result.get("dependencies", [])
                print_info(f"{relation_type} of {node} (depth={depth}):")
                if not deps_list:
                    print_info("  (none)")
                else:
                    for dep in deps_list:
                        if isinstance(dep, dict):
                            type_str = f"[{dep.get('type', 'unknown')}]"
                            name_str = dep.get("qualified_name") or dep.get("name", str(dep))
                        else:
                            type_str = ""
                            name_str = str(dep)
                        print_info(f"  {type_str} {name_str}")
            return
        except DaemonError:
            # Fall through to local database access
            pass
        finally:
            client.close()

    # Fallback to direct database access
    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked by the daemon. The daemon should be routing queries, but isn't responding."
        )
        print_info("Try: mu serve --stop && mu serve")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Find the node by name
    matching_nodes = db.find_by_name(f"%{node}%")

    if not matching_nodes:
        print_error(f"No node found matching '{node}'")
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

    for n in related:
        prefix = "  "
        type_str = f"[{n.type.value}]"
        name_str = n.qualified_name or n.name
        print_info(f"{prefix}{type_str} {name_str}")


__all__ = ["deps"]
