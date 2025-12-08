"""FastAPI server for MU daemon mode.

Provides HTTP REST API and WebSocket endpoints for querying and
receiving real-time updates from the code graph.

Supports multi-project mode: clients can pass `cwd` to route requests
to the appropriate .mubase based on working directory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from mu.daemon.config import DaemonConfig
from mu.daemon.events import FileChange, GraphEvent, UpdateQueue
from mu.daemon.watcher import FileWatcher
from mu.daemon.worker import GraphWorker
from mu.kernel import MUbase
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-Project Support
# =============================================================================


def find_mubase_for_path(path: Path) -> Path | None:
    """Find the nearest .mubase file for a given path.

    Walks up the directory tree from `path` looking for .mubase.

    Args:
        path: Starting path (file or directory)

    Returns:
        Path to .mubase if found, None otherwise
    """
    if path.is_file():
        path = path.parent

    path = path.resolve()
    for parent in [path, *path.parents]:
        mubase = parent / ".mubase"
        if mubase.exists():
            return mubase
    return None


class ProjectManager:
    """Manages multiple project databases for multi-project daemon mode.

    Caches MUbase instances keyed by project root path.
    Thread-safe via asyncio lock.
    """

    def __init__(self, default_mubase: MUbase, default_path: Path) -> None:
        """Initialize with a default project.

        Args:
            default_mubase: The default MUbase instance
            default_path: Path to the default .mubase
        """
        self._default_mubase = default_mubase
        self._default_path = default_path.resolve()
        self._cache: dict[Path, MUbase] = {self._default_path: default_mubase}
        self._lock = asyncio.Lock()

    async def get_mubase(self, cwd: str | None = None) -> tuple[MUbase, Path]:
        """Get MUbase instance for a working directory.

        Args:
            cwd: Client's working directory. If None, returns default.

        Returns:
            Tuple of (MUbase instance, mubase_path)

        Raises:
            HTTPException: If no .mubase found for the cwd
        """
        if not cwd:
            return self._default_mubase, self._default_path

        cwd_path = Path(cwd).resolve()
        mubase_path = find_mubase_for_path(cwd_path)

        if not mubase_path:
            # No .mubase found - return default with a note
            logger.debug(f"No .mubase found for {cwd}, using default")
            return self._default_mubase, self._default_path

        mubase_path = mubase_path.resolve()

        async with self._lock:
            if mubase_path in self._cache:
                return self._cache[mubase_path], mubase_path

            # Open new MUbase for this project
            logger.info(f"Opening MUbase for project: {mubase_path}")
            db = MUbase(mubase_path)
            self._cache[mubase_path] = db
            return db, mubase_path

    async def close_all(self) -> None:
        """Close all cached MUbase instances."""
        async with self._lock:
            for path, db in self._cache.items():
                if path != self._default_path:  # Don't close default twice
                    db.close()
            self._cache.clear()

    @property
    def project_count(self) -> int:
        """Number of cached projects."""
        return len(self._cache)

    def list_projects(self) -> list[str]:
        """List all cached project paths."""
        return [str(p) for p in self._cache.keys()]


def _resolve_node_id(db: Any, node_ref: str) -> str:
    """Resolve a node reference to a full node ID.

    Handles:
    - Full node IDs: mod:src/cli.py, cls:src/file.py:ClassName
    - Simple names: MUbase, AuthService
    """
    # If it already looks like a full node ID, return it
    if node_ref.startswith(("mod:", "cls:", "fn:")):
        return node_ref

    # Try exact name match
    nodes = db.find_by_name(node_ref)
    if nodes:
        return str(nodes[0].id)

    # Try pattern match
    nodes = db.find_by_name(f"%{node_ref}%")
    if nodes:
        # Prefer exact name matches
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    # Return original if not found (will fail in has_node check)
    return node_ref


# =============================================================================
# Pydantic Models for API
# =============================================================================


class StatusResponse(BaseModel):
    """Response model for /status endpoint."""

    status: str = Field(description="Daemon status (running)")
    mubase_path: str = Field(description="Path to .mubase file")
    stats: dict[str, Any] = Field(description="Database statistics")
    language_stats: dict[str, Any] = Field(
        default_factory=dict, description="Language distribution statistics"
    )
    connections: int = Field(description="Active WebSocket connections")
    uptime_seconds: float = Field(description="Daemon uptime in seconds")
    # Multi-project info
    active_projects: int = Field(default=1, description="Number of cached projects")
    project_paths: list[str] = Field(default_factory=list, description="Cached project paths")


class NodeResponse(BaseModel):
    """Response model for node data."""

    id: str
    type: str
    name: str
    qualified_name: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    complexity: int = 0


class NeighborsResponse(BaseModel):
    """Response model for /nodes/{id}/neighbors endpoint."""

    node_id: str
    direction: str
    neighbors: list[NodeResponse]


class QueryRequest(BaseModel):
    """Request model for /query endpoint."""

    muql: str = Field(description="MUQL query string")
    cwd: str | None = Field(
        default=None,
        description="Client working directory for multi-project routing",
    )


class QueryResponse(BaseModel):
    """Response model for /query endpoint."""

    result: Any = Field(description="Query result")
    success: bool = Field(description="Whether query succeeded")
    error: str | None = Field(default=None, description="Error message if failed")


class ContextRequest(BaseModel):
    """Request model for /context endpoint."""

    question: str = Field(description="Natural language question")
    max_tokens: int = Field(default=8000, description="Maximum tokens in output")
    exclude_tests: bool = Field(default=False, description="Exclude test files")
    cwd: str | None = Field(
        default=None,
        description="Client working directory for multi-project routing",
    )


class GraphReasoningRequest(BaseModel):
    """Request model for graph reasoning endpoints (/impact, /ancestors)."""

    node_id: str = Field(description="Node ID or name to analyze")
    edge_types: list[str] | None = Field(
        default=None,
        description="Optional list of edge types to follow",
    )
    cwd: str | None = Field(
        default=None,
        description="Client working directory for multi-project routing",
    )


class CyclesRequest(BaseModel):
    """Request model for /cycles endpoint."""

    edge_types: list[str] | None = Field(
        default=None,
        description="Optional list of edge types to consider",
    )
    cwd: str | None = Field(
        default=None,
        description="Client working directory for multi-project routing",
    )


class ContextResponse(BaseModel):
    """Response model for /context endpoint."""

    mu_text: str = Field(description="MU format context")
    token_count: int = Field(description="Token count")
    nodes: list[NodeResponse] = Field(description="Included nodes")


class ContractsRequest(BaseModel):
    """Request model for /contracts/verify endpoint."""

    contracts_path: str | None = Field(
        default=None,
        description="Path to contracts file (default: .mu-contracts.yml)",
    )


class ContractViolationResponse(BaseModel):
    """A single contract violation."""

    contract: str = Field(description="Contract name")
    rule: str = Field(description="Rule name")
    message: str = Field(description="Violation message")
    severity: str = Field(description="Severity: 'error' or 'warning'")
    file_path: str | None = Field(default=None, description="File path if applicable")
    line: int | None = Field(default=None, description="Line number if applicable")
    node_id: str | None = Field(default=None, description="Node ID if applicable")


class ContractsResponse(BaseModel):
    """Response model for /contracts/verify endpoint."""

    passed: bool = Field(description="Whether all contracts passed")
    error_count: int = Field(description="Number of errors")
    warning_count: int = Field(description="Number of warnings")
    violations: list[ContractViolationResponse] = Field(description="List of violations")


# =============================================================================
# Graph Reasoning Models
# =============================================================================


class ImpactResponse(BaseModel):
    """Response model for impact analysis."""

    node_id: str = Field(description="Source node ID")
    impacted_nodes: list[str] = Field(description="List of impacted node IDs")
    count: int = Field(description="Number of impacted nodes")


class AncestorsResponse(BaseModel):
    """Response model for ancestors analysis."""

    node_id: str = Field(description="Source node ID")
    ancestor_nodes: list[str] = Field(description="List of ancestor node IDs")
    count: int = Field(description="Number of ancestor nodes")


class CyclesResponse(BaseModel):
    """Response model for cycle detection."""

    cycles: list[list[str]] = Field(description="List of cycles (each cycle is a list of node IDs)")
    cycle_count: int = Field(description="Number of cycles found")
    total_nodes_in_cycles: int = Field(description="Total nodes involved in cycles")


# =============================================================================
# WebSocket Connection Manager
# =============================================================================


class ConnectionManager:
    """Manage WebSocket connections with connection limits.

    Uses a counter to limit concurrent connections and provides
    broadcast functionality for graph events.
    """

    def __init__(self, max_connections: int = 100) -> None:
        """Initialize the connection manager.

        Args:
            max_connections: Maximum allowed connections
        """
        self.active: list[WebSocket] = []
        self._max_connections = max_connections
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket to accept

        Returns:
            True if connection was accepted, False if limit reached
        """
        async with self._lock:
            if len(self.active) >= self._max_connections:
                return False
            await websocket.accept()
            self.active.append(websocket)
        logger.info(f"WebSocket connected, total: {len(self.active)}")
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """Handle WebSocket disconnection.

        Args:
            websocket: The WebSocket that disconnected
        """
        async with self._lock:
            if websocket in self.active:
                self.active.remove(websocket)
        logger.info(f"WebSocket disconnected, total: {len(self.active)}")

    async def broadcast(self, events: list[GraphEvent]) -> None:
        """Broadcast graph events to all connected clients.

        Args:
            events: List of graph events to broadcast
        """
        if not self.active:
            return

        message = {
            "type": "graph_update",
            "events": [e.to_dict() for e in events],
            "timestamp": time.time(),
        }

        # Copy list to avoid modification during iteration
        async with self._lock:
            connections = self.active.copy()

        disconnected: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        """Get number of active connections."""
        return len(self.active)


# =============================================================================
# Application State
# =============================================================================


class AppState:
    """Shared application state for daemon components."""

    def __init__(
        self,
        mubase: MUbase,
        mubase_path: Path,
        config: DaemonConfig,
    ) -> None:
        self.mubase = mubase
        self.mubase_path = mubase_path
        self.config = config
        self.start_time = time.time()
        self.queue = UpdateQueue(debounce_ms=config.debounce_ms)
        self.watcher: FileWatcher | None = None
        self.worker: GraphWorker | None = None
        self.manager = ConnectionManager(max_connections=config.max_connections)
        # Multi-project support
        self.projects = ProjectManager(mubase, mubase_path)


# =============================================================================
# Application Factory
# =============================================================================


def create_app(mubase_path: Path, config: DaemonConfig) -> FastAPI:
    """Create the FastAPI application with all endpoints.

    Args:
        mubase_path: Path to the .mubase file
        config: Daemon configuration

    Returns:
        Configured FastAPI application
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage daemon lifecycle - startup and shutdown."""
        # Startup
        logger.info(f"Starting MU daemon, mubase: {mubase_path}")

        mubase = MUbase(mubase_path)
        state = AppState(mubase, mubase_path, config)
        app.state.daemon = state

        # Determine watch paths
        watch_paths = config.watch_paths or [mubase_path.parent]

        # Create callback for file watcher
        async def on_file_change(change_type: str, path: Path) -> None:
            change = FileChange(
                change_type=change_type,
                path=path,
                timestamp=time.time(),
            )
            await state.queue.put(change)

        # Start file watcher
        state.watcher = FileWatcher(watch_paths, on_file_change)
        await state.watcher.start()

        # Start graph worker
        state.worker = GraphWorker(mubase, state.queue, mubase_path.parent)

        # Subscribe connection manager to worker events
        async def on_graph_events(events: list[GraphEvent]) -> None:
            await state.manager.broadcast(events)

        state.worker.subscribe(on_graph_events)
        await state.worker.start()

        logger.info("MU daemon started successfully")

        yield

        # Shutdown
        logger.info("Shutting down MU daemon")

        if state.watcher:
            await state.watcher.stop()

        if state.worker:
            await state.worker.stop()

        # Flush any pending queue items
        await state.queue.flush()

        # Close all project databases
        await state.projects.close_all()
        state.mubase.close()
        logger.info("MU daemon shutdown complete")

    app = FastAPI(
        title="MU Daemon",
        description="Real-time code graph API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # -------------------------------------------------------------------------
    # REST Endpoints
    # -------------------------------------------------------------------------

    @app.get("/status", response_model=StatusResponse)
    async def get_status(
        cwd: str | None = Query(
            default=None,
            description="Client working directory for project-specific stats",
        ),
    ) -> StatusResponse:
        """Get daemon status and statistics.

        If `cwd` is provided, returns stats for that project's .mubase.
        Otherwise returns stats for the default project.
        """
        state: AppState = app.state.daemon

        # Get project-specific mubase if cwd provided
        mubase, mubase_path = await state.projects.get_mubase(cwd)
        stats = mubase.stats()
        language_stats = mubase.get_language_stats()

        return StatusResponse(
            status="running",
            mubase_path=str(mubase_path),
            stats=stats,
            language_stats=language_stats,
            connections=state.manager.connection_count,
            uptime_seconds=time.time() - state.start_time,
            active_projects=state.projects.project_count,
            project_paths=state.projects.list_projects(),
        )

    @app.get("/nodes/{node_id}", response_model=NodeResponse)
    async def get_node(node_id: str) -> NodeResponse:
        """Get a node by ID."""
        state: AppState = app.state.daemon
        node = state.mubase.get_node(node_id)
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        return NodeResponse(
            id=node.id,
            type=node.type.value,
            name=node.name,
            qualified_name=node.qualified_name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            properties=node.properties,
            complexity=node.complexity,
        )

    @app.get("/nodes/{node_id}/neighbors", response_model=NeighborsResponse)
    async def get_neighbors(
        node_id: str,
        direction: str = Query(
            default="both",
            description="Direction: 'outgoing', 'incoming', or 'both'",
        ),
    ) -> NeighborsResponse:
        """Get neighboring nodes."""
        state: AppState = app.state.daemon

        # Validate node exists
        node = state.mubase.get_node(node_id)
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        if direction not in ("both", "outgoing", "incoming"):
            raise HTTPException(status_code=400, detail="Invalid direction")

        neighbors = state.mubase.get_neighbors(node_id, direction=direction)
        return NeighborsResponse(
            node_id=node_id,
            direction=direction,
            neighbors=[
                NodeResponse(
                    id=n.id,
                    type=n.type.value,
                    name=n.name,
                    qualified_name=n.qualified_name,
                    file_path=n.file_path,
                    line_start=n.line_start,
                    line_end=n.line_end,
                    properties=n.properties,
                    complexity=n.complexity,
                )
                for n in neighbors
            ],
        )

    @app.post("/query", response_model=QueryResponse)
    async def execute_query(request: QueryRequest) -> QueryResponse:
        """Execute a MUQL query.

        If `cwd` is provided in request, uses that project's .mubase.
        """
        state: AppState = app.state.daemon

        try:
            from mu.kernel.muql import MUQLEngine

            # Get project-specific mubase
            mubase, _ = await state.projects.get_mubase(request.cwd)
            engine = MUQLEngine(mubase)
            # Use query_dict to return dict directly - FastAPI handles serialization
            result = engine.query_dict(request.muql)
            return QueryResponse(result=result, success=True)
        except Exception as e:
            return QueryResponse(result=None, success=False, error=str(e))

    @app.post("/context", response_model=ContextResponse)
    async def get_context(request: ContextRequest) -> ContextResponse:
        """Extract smart context for a question.

        If `cwd` is provided in request, uses that project's .mubase.
        """
        state: AppState = app.state.daemon

        try:
            from mu.kernel.context import ExtractionConfig, SmartContextExtractor

            # Get project-specific mubase
            mubase, _ = await state.projects.get_mubase(request.cwd)

            config = ExtractionConfig(
                max_tokens=request.max_tokens,
                exclude_tests=request.exclude_tests,
            )
            extractor = SmartContextExtractor(mubase, config)
            result = extractor.extract(request.question)

            return ContextResponse(
                mu_text=result.mu_text,
                token_count=result.token_count,
                nodes=[
                    NodeResponse(
                        id=n.id,
                        type=n.type.value,
                        name=n.name,
                        qualified_name=n.qualified_name,
                        file_path=n.file_path,
                        line_start=n.line_start,
                        line_end=n.line_end,
                        properties=n.properties,
                        complexity=n.complexity,
                    )
                    for n in result.nodes
                ],
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # -------------------------------------------------------------------------
    # Graph Reasoning Endpoints
    # -------------------------------------------------------------------------

    @app.post("/impact", response_model=ImpactResponse)
    async def get_impact(request: GraphReasoningRequest) -> ImpactResponse:
        """Find downstream impact of changing a node.

        "If I change X, what might break?"
        """
        state: AppState = app.state.daemon

        try:
            from mu.kernel.graph import GraphManager

            # Get project-specific mubase
            mubase, _ = await state.projects.get_mubase(request.cwd)

            gm = GraphManager(mubase.conn)
            gm.load()

            # Resolve node name to ID if needed
            resolved_id = _resolve_node_id(mubase, request.node_id)

            if not gm.has_node(resolved_id):
                raise HTTPException(status_code=404, detail=f"Node not found: {resolved_id}")

            impacted = gm.impact(resolved_id, request.edge_types)

            return ImpactResponse(
                node_id=resolved_id,
                impacted_nodes=impacted,
                count=len(impacted),
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/ancestors", response_model=AncestorsResponse)
    async def get_ancestors(request: GraphReasoningRequest) -> AncestorsResponse:
        """Find upstream dependencies of a node.

        "What does X depend on?"
        """
        state: AppState = app.state.daemon

        try:
            from mu.kernel.graph import GraphManager

            # Get project-specific mubase
            mubase, _ = await state.projects.get_mubase(request.cwd)

            gm = GraphManager(mubase.conn)
            gm.load()

            # Resolve node name to ID if needed
            resolved_id = _resolve_node_id(mubase, request.node_id)

            if not gm.has_node(resolved_id):
                raise HTTPException(status_code=404, detail=f"Node not found: {resolved_id}")

            ancestor_nodes = gm.ancestors(resolved_id, request.edge_types)

            return AncestorsResponse(
                node_id=resolved_id,
                ancestor_nodes=ancestor_nodes,
                count=len(ancestor_nodes),
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/cycles", response_model=CyclesResponse)
    async def get_cycles(request: CyclesRequest) -> CyclesResponse:
        """Detect circular dependencies in the codebase."""
        state: AppState = app.state.daemon

        try:
            from mu.kernel.graph import GraphManager

            # Get project-specific mubase
            mubase, _ = await state.projects.get_mubase(request.cwd)

            gm = GraphManager(mubase.conn)
            gm.load()

            cycles = gm.find_cycles(request.edge_types)

            return CyclesResponse(
                cycles=cycles,
                cycle_count=len(cycles),
                total_nodes_in_cycles=sum(len(c) for c in cycles),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/export")
    async def export_graph(
        format: str = Query(default="json", description="Export format"),
        nodes: str | None = Query(default=None, description="Comma-separated node IDs"),
        types: str | None = Query(default=None, description="Comma-separated node types"),
        max_nodes: int | None = Query(default=None, description="Maximum nodes"),
    ) -> Response:
        """Export graph in various formats."""
        state: AppState = app.state.daemon

        try:
            from mu.kernel.export import ExportOptions, get_default_manager

            manager = get_default_manager()

            # Parse filters
            node_ids = nodes.split(",") if nodes else None
            node_types = None
            if types:
                try:
                    node_types = [NodeType(t.strip()) for t in types.split(",")]
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid node type: {e}") from e

            options = ExportOptions(
                node_ids=node_ids,
                node_types=node_types,
                max_nodes=max_nodes,
            )

            result = manager.export(state.mubase, format, options)
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)

            # Determine content type
            content_type = "application/json" if format == "json" else "text/plain"

            return Response(content=result.output, media_type=content_type)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/contracts/verify", response_model=ContractsResponse)
    async def verify_contracts(request: ContractsRequest) -> ContractsResponse:
        """Verify architecture contracts against the graph."""
        state: AppState = app.state.daemon

        # Determine contracts file path
        contracts_path = Path(request.contracts_path or ".mu-contracts.yml")
        if not contracts_path.is_absolute():
            contracts_path = state.mubase_path.parent / contracts_path

        # Resolve to absolute and validate no path traversal
        contracts_path = contracts_path.resolve()
        project_root = state.mubase_path.parent.resolve()
        if not str(contracts_path).startswith(str(project_root)):
            raise HTTPException(
                status_code=400,
                detail="Invalid contracts path: path traversal not allowed",
            )

        try:
            from mu.contracts import ContractVerifier, parse_contracts_file

            # Check if contracts file exists
            if not contracts_path.exists():
                # No contracts file - return passed with no violations
                return ContractsResponse(
                    passed=True,
                    error_count=0,
                    warning_count=0,
                    violations=[],
                )

            # Parse contracts and verify
            contracts = parse_contracts_file(contracts_path)
            verifier = ContractVerifier(state.mubase)
            result = verifier.verify(contracts)

            # Convert violations to response format
            # Combine violations and warnings into a single list
            all_violations = result.violations + result.warnings
            violations = []
            for v in all_violations:
                violations.append(
                    ContractViolationResponse(
                        contract=v.contract.name,
                        rule=v.contract.rule.type.value,
                        message=v.message,
                        severity=v.contract.severity.value,
                        file_path=v.file_path,
                        line=v.line,
                        node_id=None,  # Violation model doesn't have node_id
                    )
                )

            return ContractsResponse(
                passed=result.passed,
                error_count=result.error_count,
                warning_count=result.warning_count,
                violations=violations,
            )
        except FileNotFoundError:
            # Contracts file not found - return passed
            return ContractsResponse(
                passed=True,
                error_count=0,
                warning_count=0,
                violations=[],
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # -------------------------------------------------------------------------
    # WebSocket Endpoint
    # -------------------------------------------------------------------------

    @app.websocket("/live")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time graph updates."""
        state: AppState = app.state.daemon

        if not await state.manager.connect(websocket):
            await websocket.close(code=1013)  # Try again later
            return

        try:
            # Send initial connection message
            await websocket.send_json(
                {
                    "type": "connected",
                    "message": "Connected to MU daemon",
                    "timestamp": time.time(),
                }
            )

            # Keep connection alive and handle client messages
            while True:
                try:
                    data = await websocket.receive_json()
                    # Handle subscription requests or other client messages
                    # For now, just acknowledge
                    await websocket.send_json(
                        {
                            "type": "ack",
                            "received": data,
                            "timestamp": time.time(),
                        }
                    )
                except WebSocketDisconnect:
                    break
        finally:
            await state.manager.disconnect(websocket)

    return app


__all__ = [
    "create_app",
    "AppState",
    "ConnectionManager",
    "StatusResponse",
    "NodeResponse",
    "QueryRequest",
    "QueryResponse",
    "ContextRequest",
    "ContextResponse",
    "ContractsRequest",
    "ContractsResponse",
    "ContractViolationResponse",
    # Graph reasoning
    "ImpactResponse",
    "AncestorsResponse",
    "CyclesResponse",
]
