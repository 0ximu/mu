"""MU Core Commands - Streamlined top-level commands.

These commands mirror the MCP tools for consistency:
- mu bootstrap  -> mu_bootstrap
- mu status     -> mu_status
- mu read       -> mu_read
- mu context    -> mu_context
- mu search     -> mu_search
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from mu.paths import find_mubase_path, get_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext
    from mu.kernel import MUbase


def _resolve_node_id_local(db: MUbase, node_ref: str, root_path: Path) -> str | None:
    """Resolve a node reference to a full node ID (local mode).

    Handles:
    - Full node IDs: mod:src/cli.py, cls:src/file.py:ClassName
    - Simple names: MUbase, AuthService
    - File paths: src/hooks/useTransactions.ts -> mod:...
    - Absolute paths: /Users/.../src/auth.py -> mod:...

    Args:
        db: MUbase instance
        node_ref: Node reference (ID, name, or file path)
        root_path: Project root path for resolving relative paths

    Returns:
        Resolved node ID or None if not found
    """
    # If it already looks like a full node ID, verify it exists
    if node_ref.startswith(("mod:", "cls:", "fn:")):
        if db.get_node(node_ref):
            return node_ref
        return None

    # Try exact name match first
    nodes = db.find_by_name(node_ref)
    if nodes:
        # Prefer exact match
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    # Check if it looks like a file path
    looks_like_path = (
        "/" in node_ref
        or "\\" in node_ref
        or node_ref.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
    )

    if looks_like_path:
        ref_path = Path(node_ref)

        # If absolute path, try to make it relative to root
        if ref_path.is_absolute():
            try:
                ref_path = ref_path.relative_to(root_path)
            except ValueError:
                pass  # Not relative to root

        # Normalize path separators
        normalized_path = str(ref_path).replace("\\", "/")

        # Try to find module with this path
        result = db.conn.execute(
            "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 1",
            [f"%{normalized_path}"],
        ).fetchone()

        if result:
            return str(result[0])

        # Also try constructing the node ID directly
        possible_id = f"mod:{normalized_path}"
        if db.get_node(possible_id):
            return possible_id

    # Try fuzzy match on name
    nodes = db.find_by_name(f"%{node_ref}%")
    if nodes:
        # Prefer exact name matches
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    return None


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Force rebuild even if .mu/mubase exists")
@click.option(
    "--embed/--no-embed",
    default=False,
    help="Generate embeddings for semantic search",
)
@click.pass_obj
def bootstrap(ctx: MUContext, path: Path, force: bool, embed: bool) -> None:
    """Bootstrap MU for a codebase in one step.

    This single command:

    \b
    1. Creates .murc.toml config if missing
    2. Builds the .mu/mubase code graph
    3. Optionally generates embeddings

    Safe to run multiple times. Use --force to rebuild.

    \b
    Examples:
        mu bootstrap              # Bootstrap current directory
        mu bootstrap ./my-project # Bootstrap specific path
        mu bootstrap --embed      # Include embeddings for semantic search
        mu bootstrap --force      # Force rebuild
    """
    import time

    from mu.config import MUConfig, get_default_config_toml
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import print_error, print_info, print_success, print_warning
    from mu.parser.base import parse_file
    from mu.scanner import SUPPORTED_LANGUAGES, scan_codebase_auto

    start_time = time.time()
    root_path = path.resolve()
    config_path = root_path / ".murc.toml"
    mubase_path = get_mubase_path(root_path)

    # Step 1: Ensure config exists
    if not config_path.exists():
        try:
            config_path.write_text(get_default_config_toml())
            print_success(f"Created {config_path}")
        except PermissionError:
            print_error(f"Permission denied: {config_path}")
            sys.exit(ExitCode.CONFIG_ERROR)

    # Step 2: Check if rebuild is needed
    if mubase_path.exists() and not force:
        db = MUbase(mubase_path)
        try:
            stats = db.stats()
            print_success(f"MU ready. Graph exists: {stats['nodes']} nodes, {stats['edges']} edges")
            print_info("Use --force to rebuild")
            return
        finally:
            db.close()

    # Step 3: Load config and scan
    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    if ctx.config is None:
        ctx.config = config

    print_info(f"Scanning {root_path}...")
    scan_result = scan_codebase_auto(root_path, config)

    if not scan_result.files:
        print_warning("No supported files found")
        sys.exit(1)

    print_info(f"Found {len(scan_result.files)} files")

    # Step 4: Parse all files
    print_info("Parsing files...")
    modules = []
    errors = 0

    for file_info in scan_result.files:
        if file_info.language not in SUPPORTED_LANGUAGES:
            continue
        parsed = parse_file(Path(root_path / file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)
        elif parsed.error:
            errors += 1

    if errors > 0 and ctx.verbosity == "verbose":
        print_warning(f"  {errors} files had parse errors")

    if not modules:
        print_warning("No modules parsed successfully")
        sys.exit(1)

    print_info(f"Parsed {len(modules)} modules")

    # Step 5: Build graph
    print_info("Building graph...")
    db = MUbase(mubase_path)
    db.build(modules, root_path)
    stats = db.stats()

    duration_ms = (time.time() - start_time) * 1000

    print_success(
        f"Built graph: {stats['nodes']} nodes, {stats['edges']} edges in {duration_ms:.0f}ms"
    )

    # Show breakdown
    if ctx.verbosity != "quiet":
        for node_type, count in stats.get("nodes_by_type", {}).items():
            print_info(f"  {node_type}: {count}")

    # Step 6: Generate embeddings if requested
    if embed:
        import asyncio

        from mu.kernel import NodeType
        from mu.kernel.embeddings import EmbeddingService
        from mu.logging import create_progress

        print_info("\nGenerating embeddings...")

        nodes = []
        for node_type in [NodeType.MODULE, NodeType.CLASS, NodeType.FUNCTION]:
            nodes.extend(db.get_nodes(node_type))

        if nodes:
            service = EmbeddingService(config=config.embeddings, provider="local")

            async def run_embedding() -> list:  # type: ignore[type-arg]
                with create_progress() as progress:
                    task = progress.add_task("Generating embeddings...", total=len(nodes))

                    def on_progress(completed: int, total: int) -> None:
                        progress.update(task, completed=completed)

                    result = await service.embed_nodes(
                        nodes, batch_size=100, on_progress=on_progress
                    )
                    return result

            embeddings = asyncio.run(run_embedding())
            db.add_embeddings_batch(embeddings)

            embed_stats = db.embedding_stats()
            print_success(
                f"Generated {len(embeddings)} embeddings ({embed_stats['coverage_percent']:.1f}% coverage)"
            )

            asyncio.run(service.close())

    db.close()

    print_info("\nNext steps:")
    print_info("  mu query 'SELECT * FROM functions LIMIT 5'")
    print_info("  mu context 'How does authentication work?'")
    print_info("  mu impact AuthService")


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def status(ctx: MUContext, as_json: bool) -> None:
    """Show MU status and next recommended action.

    Checks configuration, graph database, and embeddings status.
    Provides actionable guidance for what to do next.

    \b
    Examples:
        mu status         # Human-readable status
        mu status --json  # JSON output for scripts
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_info, print_success, print_warning

    cwd = Path.cwd()
    config_exists = (cwd / ".murc.toml").exists()

    # Find mubase
    mubase_path = find_mubase_path(cwd)

    embeddings_exist = False
    stats = {}
    next_action = None
    message = ""
    daemon_running = False

    # Try daemon first (no lock)
    client = DaemonClient()
    if client.is_running():
        daemon_running = True
        try:
            daemon_status = client.status(cwd=str(cwd))
            stats = daemon_status.get("stats", {})
            if mubase_path:
                embeddings_db = mubase_path.parent / ".mu-embeddings.db"
                embeddings_exist = embeddings_db.exists()

            if not embeddings_exist:
                next_action = "mu bootstrap --embed"
                message = "MU ready. Run 'mu bootstrap --embed' to enable semantic search."
            else:
                next_action = None
                message = "MU ready. All systems operational."
        except DaemonError as e:
            print_warning(f"Daemon query failed: {e}")
            daemon_running = False

    # Fallback to direct MUbase access
    if not daemon_running:
        if mubase_path:
            embeddings_db = mubase_path.parent / ".mu-embeddings.db"
            embeddings_exist = embeddings_db.exists()

            from mu.kernel import MUbase, MUbaseLockError

            try:
                db = MUbase(mubase_path, read_only=True)
                try:
                    stats = db.stats()
                finally:
                    db.close()
            except MUbaseLockError:
                # Database locked - daemon might be running but we couldn't connect
                stats = {}
                message = "Database locked. Start daemon with 'mu daemon start' for queries."

            if not embeddings_exist:
                next_action = "mu bootstrap --embed"
                message = (
                    message or "MU ready. Run 'mu bootstrap --embed' to enable semantic search."
                )
            else:
                next_action = None
                message = message or "MU ready. All systems operational."
        else:
            next_action = "mu bootstrap"
            message = "No .mu/mubase found. Run 'mu bootstrap' to initialize."

    result = {
        "daemon_running": daemon_running,
        "config_exists": config_exists,
        "mubase_exists": mubase_path is not None,
        "mubase_path": str(mubase_path) if mubase_path else None,
        "embeddings_exist": embeddings_exist,
        "stats": stats,
        "next_action": next_action,
        "message": message,
    }

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        if mubase_path:
            print_success("MU Status: Ready")
            if daemon_running:
                print_info("  Daemon: Running")
            print_info(f"  Database: {mubase_path}")
            print_info(f"  Nodes: {stats.get('nodes', 0)}")
            print_info(f"  Edges: {stats.get('edges', 0)}")
            if embeddings_exist:
                print_info("  Embeddings: Yes")
            else:
                print_warning("  Embeddings: No (run 'mu bootstrap --embed')")
        else:
            print_warning("MU Status: Not initialized")
            print_info(f"  Config: {'Yes' if config_exists else 'No'}")

        if next_action:
            print_info(f"\nNext action: {next_action}")


@click.command()
@click.argument("node_id")
@click.option("--context", "-c", "context_lines", default=3, help="Lines of context before/after")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def read(ctx: MUContext, node_id: str, context_lines: int, as_json: bool) -> None:
    """Read source code for a specific node.

    Closes the find->read loop: after finding nodes with 'mu query',
    use 'mu read' to see the actual source code.

    \b
    Examples:
        mu read AuthService                    # Read by name
        mu read 'cls:src/auth.py:AuthService'  # Read by full ID
        mu read AuthService --context 10       # More context lines
        mu read AuthService --json             # JSON output
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_error, print_info

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # Helper to read source from node data
    def _read_source(
        node_data: dict[str, Any],
        resolved_id: str,
        root_path: Path,
    ) -> dict[str, Any]:
        file_path_str = node_data.get("file_path")
        line_start = node_data.get("line_start")
        line_end = node_data.get("line_end")
        node_type = node_data.get("node_type", node_data.get("type", ""))

        if not file_path_str or not line_start or not line_end:
            missing = []
            if not file_path_str:
                missing.append("file_path")
            if not line_start:
                missing.append("line_start")
            if not line_end:
                missing.append("line_end")

            if node_type == "external":
                hint = "(external dependencies don't have source)"
            elif not file_path_str:
                hint = '(try: mu query "SELECT * FROM nodes WHERE file_path IS NOT NULL")'
            else:
                hint = f"(file: {file_path_str} - try reading the file directly)"

            print_error(
                f"Node '{node_id}' has no source location (missing: {', '.join(missing)}) {hint}"
            )
            sys.exit(1)

        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = root_path / file_path

        if not file_path.exists():
            print_error(f"Source file not found: {file_path}")
            sys.exit(1)

        lines = file_path.read_text().splitlines()
        total_lines = len(lines)

        start_idx = line_start - 1
        end_idx = line_end

        context_start = max(0, start_idx - context_lines)
        context_end = min(total_lines, end_idx + context_lines)

        source_lines = lines[start_idx:end_idx]
        context_before_lines = lines[context_start:start_idx]
        context_after_lines = lines[end_idx:context_end]

        ext = file_path.suffix.lstrip(".")
        lang_map = {
            "py": "python",
            "ts": "typescript",
            "tsx": "typescript",
            "js": "javascript",
            "jsx": "javascript",
            "go": "go",
            "rs": "rust",
            "java": "java",
            "cs": "csharp",
        }
        language = lang_map.get(ext, ext)

        return {
            "node_id": resolved_id,
            "file_path": str(file_path),
            "line_start": line_start,
            "line_end": line_end,
            "source": "\n".join(source_lines),
            "context_before": "\n".join(context_before_lines),
            "context_after": "\n".join(context_after_lines),
            "language": language,
        }

    result = None
    # mubase_path is .mu/mubase, so root is two levels up
    root_path = mubase_path.parent.parent

    # Try daemon first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            # Resolve node name to ID if needed
            if node_id.startswith(("mod:", "cls:", "fn:")):
                resolved_id = node_id
                node_data = client.node(node_id, cwd=str(cwd))
            else:
                found = client.find_node(node_id, cwd=str(cwd))
                if found:
                    resolved_id = found.get("id", node_id)
                    node_data = found
                else:
                    # find_node returns None on error or not found
                    # Fall through to local mode to try there
                    node_data = None

            if node_data:
                result = _read_source(node_data, resolved_id, root_path)
        except DaemonError:
            pass  # Fall through to local mode

    # Fallback to direct MUbase access
    if result is None:
        from mu.errors import ExitCode
        from mu.kernel import MUbase, MUbaseLockError

        try:
            db = MUbase(mubase_path, read_only=True)
        except MUbaseLockError:
            print_error(
                "Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'."
            )
            sys.exit(ExitCode.CONFIG_ERROR)

        try:
            # Resolve node name to ID if needed (fuzzy resolution)
            maybe_resolved_id = _resolve_node_id_local(db, node_id, root_path)
            if maybe_resolved_id is None:
                print_error(f"Node not found: {node_id}")
                sys.exit(1)
            resolved_id = maybe_resolved_id  # Now guaranteed non-None

            fetched_node = db.get_node(resolved_id)
            if not fetched_node:
                print_error(f"Node not found: {node_id}")
                sys.exit(1)

            node = fetched_node
            node_data = {
                "file_path": node.file_path,
                "line_start": node.line_start,
                "line_end": node.line_end,
                "node_type": node.type.value if hasattr(node.type, "value") else str(node.type),
            }
            result = _read_source(node_data, resolved_id, root_path)
        finally:
            db.close()

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        # Pretty print with line numbers
        print_info(f"# {result['node_id']}")
        print_info(f"# {result['file_path']}:{result['line_start']}-{result['line_end']}")
        print_info("")

        # Context before (dimmed)
        context_before_lines = (
            result["context_before"].split("\n") if result["context_before"] else []
        )
        source_lines = result["source"].split("\n") if result["source"] else []
        context_after_lines = result["context_after"].split("\n") if result["context_after"] else []

        context_start = result["line_start"] - len(context_before_lines)
        for i, line in enumerate(context_before_lines):
            line_no = context_start + i
            click.echo(click.style(f"{line_no:4} │ {line}", dim=True))

        for i, line in enumerate(source_lines):
            line_no = result["line_start"] + i
            click.echo(f"{line_no:4} │ {line}")

        for i, line in enumerate(context_after_lines):
            line_no = result["line_end"] + i + 1
            click.echo(click.style(f"{line_no:4} │ {line}", dim=True))


@click.command()
@click.argument("question")
@click.option("--max-tokens", "-t", default=8000, help="Maximum tokens in output")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def context(ctx: MUContext, question: str, max_tokens: int, as_json: bool) -> None:
    """Extract smart context for a natural language question.

    Analyzes the question, finds relevant code nodes, and returns
    a token-efficient MU format representation.

    \b
    Examples:
        mu context 'How does authentication work?'
        mu context 'What calls the payment processor?' --max-tokens 4000
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_error, print_info

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # Try daemon first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            daemon_result = client.context(question, max_tokens=max_tokens, cwd=str(cwd))
            mu_text = daemon_result.get("mu_text", "")
            token_count = daemon_result.get("token_count", 0)
            nodes = daemon_result.get("nodes", [])

            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "mu_text": mu_text,
                            "token_count": token_count,
                            "node_count": len(nodes),
                        },
                        indent=2,
                    )
                )
            else:
                print_info(f"# {len(nodes)} nodes, {token_count} tokens")
                print_info("")
                click.echo(mu_text)
            return
        except DaemonError:
            pass  # Fall through to local mode

    # Local mode (daemon unavailable)
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'."
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        cfg = ExtractionConfig(max_tokens=max_tokens)
        smart_extractor = SmartContextExtractor(db, cfg)
        context_result = smart_extractor.extract(question)

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "mu_text": context_result.mu_text,
                        "token_count": context_result.token_count,
                        "node_count": len(context_result.nodes),
                    },
                    indent=2,
                )
            )
        else:
            print_info(
                f"# {len(context_result.nodes)} nodes, {context_result.token_count} tokens"
            )
            print_info("")
            click.echo(context_result.mu_text)
    finally:
        db.close()


@click.command()
@click.argument("query")
@click.option("--limit", "-l", default=20, help="Maximum results")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def search(ctx: MUContext, query: str, limit: int, as_json: bool) -> None:
    """Semantic search for code nodes.

    Search for code elements using natural language or keywords.
    Requires embeddings (run 'mu bootstrap --embed' first).

    \b
    Examples:
        mu search 'authentication logic'
        mu search 'database connection' --limit 10
        mu search 'error handling' --json
    """
    import asyncio
    import json as json_module

    from mu.config import MUConfig
    from mu.kernel import MUbase
    from mu.kernel.embeddings import EmbeddingService
    from mu.logging import print_error, print_info, print_warning

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    from mu.errors import ExitCode
    from mu.kernel import MUbaseLockError

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'."
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        embed_stats = db.embedding_stats()
        has_embeddings = embed_stats["nodes_with_embeddings"] > 0

        if has_embeddings:
            # Semantic search with embeddings
            try:
                config = MUConfig.load()
            except Exception:
                config = MUConfig()

            service = EmbeddingService(config=config.embeddings, provider="local")

            async def get_query_embedding() -> list[float] | None:
                return await service.embed_query(query)

            print_info(f"Semantic search: {query}")
            query_embedding = asyncio.run(get_query_embedding())

            if query_embedding is None:
                print_warning("Failed to generate query embedding, falling back to keyword search")
                has_embeddings = False
            else:
                # Perform vector search
                results = db.vector_search(
                    query_embedding=query_embedding,
                    embedding_type="code",
                    limit=limit,
                )

                asyncio.run(service.close())

                if as_json:
                    click.echo(
                        json_module.dumps(
                            [
                                {
                                    "node_id": node.id,
                                    "name": node.name,
                                    "type": node.type.value,
                                    "score": round(score, 4),
                                    "file_path": node.file_path,
                                    "line_start": node.line_start,
                                }
                                for node, score in results
                            ],
                            indent=2,
                        )
                    )
                else:
                    if not results:
                        print_info("No results found")
                        return

                    print_info(f"Found {len(results)} results:\n")
                    for node, score in results:
                        score_pct = score * 100
                        click.echo(f"  {node.name} ({node.type.value}) - {score_pct:.1f}%")
                        if node.file_path:
                            click.echo(
                                click.style(f"    {node.file_path}:{node.line_start}", dim=True)
                            )
                return

        # Keyword search fallback (no embeddings or embedding failed)
        if not has_embeddings:
            print_info(f"Keyword search: {query}")
            print_info(click.style("(For semantic search, run 'mu bootstrap --embed')", dim=True))
            print_info("")

        # Search by name pattern
        keyword_results = db.find_by_name(f"%{query}%")

        # Also search in qualified names if we have few results
        if len(keyword_results) < limit:
            # Get all nodes and filter by qualified_name containing query
            all_nodes = db.execute(
                """
                SELECT * FROM nodes
                WHERE qualified_name LIKE ? OR name LIKE ?
                ORDER BY
                    CASE WHEN name LIKE ? THEN 0 ELSE 1 END,
                    complexity DESC
                LIMIT ?
                """,
                [f"%{query}%", f"%{query}%", f"%{query}%", limit],
            )
            from mu.kernel.models import Node

            keyword_results = [Node.from_row(row) for row in all_nodes]

        # Limit results
        keyword_results = keyword_results[:limit]

        if as_json:
            click.echo(
                json_module.dumps(
                    [
                        {
                            "node_id": node.id,
                            "name": node.name,
                            "type": node.type.value,
                            "score": 1.0,  # No score for keyword search
                            "file_path": node.file_path,
                            "line_start": node.line_start,
                        }
                        for node in keyword_results
                    ],
                    indent=2,
                )
            )
        else:
            if not keyword_results:
                print_info("No results found")
                return

            print_info(f"Found {len(keyword_results)} results:\n")
            for node in keyword_results:
                click.echo(f"  {node.name} ({node.type.value})")
                if node.file_path:
                    click.echo(click.style(f"    {node.file_path}:{node.line_start}", dim=True))
    finally:
        db.close()


@click.command()
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--change-type",
    "-c",
    type=click.Choice(["create", "modify", "delete"]),
    default="modify",
    help="Type of change being made",
)
@click.option("--no-conventions", is_flag=True, help="Skip convention-based detection")
@click.option("--no-git", is_flag=True, help="Skip git co-change analysis")
@click.option("--no-deps", is_flag=True, help="Skip dependency analysis")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def related(
    ctx: MUContext,
    file_path: Path,
    change_type: str,
    no_conventions: bool,
    no_git: bool,
    no_deps: bool,
    as_json: bool,
) -> None:
    """Suggest related files that typically change together.

    Analyzes a file to find related files based on:

    \b
    1. Convention patterns (test files, stories, index exports)
    2. Git history (files that historically change together)
    3. Dependencies (files that import this file)

    \b
    Examples:
        mu related src/auth.py              # Find files related to auth.py
        mu related src/hooks/useAuth.ts     # Find test/story files
        mu related src/new_feature.py -c create  # Creating a new file
        mu related src/old_module.py -c delete   # Deleting a file
        mu related src/api.py --no-git      # Skip git analysis
        mu related src/api.py --json        # JSON output
    """
    import json

    from mu.intelligence import RelatedFilesDetector
    from mu.kernel import MUbase
    from mu.logging import print_info, print_success, print_warning

    # Find mubase for dependency analysis
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    db = None
    if mubase_path and not no_deps:
        try:
            db = MUbase(mubase_path)
        except Exception:
            if ctx.verbosity == "verbose":
                print_warning("Could not open .mu/mubase for dependency analysis")

    try:
        # Determine root path
        root_path = mubase_path.parent if mubase_path else cwd

        detector = RelatedFilesDetector(db=db, root_path=root_path)
        result = detector.detect(
            str(file_path),
            change_type=change_type,  # type: ignore[arg-type]
            include_conventions=not no_conventions,
            include_git_cochange=not no_git,
            include_dependencies=not no_deps,
        )

        if as_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
        else:
            # Pretty print
            print_info(f"# Related files for: {result.file_path}")
            print_info(f"# Change type: {result.change_type}")
            print_info("")

            if not result.related_files:
                print_info("No related files detected.")
                return

            # Group by action
            create_files = result.create_files
            update_files = result.update_files
            review_files = result.review_files

            if create_files:
                print_success(f"Create ({len(create_files)}):")
                for rf in create_files:
                    click.echo(f"  + {rf.path}")
                    click.echo(click.style(f"      {rf.reason} ({rf.confidence:.0%})", dim=True))
                print_info("")

            if update_files:
                print_warning(f"Update ({len(update_files)}):")
                for rf in update_files:
                    click.echo(f"  ~ {rf.path}")
                    click.echo(click.style(f"      {rf.reason} ({rf.confidence:.0%})", dim=True))
                print_info("")

            if review_files:
                print_info(f"Review ({len(review_files)}):")
                for rf in review_files[:10]:  # Limit review suggestions
                    click.echo(f"  ? {rf.path}")
                    click.echo(click.style(f"      {rf.reason} ({rf.confidence:.0%})", dim=True))
                if len(review_files) > 10:
                    click.echo(click.style(f"  ... and {len(review_files) - 10} more", dim=True))
                print_info("")

            print_info(f"Detection time: {result.detection_time_ms:.1f}ms")
    finally:
        if db:
            db.close()


__all__ = ["bootstrap", "status", "read", "context", "search", "related"]
