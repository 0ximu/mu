"""OMEGA S-expression exporter with schema-based compression.

Exports the graph as Lisp S-expressions with a fixed schema header
for strict positional format parsing. Part of Project OMEGA.

Schema v2.0 uses defschema forms that define the exact positional
format for each entity type, enabling deterministic parsing by LLMs.

Example output:
    ;; OMG SCHEMA v2.0
    (defschema module [Name File Deps])
    (defschema class [Name Bases Methods Complexity])
    (defschema method [Name Args ReturnType Complexity])
    (defschema function [Name Args ReturnType Complexity Decorators])

    ;; Codebase: mu @ abc1234
    (module mu.auth "src/mu/auth.py" [mu.models mu.utils]
      (class AuthService [BaseService]
        (method authenticate [username:str password:str] User 5)
        (method logout [] None 2)))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mu.kernel.export.base import ExportOptions, ExportResult

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


# ============================================================================
# OMG SCHEMA v2.0 - Strict Positional Typing
# ============================================================================
# This schema is emitted ONCE at the top of every OMEGA export.
# Position determines meaning - no named parameters.
# ============================================================================

OMG_SCHEMA_VERSION = "2.0"

OMG_SCHEMA_HEADER = """;; OMG SCHEMA v2.0 - STRICT POSITIONAL TYPING
;; Format: (type arg1 arg2 ...)
;; Position determines meaning. No named parameters.

;; === CONTAINERS ===
(defschema module [Name FilePath]
  "Source file. Name is namespace/module path.")

(defschema service [Name Dependencies Methods]
  "Class implementing I{Name}. Dependencies are ctor-injected.")

(defschema class [Name Parent Attrs Methods]
  "Class definition. Parent is base class or nil.")

(defschema validator [Name Target Rules]
  "FluentValidation class for Target type.")

;; === MEMBERS ===
(defschema method [Name Args ReturnType Complexity]
  "Instance method. Complexity is cyclomatic score.")

(defschema function [Name Args ReturnType Complexity]
  "Standalone/static function.")

(defschema attr [Name Type]
  "Property or field.")

;; === SPECIALIZED ===
(defschema api [HttpVerb Path Handler Args]
  "HTTP endpoint. Azure Function or Controller action.")

(defschema model [Name Fields]
  "DTO or Entity. Fields are name:type pairs.")

(defschema enum [Name Values]
  "Enumeration type.")

(defschema const [Name Type Value]
  "Constant definition.")

;; === SIGILS ===
;; _name     = injected dependency (private field)
;; Name?     = nullable type
;; [T]       = list/array of T
;; Result<T> = Result monad containing T
;; +N        = N additional items omitted

;; === READING EXAMPLES ===
;; (service InvoiceService [_repo _logger] (...methods...))
;;   → class InvoiceService : IInvoiceService
;;   → private readonly IRepo _repo;
;;   → private readonly ILogger _logger;
;;
;; (method VoidAsync [id:Guid status:string?] Result<Invoice> 38)
;;   → public async Task<Result<Invoice>> VoidAsync(Guid id, string? status)
;;   → cyclomatic complexity: 38
;;
;; (validator VoidInvoice Invoice [Required NotEmpty ValidStatus])
;;   → class VoidInvoiceValidator : AbstractValidator<Invoice>
;;   → rules: Required, NotEmpty, ValidStatus"""


@dataclass
class OmegaExportOptions(ExportOptions):
    """Extended options for OMEGA export."""

    include_synthesized: bool = True
    """Include dynamically synthesized macros (legacy, kept for compatibility)."""

    max_synthesized_macros: int = 5
    """Maximum synthesized macros to include (legacy, kept for compatibility)."""

    include_header: bool = True
    """Include schema definitions header."""

    pretty_print: bool = True
    """Format with indentation for readability."""

    use_schema_v2: bool = True
    """Use OMG SCHEMA v2.0 format (strict positional). Set False for legacy defmacro."""


class OmegaExporter:
    """Export graph as OMEGA Schema v2.0 S-expressions.

    Uses strict positional typing with a fixed schema header emitted once
    at the top. Position determines meaning - no named parameters.

    Example output:
        ;; OMG SCHEMA v2.0 - STRICT POSITIONAL TYPING
        (defschema module [Name FilePath] ...)
        (defschema class [Name Parent Attrs Methods] ...)
        ...

        ;; Codebase: mu @ abc1234
        (module mu.auth "src/mu/auth.py"
          (class AuthService BaseService [_repo _logger]
            (method authenticate [username:str password:str] User 5)
            (method logout [] None 2)))
    """

    format_name: str = "omega"
    file_extension: str = ".omega.lisp"
    description: str = "OMEGA Schema v2.0 - strict positional S-expressions"

    def __init__(self) -> None:
        """Initialize the OMEGA exporter."""
        self._synthesizer: Any = None
        self._lisp_exporter: Any = None

    @property
    def synthesizer(self) -> Any:
        """Lazy-load macro synthesizer."""
        if self._synthesizer is None:
            # Synthesizer needs MUbase, which we'll set per-export
            self._synthesizer = None
        return self._synthesizer

    @property
    def lisp_exporter(self) -> Any:
        """Lazy-load Lisp exporter."""
        if self._lisp_exporter is None:
            from mu.kernel.export.lisp import LispExporter

            self._lisp_exporter = LispExporter()
        return self._lisp_exporter

    def export(
        self,
        mubase: MUbase,
        options: OmegaExportOptions | ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to OMEGA Schema v2.0 format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with OMEGA format output.
        """
        options = options or OmegaExportOptions()

        # Extract OmegaExportOptions fields or use defaults
        include_header = getattr(options, "include_header", True)
        pretty_print = getattr(options, "pretty_print", True)

        # Get nodes for export
        nodes = self._get_nodes(mubase, options)
        if not nodes:
            return ExportResult(
                output=";; No nodes to export",
                format=self.format_name,
                node_count=0,
                edge_count=0,
            )

        # Generate OMEGA output
        lines: list[str] = []

        # Emit schema header ONCE at top
        if include_header:
            lines.append(OMG_SCHEMA_HEADER)
            lines.append("")

        # Get codebase info for the header comment
        codebase_info = self._get_codebase_info(mubase)
        if codebase_info:
            lines.append(f";; Codebase: {codebase_info}")

        # Generate strict positional body
        body = self._generate_schema_v2_body(nodes, mubase, pretty_print)
        lines.append(body)

        output = "\n".join(lines)

        return ExportResult(
            output=output,
            format=self.format_name,
            node_count=len(nodes),
            edge_count=0,  # We don't export edges in OMEGA
        )

    def _get_codebase_info(self, mubase: MUbase) -> str:
        """Get codebase name and commit for header comment.

        Args:
            mubase: The MUbase database.

        Returns:
            String like "mu @ abc1234" or empty string.
        """
        try:
            import subprocess

            # Get repo name
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=str(mubase.path.parent) if hasattr(mubase, "path") else None,
            )
            codebase = ""
            if result.returncode == 0:
                url = result.stdout.strip()
                if "/" in url:
                    codebase = url.split("/")[-1].replace(".git", "")

            # Get commit hash
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(mubase.path.parent) if hasattr(mubase, "path") else None,
            )
            commit = result.stdout.strip() if result.returncode == 0 else ""

            if codebase and commit:
                return f"{codebase} @ {commit}"
            elif codebase:
                return codebase
            return ""
        except Exception:
            return ""

    def _generate_schema_v2_body(
        self,
        nodes: list[Any],
        mubase: MUbase,
        pretty_print: bool = True,
    ) -> str:
        """Generate strict positional S-expression body using Schema v2.0.

        Each node is emitted using its schema form:
        - (module Name FilePath ...)
        - (class Name Parent Attrs ...)
        - (method Name Args ReturnType Complexity)
        - (function Name Args ReturnType Complexity)
        - (service Name Dependencies ...)

        Args:
            nodes: Nodes to include in the body.
            mubase: The MUbase database for querying relationships.
            pretty_print: Whether to format with indentation.

        Returns:
            Strict positional S-expression body.
        """
        from collections import defaultdict

        from mu.kernel.schema import NodeType

        if not nodes:
            return ""

        indent = "  " if pretty_print else ""
        nl = "\n" if pretty_print else " "

        # Group nodes by module for structured output
        by_module: dict[str, list[Any]] = defaultdict(list)
        for node in nodes:
            module_path = node.file_path or "unknown"
            by_module[module_path].append(node)

        lines: list[str] = []

        for module_path, module_nodes in sorted(by_module.items()):
            # Generate module name from path
            module_name = self._path_to_module_name(module_path)

            # Separate nodes by type
            classes = [n for n in module_nodes if n.type == NodeType.CLASS]
            functions = [
                n for n in module_nodes
                if n.type == NodeType.FUNCTION and not (n.properties or {}).get("is_method")
            ]

            # Build module content
            module_content: list[str] = []

            # Process classes with their methods
            for cls in classes:
                class_sexpr = self._class_to_schema_v2(cls, mubase, indent * 2)
                module_content.append(class_sexpr)

            # Process top-level functions
            for func in functions:
                func_sexpr = self._function_to_schema_v2(func)
                module_content.append(f"{indent}{func_sexpr}")

            # Build module S-expression
            # (module Name FilePath ...contents...)
            if module_content:
                lines.append(f'(module {module_name} "{module_path}"')
                lines.extend(module_content)
                lines.append(")")
            else:
                lines.append(f'(module {module_name} "{module_path}")')

        return nl.join(lines)

    def _class_to_schema_v2(self, node: Any, mubase: MUbase, indent: str = "") -> str:
        """Convert a class node to Schema v2.0 S-expression.

        Determines if class is a service, model, validator, or plain class.

        Args:
            node: The class node.
            mubase: The MUbase database.
            indent: Indentation prefix.

        Returns:
            S-expression like:
            (service AuthService [_repo _logger] (method ...))
            (class UserModel BaseModel [name email] ...)
            (model UserDTO [id:int name:str])
        """
        from mu.kernel.schema import NodeType

        props = node.properties or {}
        name = node.name or "Unknown"
        bases = props.get("bases", [])
        attrs = props.get("attributes", [])
        decorators = str(props.get("decorators", [])).lower()

        # Get methods for this class
        children = mubase.get_children(node.id)
        methods = [c for c in children if c.type == NodeType.FUNCTION]

        # Determine class type based on naming/decorators
        name_lower = name.lower()

        # Format attributes as dependency list (prefix with _ for injected deps)
        attr_list = self._format_attrs(attrs)

        # Format base class (first one or nil)
        parent = bases[0] if bases else "nil"

        # Check if it's a service (ends with Service)
        if name_lower.endswith("service"):
            return self._service_to_schema_v2(name, attr_list, methods, indent)

        # Check if it's a dataclass/model
        if "dataclass" in decorators or name_lower.endswith("model"):
            return self._model_to_schema_v2(name, attrs, indent)

        # Check if it's a validator (ends with Validator)
        if name_lower.endswith("validator"):
            # Try to extract target from name (e.g., InvoiceValidator -> Invoice)
            target = name[:-9] if name.endswith("Validator") else name
            rules = attrs[:5]  # Use attrs as rules placeholder
            return f"{indent}(validator {name} {target} [{' '.join(str(r) for r in rules)}])"

        # Default: plain class
        return self._plain_class_to_schema_v2(name, parent, attr_list, methods, indent)

    def _service_to_schema_v2(
        self, name: str, deps: list[str], methods: list[Any], indent: str
    ) -> str:
        """Format a service class.

        (service Name [deps] (method ...) ...)
        """
        lines = []
        deps_str = " ".join(deps) if deps else ""

        if methods:
            lines.append(f"{indent}(service {name} [{deps_str}]")
            for method in methods:
                method_sexpr = self._method_to_schema_v2(method)
                lines.append(f"{indent}  {method_sexpr}")
            lines.append(f"{indent})")
            return "\n".join(lines)
        else:
            return f"{indent}(service {name} [{deps_str}])"

    def _model_to_schema_v2(self, name: str, attrs: list[Any], indent: str) -> str:
        """Format a model/dataclass.

        (model Name [field1:type1 field2:type2])
        """
        fields = self._format_fields(attrs)
        return f"{indent}(model {name} [{fields}])"

    def _plain_class_to_schema_v2(
        self, name: str, parent: str, attrs: list[str], methods: list[Any], indent: str
    ) -> str:
        """Format a plain class.

        (class Name Parent [attrs] (method ...) ...)
        """
        lines = []
        attrs_str = " ".join(attrs) if attrs else ""

        if methods:
            lines.append(f"{indent}(class {name} {parent} [{attrs_str}]")
            for method in methods:
                method_sexpr = self._method_to_schema_v2(method)
                lines.append(f"{indent}  {method_sexpr}")
            lines.append(f"{indent})")
            return "\n".join(lines)
        else:
            return f"{indent}(class {name} {parent} [{attrs_str}])"

    def _method_to_schema_v2(self, node: Any) -> str:
        """Convert a method node to Schema v2.0 S-expression.

        (method Name [args] ReturnType Complexity)
        """
        props = node.properties or {}
        name = node.name or "unknown"
        return_type = props.get("return_type", "None") or "None"
        complexity = props.get("complexity", 0) or node.complexity or 0

        # Format parameters
        params = props.get("parameters", [])
        args = self._format_params(params)

        return f"(method {name} [{args}] {return_type} {complexity})"

    def _function_to_schema_v2(self, node: Any) -> str:
        """Convert a function node to Schema v2.0 S-expression.

        (function Name [args] ReturnType Complexity)

        If function has HTTP decorators, use (api HttpVerb Path Handler [args])
        """
        props = node.properties or {}
        name = node.name or "unknown"
        return_type = props.get("return_type", "None") or "None"
        complexity = props.get("complexity", 0) or node.complexity or 0
        decorators = props.get("decorators", [])
        decorators_str = str(decorators).lower()

        # Check for API endpoint (HTTP method decorators)
        for verb in ["get", "post", "put", "delete", "patch"]:
            if verb in decorators_str:
                path = self._extract_path_from_decorators(decorators)
                params = props.get("parameters", [])
                args = self._format_params(params)
                return f'(api {verb.upper()} "{path}" {name} [{args}])'

        # Regular function
        params = props.get("parameters", [])
        args = self._format_params(params)

        return f"(function {name} [{args}] {return_type} {complexity})"

    def _format_params(self, params: list[Any]) -> str:
        """Format function/method parameters as name:type pairs."""
        param_strs = []
        for p in params:
            if isinstance(p, dict):
                pname = p.get("name", "?")
                ptype = p.get("type_annotation", "")
                # Skip self/cls
                if pname in ("self", "cls"):
                    continue
                if ptype:
                    param_strs.append(f"{pname}:{ptype}")
                else:
                    param_strs.append(pname)
            elif isinstance(p, str):
                param_strs.append(p)
        return " ".join(param_strs)

    def _format_attrs(self, attrs: list[Any]) -> list[str]:
        """Format class attributes, prefixing injected deps with _."""
        result = []
        for attr in attrs[:10]:  # Limit to 10
            if isinstance(attr, dict):
                aname = attr.get("name", "?")
            else:
                aname = str(attr)
            # Prefix with _ if it looks like an injected dependency
            if aname.startswith("_") or "service" in aname.lower() or "repo" in aname.lower():
                if not aname.startswith("_"):
                    aname = f"_{aname}"
            result.append(aname)
        if len(attrs) > 10:
            result.append(f"+{len(attrs) - 10}")
        return result

    def _format_fields(self, attrs: list[Any]) -> str:
        """Format model fields as name:type pairs."""
        field_strs = []
        for attr in attrs[:10]:  # Limit to 10
            if isinstance(attr, dict):
                fname = attr.get("name", "?")
                ftype = attr.get("type", attr.get("type_annotation", "Any"))
                field_strs.append(f"{fname}:{ftype}" if ftype else fname)
            else:
                field_strs.append(str(attr))
        if len(attrs) > 10:
            field_strs.append(f"+{len(attrs) - 10}")
        return " ".join(field_strs)

    def _extract_path_from_decorators(self, decorators: list[Any]) -> str:
        """Extract URL path from HTTP method decorators."""
        import re

        for dec in decorators:
            dec_str = str(dec)
            # Look for path in quotes
            path_match = re.search(r'["\']([^"\']+)["\']', dec_str)
            if path_match:
                return path_match.group(1)
        return "/"

    def _path_to_module_name(self, path: str) -> str:
        """Convert a file path to module name.

        Args:
            path: File path.

        Returns:
            Module name (e.g., 'mu.parser.models').
        """
        name = path

        # Remove common prefixes
        for prefix in ("src/", "lib/", "app/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        # Remove extension
        for ext in (".py", ".ts", ".js", ".go", ".java", ".rs", ".cs"):
            if name.endswith(ext):
                name = name[:-len(ext)]
                break

        # Convert path separators to dots
        name = name.replace("/", ".").replace("\\", ".")

        # Remove trailing __init__
        if name.endswith(".__init__"):
            name = name[:-9]

        return name

    def _get_nodes(self, mubase: MUbase, options: ExportOptions) -> list[Any]:
        """Get nodes based on filter options.

        Args:
            mubase: The MUbase database.
            options: Export options with filters.

        Returns:
            List of filtered nodes.
        """
        from mu.kernel.models import Node

        # If specific node IDs requested
        if options.node_ids:
            nodes: list[Node] = []
            for node_id in options.node_ids:
                node = mubase.get_node(node_id)
                if node:
                    nodes.append(node)
            return nodes

        # Get all nodes of requested types
        if options.node_types:
            nodes = []
            for node_type in options.node_types:
                nodes.extend(mubase.get_nodes(node_type))
        else:
            nodes = mubase.get_nodes()

        # Apply max_nodes limit
        if options.max_nodes and len(nodes) > options.max_nodes:
            nodes = nodes[: options.max_nodes]

        return nodes


__all__ = ["OmegaExporter", "OmegaExportOptions", "OMG_SCHEMA_HEADER", "OMG_SCHEMA_VERSION"]
