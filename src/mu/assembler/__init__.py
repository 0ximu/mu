"""MU Assembler - Cross-file import resolution and module graph assembly.

The Assembler stitches file-level MU output into a cohesive codebase representation,
resolving imports to actual module paths within the scanned codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from mu.parser.models import ImportDef, ModuleDef
from mu.reducer.generator import DynamicDependency, ReducedCodebase

# Re-export for type checking
__all__ = ["ReducedModule"]
from mu.reducer.generator import ReducedModule  # noqa: E402, F401


class DependencyType(Enum):
    """Type of dependency relationship."""
    INTERNAL = "internal"  # Within the scanned codebase
    EXTERNAL = "external"  # Third-party package
    STDLIB = "stdlib"      # Standard library
    DYNAMIC = "dynamic"    # Runtime/dynamic import (pattern detected but not resolvable)


@dataclass
class ResolvedImport:
    """An import resolved to its actual location."""

    original: ImportDef
    resolved_path: str | None = None  # Path within codebase, or None if external
    dep_type: DependencyType = DependencyType.EXTERNAL
    resolved_names: list[str] = field(default_factory=list)  # Resolved symbol names


@dataclass
class DynamicImportInfo:
    """Information about a dynamic import."""

    pattern: str | None = None    # The pattern/expression (e.g., "f'plugins.{name}'")
    source: str | None = None     # Detection method (e.g., "importlib", "import()")
    line: int = 0                 # Source line number
    resolved_path: str | None = None  # If resolvable, the target path

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.pattern:
            result["pattern"] = self.pattern
        if self.source:
            result["source"] = self.source
        if self.line:
            result["line"] = self.line
        if self.resolved_path:
            result["resolved_path"] = self.resolved_path
        return result


@dataclass
class ModuleNode:
    """A node in the module dependency graph."""

    name: str                    # Module name (e.g., "mu.parser.models")
    path: str                    # File path relative to root
    language: str
    internal_deps: list[str] = field(default_factory=list)   # Other modules in codebase
    external_deps: list[str] = field(default_factory=list)   # Third-party packages
    stdlib_deps: list[str] = field(default_factory=list)     # Standard library modules
    dynamic_deps: list[DynamicImportInfo] = field(default_factory=list)  # Dynamic/runtime imports
    exports: list[str] = field(default_factory=list)         # Symbols this module exports

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "path": self.path,
            "language": self.language,
            "internal_deps": self.internal_deps,
            "external_deps": self.external_deps,
            "stdlib_deps": self.stdlib_deps,
            "exports": self.exports,
        }
        if self.dynamic_deps:
            result["dynamic_deps"] = [d.to_dict() for d in self.dynamic_deps]
        return result


@dataclass
class ModuleGraph:
    """Graph of module dependencies in the codebase."""

    nodes: dict[str, ModuleNode] = field(default_factory=dict)  # path -> ModuleNode
    edges: list[tuple[str, str, DependencyType]] = field(default_factory=list)  # (from, to, type)

    def add_node(self, node: ModuleNode) -> None:
        """Add a module node to the graph."""
        self.nodes[node.path] = node

    def add_edge(self, from_path: str, to_path: str, dep_type: DependencyType) -> None:
        """Add a dependency edge between modules."""
        self.edges.append((from_path, to_path, dep_type))

    def get_internal_graph(self) -> dict[str, list[str]]:
        """Get internal dependencies as adjacency list."""
        graph: dict[str, list[str]] = {}
        for from_path, to_path, dep_type in self.edges:
            if dep_type == DependencyType.INTERNAL:
                if from_path not in graph:
                    graph[from_path] = []
                graph[from_path].append(to_path)
        return graph

    def get_external_packages(self) -> set[str]:
        """Get all external packages used."""
        packages: set[str] = set()
        for node in self.nodes.values():
            packages.update(node.external_deps)
        return packages

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [
                {"from": f, "to": t, "type": d.value}
                for f, t, d in self.edges
            ],
        }


# Go standard library packages (common subset)
GO_STDLIB = {
    "archive", "bufio", "builtin", "bytes", "compress", "container", "context",
    "crypto", "database", "debug", "embed", "encoding", "errors", "expvar",
    "flag", "fmt", "go", "hash", "html", "image", "index", "io", "log", "maps",
    "math", "mime", "net", "os", "path", "plugin", "reflect", "regexp", "runtime",
    "slices", "sort", "strconv", "strings", "sync", "syscall", "testing", "text",
    "time", "unicode", "unsafe",
}

# Rust standard library crates
RUST_STDLIB = {
    "std", "core", "alloc", "collections", "proc_macro",
    # Common std modules that might be imported directly
    "std.io", "std.fs", "std.env", "std.path", "std.net", "std.sync",
    "std.thread", "std.time", "std.collections", "std.fmt", "std.str",
    "std.vec", "std.string", "std.boxed", "std.rc", "std.cell",
    "std.mem", "std.ptr", "std.slice", "std.iter", "std.ops",
    "std.cmp", "std.hash", "std.default", "std.marker", "std.convert",
    "std.borrow", "std.clone", "std.any", "std.error", "std.panic",
    "std.process", "std.ffi", "std.os",
    # Core modules
    "core.fmt", "core.ops", "core.cmp", "core.iter", "core.option",
    "core.result", "core.slice", "core.str", "core.mem", "core.ptr",
    # Alloc modules
    "alloc.vec", "alloc.string", "alloc.boxed", "alloc.rc", "alloc.sync",
}

# Java standard library packages
JAVA_STDLIB = {
    "java.lang", "java.util", "java.io", "java.nio", "java.net",
    "java.sql", "java.math", "java.text", "java.time", "java.security",
    "java.awt", "java.beans", "java.rmi", "java.applet",
    "javax.swing", "javax.sql", "javax.xml", "javax.crypto",
    "javax.net", "javax.naming", "javax.management", "javax.annotation",
    # Common package roots
    "java", "javax", "sun", "com.sun", "org.w3c", "org.xml",
}

# Python standard library modules (common subset for MVP)
PYTHON_STDLIB = {
    "abc", "argparse", "ast", "asyncio", "base64", "bisect", "builtins",
    "calendar", "collections", "concurrent", "contextlib", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "email", "enum",
    "errno", "exceptions", "fnmatch", "fractions", "functools", "gc",
    "getopt", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "linecache", "locale", "logging", "lzma", "math", "mimetypes",
    "multiprocessing", "numbers", "operator", "os", "pathlib", "pickle",
    "platform", "pprint", "queue", "random", "re", "secrets", "shutil",
    "signal", "socket", "sqlite3", "ssl", "statistics", "string", "struct",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
    "timeit", "traceback", "types", "typing", "unittest", "urllib", "uuid",
    "warnings", "weakref", "xml", "zipfile", "zlib",
    # typing_extensions is commonly used but not stdlib
    "__future__",
}


class ImportResolver:
    """Resolves imports to actual module paths within a codebase."""

    def __init__(self, modules: list[ModuleDef], root_path: Path):
        """Initialize resolver with parsed modules.

        Args:
            modules: List of parsed module definitions
            root_path: Root path of the scanned codebase
        """
        self.root_path = root_path.resolve()
        self.modules = modules

        # Build lookup tables
        self._path_to_module: dict[str, ModuleDef] = {}
        self._module_name_to_path: dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Build module lookup index."""
        for module in self.modules:
            self._path_to_module[module.path] = module
            self._module_name_to_path[module.name] = module.path

    def resolve(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve an import to its actual location.

        Args:
            imp: The import definition to resolve
            from_module: The module containing this import

        Returns:
            ResolvedImport with resolution details
        """
        # Handle dynamic imports specially
        if imp.is_dynamic:
            return self._resolve_dynamic(imp, from_module)

        language = from_module.language

        if language == "python":
            return self._resolve_python(imp, from_module)
        elif language in ("typescript", "javascript"):
            return self._resolve_typescript(imp, from_module)
        elif language == "csharp":
            return self._resolve_csharp(imp, from_module)
        elif language == "go":
            return self._resolve_go(imp, from_module)
        elif language == "rust":
            return self._resolve_rust(imp, from_module)
        elif language == "java":
            return self._resolve_java(imp, from_module)
        else:
            # Unknown language - treat as external
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.EXTERNAL,
            )

    def _resolve_dynamic(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve a dynamic import.

        Dynamic imports are marked as DYNAMIC type since their actual
        target cannot be determined statically. If the module name is
        a static string, we still try to resolve it.
        """
        # If the dynamic import has a concrete module name (not a pattern),
        # we can try to resolve it like a normal import
        if imp.module and imp.module != "<dynamic>":
            # Try normal resolution but mark as dynamic
            language = from_module.language
            if language == "python":
                resolved = self._resolve_python(imp, from_module)
            elif language in ("typescript", "javascript"):
                resolved = self._resolve_typescript(imp, from_module)
            else:
                resolved = ResolvedImport(original=imp, dep_type=DependencyType.EXTERNAL)

            # Even if we resolved it, mark the dependency type as DYNAMIC
            # to indicate it's a runtime import
            return ResolvedImport(
                original=imp,
                resolved_path=resolved.resolved_path,
                dep_type=DependencyType.DYNAMIC,
                resolved_names=resolved.resolved_names,
            )

        # Truly dynamic pattern - cannot be resolved
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.DYNAMIC,
        )

    def _resolve_python(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve Python import statements."""
        module_name = imp.module

        # Check for stdlib
        root_module = module_name.split(".")[0]
        if root_module in PYTHON_STDLIB:
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Handle relative imports
        if module_name.startswith("."):
            resolved_path = self._resolve_relative_python(module_name, from_module)
            if resolved_path:
                return ResolvedImport(
                    original=imp,
                    resolved_path=resolved_path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # Try to find as internal module
        # First try exact match on module name
        if module_name in self._module_name_to_path:
            return ResolvedImport(
                original=imp,
                resolved_path=self._module_name_to_path[module_name],
                dep_type=DependencyType.INTERNAL,
                resolved_names=imp.names,
            )

        # Try path-based resolution for dotted imports (e.g., "mu.parser.models")
        # Convert dotted module name to file path patterns
        module_name.split(".")
        for mod in self.modules:
            # Check if path contains the module parts as directories/file
            # e.g., "mu.parser.models" -> matches "src/mu/parser/models.py"
            # or "mu.parser" -> matches "src/mu/parser/__init__.py"
            mod_path_parts = Path(mod.path).parts

            # Check if the import path matches the end of the file path
            # For a module path like src/mu/parser/models.py,
            # we want to match imports like "mu.parser.models" or "parser.models" or "models"
            file_stem = Path(mod.path).stem
            if file_stem == "__init__":
                # Package: use parent directory name
                file_stem = mod_path_parts[-2] if len(mod_path_parts) >= 2 else ""

            # Build possible module paths from file path
            # e.g., src/mu/parser/models.py -> ["models", "parser.models", "mu.parser.models"]
            possible_names = []
            current_parts: list[str] = []
            for part in reversed(mod_path_parts[:-1]):  # Exclude filename
                current_parts.insert(0, part)
                possible_names.append(".".join(current_parts + [file_stem]))
            possible_names.insert(0, file_stem)  # Just the module name

            if module_name in possible_names:
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

            # Also check if importing a package (module_name matches directory)
            if module_name == file_stem or any(
                pn.endswith("." + module_name) or pn == module_name
                for pn in possible_names
            ):
                continue  # Already checked above

        # Check if module_name matches any path suffix
        # This handles cases like "mu.parser" matching "src/mu/parser/__init__.py"
        module_path_suffix = module_name.replace(".", "/")
        for mod in self.modules:
            # Check both .py files and __init__.py in packages
            if mod.path.endswith(f"/{module_path_suffix}.py") or \
               mod.path.endswith(f"/{module_path_suffix}/__init__.py") or \
               mod.path == f"{module_path_suffix}.py" or \
               mod.path == f"{module_path_suffix}/__init__.py":
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # External package
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )

    def _resolve_relative_python(self, module_name: str, from_module: ModuleDef) -> str | None:
        """Resolve relative Python import."""
        # Count leading dots
        dots = 0
        for c in module_name:
            if c == ".":
                dots += 1
            else:
                break

        remainder = module_name[dots:]

        # Get current module's package path
        from_parts = Path(from_module.path).parts

        # Go up 'dots' levels (minus 1 for the current directory)
        if dots > len(from_parts):
            return None  # Invalid relative import

        # Build the target path
        base_parts = from_parts[:-dots]  # Go up 'dots' directories
        if remainder:
            # Add the remainder as path components
            target_parts = list(base_parts) + remainder.split(".")
        else:
            target_parts = list(base_parts)

        # Try to find matching module
        target_base = "/".join(target_parts)

        # Check for exact file match
        for ext in [".py", "/__init__.py"]:
            candidate = target_base + ext
            candidate = candidate.lstrip("/")
            if candidate in self._path_to_module:
                return candidate

        # Check for module name match
        target_name = ".".join(target_parts)
        if target_name in self._module_name_to_path:
            return self._module_name_to_path[target_name]

        return None

    def _resolve_typescript(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve TypeScript/JavaScript import statements."""
        module_path = imp.module

        # Relative imports
        if module_path.startswith("."):
            resolved = self._resolve_relative_typescript(module_path, from_module)
            if resolved:
                return ResolvedImport(
                    original=imp,
                    resolved_path=resolved,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # Absolute imports starting with known source paths
        # Check if it matches any internal module path
        for mod in self.modules:
            # Normalize paths for comparison
            mod_path_no_ext = re.sub(r'\.(ts|tsx|js|jsx|mjs)$', '', mod.path)
            if module_path == mod_path_no_ext or mod.path.startswith(module_path + "/"):
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # Node built-ins
        if module_path in {"fs", "path", "os", "http", "https", "crypto", "util", "events", "stream", "buffer", "child_process", "cluster", "dns", "net", "readline", "tls", "url", "zlib"}:
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # External package
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )

    def _resolve_relative_typescript(self, module_path: str, from_module: ModuleDef) -> str | None:
        """Resolve relative TypeScript/JavaScript import."""
        from_dir = Path(from_module.path).parent

        # Normalize the relative path
        target = (from_dir / module_path).as_posix()

        # Clean up the path (handle .. and .)
        parts: list[str] = []
        for part in target.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)

        target = "/".join(parts)

        # Try various extensions
        extensions = [".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx", "/index.js"]

        for ext in extensions:
            candidate = target + ext
            if candidate in self._path_to_module:
                return candidate

        # Direct match (already has extension)
        if target in self._path_to_module:
            return target

        return None

    def _resolve_csharp(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve C# using statements."""
        namespace = imp.module

        # System namespaces are stdlib
        if namespace.startswith("System"):
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Microsoft.* namespaces are typically stdlib/framework
        if namespace.startswith("Microsoft."):
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Try to find internal namespace match
        # C# uses namespaces, not file paths, so we look for modules
        # that might define symbols in this namespace
        for mod in self.modules:
            # Check if module name matches namespace pattern
            if mod.name.startswith(namespace) or namespace.startswith(mod.name):
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # External package (NuGet)
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )

    def _resolve_go(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve Go import statements."""
        import_path = imp.module

        # Get the root package (first path element)
        root_pkg = import_path.split("/")[0]

        # Check for standard library
        if root_pkg in GO_STDLIB:
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Check if it looks like an internal import
        # Go modules typically use domain-based paths (e.g., github.com/user/repo)
        # Internal packages might not have domain prefix or use relative paths

        # Try to find internal module match
        # For Go, module paths are based on directory structure
        for mod in self.modules:
            mod_dir = Path(mod.path).parent.as_posix()
            # Check if import path matches module directory suffix
            if mod_dir.endswith(import_path) or import_path.endswith(mod_dir):
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

            # Check if module package name matches import
            if mod.name == import_path.split("/")[-1]:
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # External package (e.g., github.com/pkg/errors)
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )

    def _resolve_rust(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve Rust use statements."""
        import_path = imp.module

        # Get the root crate/module
        root_crate = import_path.split(".")[0]

        # Check for standard library
        if root_crate in ("std", "core", "alloc", "proc_macro"):
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Check if full path is in stdlib
        if import_path in RUST_STDLIB:
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Check for crate-relative imports
        if root_crate in ("crate", "self", "super"):
            # Try to resolve to internal module
            for mod in self.modules:
                mod_stem = Path(mod.path).stem
                # Check if any part of the import matches a module
                path_parts = import_path.split(".")
                for part in path_parts[1:]:  # Skip crate/self/super
                    if part == mod_stem:
                        return ResolvedImport(
                            original=imp,
                            resolved_path=mod.path,
                            dep_type=DependencyType.INTERNAL,
                            resolved_names=imp.names,
                        )

        # Try to find internal module match by name
        for mod in self.modules:
            mod_stem = Path(mod.path).stem
            if mod_stem == root_crate or mod_stem in import_path.split("."):
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # External crate (crates.io dependency)
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )

    def _resolve_java(self, imp: ImportDef, from_module: ModuleDef) -> ResolvedImport:
        """Resolve Java import statements."""
        import_path = imp.module

        # Check for Java standard library packages
        for stdlib_pkg in JAVA_STDLIB:
            if import_path.startswith(stdlib_pkg):
                return ResolvedImport(
                    original=imp,
                    dep_type=DependencyType.STDLIB,
                )

        # Get the root package
        root_pkg = import_path.split(".")[0]

        # Common Java stdlib root packages
        if root_pkg in ("java", "javax", "sun", "com.sun", "org.w3c", "org.xml"):
            return ResolvedImport(
                original=imp,
                dep_type=DependencyType.STDLIB,
            )

        # Try to find internal module match
        # Java uses package paths that may match directory structure
        for mod in self.modules:
            # Check if module's package matches import path
            if mod.name.startswith(import_path) or import_path.startswith(mod.name):
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

            # Check if the imported class name matches a module
            class_name = import_path.rsplit(".", 1)[-1]
            if Path(mod.path).stem == class_name:
                return ResolvedImport(
                    original=imp,
                    resolved_path=mod.path,
                    dep_type=DependencyType.INTERNAL,
                    resolved_names=imp.names,
                )

        # External dependency (Maven/Gradle)
        return ResolvedImport(
            original=imp,
            dep_type=DependencyType.EXTERNAL,
        )


class Assembler:
    """Assembles file-level MU into cohesive codebase representation."""

    def __init__(self, modules: list[ModuleDef], root_path: Path):
        """Initialize assembler.

        Args:
            modules: List of parsed module definitions
            root_path: Root path of the scanned codebase
        """
        self.modules = modules
        self.root_path = root_path.resolve()
        self.resolver = ImportResolver(modules, root_path)
        self.graph: ModuleGraph | None = None

    def build_graph(self) -> ModuleGraph:
        """Build the complete module dependency graph."""
        graph = ModuleGraph()

        for module in self.modules:
            # Create node for this module
            node = ModuleNode(
                name=module.name,
                path=module.path,
                language=module.language,
            )

            # Collect exports (class names, function names)
            for cls in module.classes:
                node.exports.append(cls.name)
            for func in module.functions:
                node.exports.append(func.name)

            # Resolve imports
            for imp in module.imports:
                resolved = self.resolver.resolve(imp, module)

                if resolved.dep_type == DependencyType.INTERNAL:
                    if resolved.resolved_path:
                        node.internal_deps.append(resolved.resolved_path)
                        graph.add_edge(module.path, resolved.resolved_path, DependencyType.INTERNAL)
                elif resolved.dep_type == DependencyType.EXTERNAL:
                    # Get the package name (first part of module path)
                    package = imp.module.split(".")[0].split("/")[0]
                    if package and package not in node.external_deps:
                        node.external_deps.append(package)
                elif resolved.dep_type == DependencyType.STDLIB:
                    root_module = imp.module.split(".")[0]
                    if root_module not in node.stdlib_deps:
                        node.stdlib_deps.append(root_module)
                elif resolved.dep_type == DependencyType.DYNAMIC:
                    # Track dynamic import info
                    dynamic_info = DynamicImportInfo(
                        pattern=imp.dynamic_pattern,
                        source=imp.dynamic_source,
                        line=imp.line_number,
                        resolved_path=resolved.resolved_path,
                    )
                    node.dynamic_deps.append(dynamic_info)
                    # If we were able to resolve the path, also add edge
                    if resolved.resolved_path:
                        graph.add_edge(module.path, resolved.resolved_path, DependencyType.DYNAMIC)

            # Deduplicate
            node.internal_deps = list(dict.fromkeys(node.internal_deps))
            node.external_deps = list(dict.fromkeys(node.external_deps))
            node.stdlib_deps = list(dict.fromkeys(node.stdlib_deps))

            graph.add_node(node)

        self.graph = graph
        return graph

    def get_topological_order(self) -> list[str]:
        """Get modules in topological order (dependencies first).

        Returns a list where each module appears after all modules it depends on.
        """
        if not self.graph:
            self.build_graph()
        assert self.graph is not None

        graph = self.graph.get_internal_graph()

        # Build out-degree: how many dependencies each node has
        out_degree: dict[str, int] = dict.fromkeys(self.graph.nodes, 0)
        # Build reverse graph: who depends on this node
        reverse_graph: dict[str, list[str]] = {path: [] for path in self.graph.nodes}

        for from_path, deps in graph.items():
            for dep in deps:
                if dep in self.graph.nodes:
                    out_degree[from_path] += 1
                    reverse_graph[dep].append(from_path)

        # Kahn's algorithm on reverse graph
        # Start with nodes that have no dependencies (out_degree = 0)
        result = []
        queue = [path for path, degree in out_degree.items() if degree == 0]

        while queue:
            path = queue.pop(0)
            result.append(path)

            # For each node that depends on this one
            for dependent in reverse_graph.get(path, []):
                if dependent in out_degree:
                    out_degree[dependent] -= 1
                    if out_degree[dependent] == 0:
                        queue.append(dependent)

        # Add any remaining (cyclic dependencies)
        for path in self.graph.nodes:
            if path not in result:
                result.append(path)

        return result

    def enhance_reduced_codebase(self, reduced: ReducedCodebase) -> ReducedCodebase:
        """Enhance a reduced codebase with resolved dependency information.

        Args:
            reduced: The reduced codebase from the reducer stage

        Returns:
            Enhanced ReducedCodebase with resolved dependencies
        """
        if not self.graph:
            self.build_graph()
        assert self.graph is not None

        # Update dependency graph with resolved paths
        resolved_graph: dict[str, list[str]] = {}

        for module in reduced.modules:
            if module.path in self.graph.nodes:
                node = self.graph.nodes[module.path]

                # Use module names instead of paths for readability
                internal_deps = []
                for dep_path in node.internal_deps:
                    if dep_path in self.graph.nodes:
                        internal_deps.append(self.graph.nodes[dep_path].name)

                if internal_deps:
                    resolved_graph[module.name] = internal_deps

        reduced.dependency_graph = resolved_graph

        # Set external packages
        reduced.external_packages = sorted(self.graph.get_external_packages())

        # Collect dynamic dependencies from all modules
        dynamic_deps: list[DynamicDependency] = []
        for module in reduced.modules:
            if module.path in self.graph.nodes:
                node = self.graph.nodes[module.path]
                for dyn_info in node.dynamic_deps:
                    # Resolve target path to module name if possible
                    resolved_target = None
                    if dyn_info.resolved_path and dyn_info.resolved_path in self.graph.nodes:
                        resolved_target = self.graph.nodes[dyn_info.resolved_path].name

                    dynamic_deps.append(DynamicDependency(
                        module_name=module.name,
                        pattern=dyn_info.pattern,
                        source=dyn_info.source,
                        line=dyn_info.line,
                        resolved_target=resolved_target,
                    ))

        reduced.dynamic_dependencies = dynamic_deps

        # Add graph stats
        reduced.stats["internal_dependencies"] = sum(
            len(deps) for deps in resolved_graph.values()
        )
        reduced.stats["external_packages"] = len(reduced.external_packages)
        reduced.stats["dynamic_imports"] = len(dynamic_deps)

        return reduced


@dataclass
class AssembledOutput:
    """Complete assembled MU output."""

    codebase: ReducedCodebase
    graph: ModuleGraph
    topological_order: list[str]
    external_packages: set[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.codebase.source,
            "stats": self.codebase.stats,
            "module_graph": self.graph.to_dict(),
            "topological_order": self.topological_order,
            "external_packages": sorted(self.external_packages),
            "modules": [
                {
                    "name": m.name,
                    "path": m.path,
                    "language": m.language,
                }
                for m in self.codebase.modules
            ],
        }


def assemble(
    modules: list[ModuleDef],
    reduced: ReducedCodebase,
    root_path: Path,
) -> AssembledOutput:
    """Convenience function to assemble a codebase.

    Args:
        modules: Original parsed modules
        reduced: Reduced codebase from reducer
        root_path: Root path of the codebase

    Returns:
        AssembledOutput with full graph and ordering
    """
    assembler = Assembler(modules, root_path)
    graph = assembler.build_graph()
    enhanced = assembler.enhance_reduced_codebase(reduced)

    return AssembledOutput(
        codebase=enhanced,
        graph=graph,
        topological_order=assembler.get_topological_order(),
        external_packages=graph.get_external_packages(),
    )


__all__ = [
    "DependencyType",
    "DynamicImportInfo",
    "ResolvedImport",
    "ModuleNode",
    "ModuleGraph",
    "ImportResolver",
    "Assembler",
    "AssembledOutput",
    "assemble",
    "PYTHON_STDLIB",
    "GO_STDLIB",
    "RUST_STDLIB",
    "JAVA_STDLIB",
]
