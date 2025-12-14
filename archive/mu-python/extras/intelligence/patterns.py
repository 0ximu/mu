"""Pattern detection for codebases.

Analyzes the MUbase graph to detect recurring patterns including:
- Naming conventions
- Error handling patterns
- Import organization
- Architectural patterns
- Testing patterns
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from mu.extras.intelligence.models import (
    Pattern,
    PatternCategory,
    PatternExample,
    PatternsResult,
)
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel import MUbase
    from mu.kernel.models import Node


class PatternDetector:
    """Detects recurring patterns in a codebase.

    Analyzes the MUbase graph to identify naming conventions,
    architectural patterns, and coding styles.
    """

    # Minimum frequency for a pattern to be considered significant
    MIN_FREQUENCY = 3

    # Minimum confidence for pattern inclusion
    MIN_CONFIDENCE = 0.3

    # Maximum examples to store per pattern
    MAX_EXAMPLES = 5

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the pattern detector.

        Args:
            mubase: The MUbase database to analyze.
        """
        self.db = mubase
        self._root_path: Path | None = None

    def detect(
        self,
        category: PatternCategory | None = None,
        refresh: bool = False,
    ) -> PatternsResult:
        """Detect patterns in the codebase.

        Args:
            category: Optional category filter. If None, detect all categories.
            refresh: If True, bypass cache and re-analyze.

        Returns:
            PatternsResult with detected patterns.
        """
        start_time = time.time()

        # Get root path from metadata
        stats = self.db.stats()
        root_path_str = stats.get("root_path")
        self._root_path = Path(root_path_str) if root_path_str else None

        patterns: list[Pattern] = []

        # Run detection for each category (or just the specified one)
        categories_to_analyze = [category] if category else list(PatternCategory)

        for cat in categories_to_analyze:
            if cat is None:
                continue
            detected = self._detect_category(cat)
            patterns.extend(detected)

        # Sort by frequency descending
        patterns.sort(key=lambda p: p.frequency, reverse=True)

        # Get unique categories found
        categories_found = list({p.category.value for p in patterns})

        elapsed_ms = (time.time() - start_time) * 1000

        return PatternsResult(
            patterns=patterns,
            total_patterns=len(patterns),
            categories_found=categories_found,
            detection_time_ms=elapsed_ms,
            codebase_stats={
                "nodes": stats.get("nodes", 0),
                "edges": stats.get("edges", 0),
                "nodes_by_type": stats.get("nodes_by_type", {}),
            },
        )

    def _detect_category(self, category: PatternCategory) -> list[Pattern]:
        """Detect patterns for a specific category.

        Args:
            category: The category to analyze.

        Returns:
            List of detected patterns for this category.
        """
        detectors = {
            PatternCategory.NAMING: self._detect_naming_patterns,
            PatternCategory.ERROR_HANDLING: self._detect_error_handling_patterns,
            PatternCategory.IMPORTS: self._detect_import_patterns,
            PatternCategory.TESTING: self._detect_testing_patterns,
            PatternCategory.ARCHITECTURE: self._detect_architecture_patterns,
            PatternCategory.API: self._detect_api_patterns,
            PatternCategory.ASYNC: self._detect_async_patterns,
            PatternCategory.LOGGING: self._detect_logging_patterns,
            PatternCategory.STATE_MANAGEMENT: self._detect_state_patterns,
            PatternCategory.COMPONENTS: self._detect_component_patterns,
        }

        detector = detectors.get(category)
        if detector:
            return detector()
        return []

    def _detect_naming_patterns(self) -> list[Pattern]:
        """Detect naming convention patterns."""
        patterns: list[Pattern] = []

        # Get all nodes by type
        classes = self.db.get_nodes(NodeType.CLASS)
        functions = self.db.get_nodes(NodeType.FUNCTION)
        modules = self.db.get_nodes(NodeType.MODULE)

        # Detect class naming patterns
        class_suffixes = self._analyze_suffixes([c.name for c in classes if c.name])
        for suffix, count in class_suffixes.most_common(10):
            if count >= self.MIN_FREQUENCY and len(suffix) > 2:
                examples = self._get_examples_by_suffix(classes, suffix)
                confidence = min(count / len(classes), 1.0) if classes else 0.0

                if confidence >= self.MIN_CONFIDENCE:
                    patterns.append(
                        Pattern(
                            name=f"class_suffix_{suffix.lower()}",
                            category=PatternCategory.NAMING,
                            description=f"Classes ending with '{suffix}' ({count} occurrences)",
                            frequency=count,
                            confidence=confidence,
                            examples=examples[: self.MAX_EXAMPLES],
                            anti_patterns=[
                                f"Using generic names without '{suffix}' suffix for this type"
                            ],
                        )
                    )

        # Detect function naming patterns
        func_prefixes = self._analyze_prefixes([f.name for f in functions if f.name])
        for prefix, count in func_prefixes.most_common(10):
            if count >= self.MIN_FREQUENCY and len(prefix) > 2:
                examples = self._get_examples_by_prefix(functions, prefix)
                confidence = min(count / len(functions), 1.0) if functions else 0.0

                if confidence >= self.MIN_CONFIDENCE:
                    patterns.append(
                        Pattern(
                            name=f"function_prefix_{prefix.lower()}",
                            category=PatternCategory.NAMING,
                            description=f"Functions prefixed with '{prefix}' ({count} occurrences)",
                            frequency=count,
                            confidence=confidence,
                            examples=examples[: self.MAX_EXAMPLES],
                        )
                    )

        # Detect casing conventions
        casing_pattern = self._detect_casing_convention(functions)
        if casing_pattern:
            patterns.append(casing_pattern)

        # Detect file naming patterns
        file_patterns = self._detect_file_naming_patterns(modules)
        patterns.extend(file_patterns)

        return patterns

    def _detect_error_handling_patterns(self) -> list[Pattern]:
        """Detect error handling patterns."""
        patterns: list[Pattern] = []

        classes = self.db.get_nodes(NodeType.CLASS)
        functions = self.db.get_nodes(NodeType.FUNCTION)

        # Find error/exception classes
        error_classes = [
            c
            for c in classes
            if any(kw in c.name.lower() for kw in ["error", "exception", "fault"])
        ]

        if len(error_classes) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(c, "Error/Exception class definition")
                for c in error_classes[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="custom_error_classes",
                    category=PatternCategory.ERROR_HANDLING,
                    description=f"Custom error/exception classes ({len(error_classes)} found)",
                    frequency=len(error_classes),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=[
                        "Using generic Error/Exception without custom classes",
                        "Not including error context in custom errors",
                    ],
                )
            )

        # Find error handling functions
        error_handlers = [
            f
            for f in functions
            if any(kw in f.name.lower() for kw in ["handle_error", "on_error", "catch", "recover"])
        ]

        if len(error_handlers) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(f, "Error handler function")
                for f in error_handlers[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="error_handler_functions",
                    category=PatternCategory.ERROR_HANDLING,
                    description=f"Dedicated error handler functions ({len(error_handlers)} found)",
                    frequency=len(error_handlers),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        return patterns

    def _detect_import_patterns(self) -> list[Pattern]:
        """Detect import organization patterns."""
        patterns: list[Pattern] = []
        modules = self.db.get_nodes(NodeType.MODULE)

        # Analyze imports via edges
        import_edges = self.db.get_edges(edge_type=None)
        import_count = len([e for e in import_edges if e.type.value == "imports"])

        if import_count > 0:
            # Calculate average imports per module
            avg_imports = import_count / len(modules) if modules else 0

            if avg_imports >= 3:
                patterns.append(
                    Pattern(
                        name="modular_imports",
                        category=PatternCategory.IMPORTS,
                        description=f"Modular import structure (avg {avg_imports:.1f} imports/module)",
                        frequency=import_count,
                        confidence=0.8,
                        examples=[],
                        anti_patterns=["Circular imports", "Import * from module"],
                    )
                )

        # Check for index/barrel files
        index_modules = [
            m
            for m in modules
            if m.file_path
            and any(
                m.file_path.endswith(name)
                for name in ["__init__.py", "index.ts", "index.js", "mod.rs"]
            )
        ]

        if len(index_modules) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(m, "Barrel/index file for re-exports")
                for m in index_modules[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="barrel_files",
                    category=PatternCategory.IMPORTS,
                    description=f"Barrel/index files for re-exports ({len(index_modules)} found)",
                    frequency=len(index_modules),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=["Importing directly from deep paths"],
                )
            )

        return patterns

    def _detect_testing_patterns(self) -> list[Pattern]:
        """Detect testing patterns."""
        patterns: list[Pattern] = []

        modules = self.db.get_nodes(NodeType.MODULE)
        functions = self.db.get_nodes(NodeType.FUNCTION)

        # Find test files
        test_modules = [
            m
            for m in modules
            if m.file_path
            and any(
                kw in m.file_path.lower()
                for kw in ["test_", "_test", ".test.", ".spec.", "/tests/"]
            )
        ]

        if len(test_modules) >= self.MIN_FREQUENCY:
            # Analyze test file naming convention
            test_naming = self._analyze_test_file_naming(test_modules)

            examples = [
                self._node_to_example(m, "Test file") for m in test_modules[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="test_file_organization",
                    category=PatternCategory.TESTING,
                    description=f"Test files ({len(test_modules)} found) - {test_naming}",
                    frequency=len(test_modules),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=["Test files scattered without convention"],
                )
            )

        # Find test functions
        test_functions = [
            f for f in functions if f.name.startswith("test_") or f.name.startswith("test")
        ]

        if len(test_functions) >= self.MIN_FREQUENCY:
            patterns.append(
                Pattern(
                    name="test_function_naming",
                    category=PatternCategory.TESTING,
                    description=f"Test functions with 'test_' prefix ({len(test_functions)} found)",
                    frequency=len(test_functions),
                    confidence=0.95,
                    examples=[],
                    anti_patterns=["Test functions without 'test_' prefix"],
                )
            )

        return patterns

    def _detect_architecture_patterns(self) -> list[Pattern]:
        """Detect architectural patterns."""
        patterns: list[Pattern] = []

        classes = self.db.get_nodes(NodeType.CLASS)

        # Service pattern
        services = [c for c in classes if c.name.endswith("Service")]
        if len(services) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(s, "Service class") for s in services[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="service_layer",
                    category=PatternCategory.ARCHITECTURE,
                    description=f"Service layer pattern ({len(services)} Service classes)",
                    frequency=len(services),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=["Business logic in controllers/handlers"],
                )
            )

        # Repository pattern
        repos = [
            c
            for c in classes
            if any(c.name.endswith(suffix) for suffix in ["Repository", "Repo", "Store"])
        ]
        if len(repos) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(r, "Repository/Store class")
                for r in repos[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="repository_pattern",
                    category=PatternCategory.ARCHITECTURE,
                    description=f"Repository/Store pattern ({len(repos)} classes)",
                    frequency=len(repos),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=["Direct database access in services"],
                )
            )

        # Controller/Handler pattern
        controllers = [
            c
            for c in classes
            if any(c.name.endswith(suffix) for suffix in ["Controller", "Handler", "Router"])
        ]
        if len(controllers) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(c, "Controller/Handler class")
                for c in controllers[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="controller_pattern",
                    category=PatternCategory.ARCHITECTURE,
                    description=f"Controller/Handler pattern ({len(controllers)} classes)",
                    frequency=len(controllers),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        # Model/Entity pattern
        models = [
            c
            for c in classes
            if any(c.name.endswith(suffix) for suffix in ["Model", "Entity", "Schema"])
        ]
        if len(models) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(m, "Model/Entity class") for m in models[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="model_layer",
                    category=PatternCategory.ARCHITECTURE,
                    description=f"Model/Entity layer ({len(models)} classes)",
                    frequency=len(models),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        return patterns

    def _detect_api_patterns(self) -> list[Pattern]:
        """Detect API patterns."""
        patterns: list[Pattern] = []

        functions = self.db.get_nodes(NodeType.FUNCTION)
        modules = self.db.get_nodes(NodeType.MODULE)

        # HTTP method handlers
        http_methods = ["get", "post", "put", "patch", "delete", "head", "options"]
        api_handlers = [
            f
            for f in functions
            if any(f.name.lower().startswith(m) or f.name.lower() == m for m in http_methods)
        ]

        if len(api_handlers) >= self.MIN_FREQUENCY:
            patterns.append(
                Pattern(
                    name="http_method_handlers",
                    category=PatternCategory.API,
                    description=f"HTTP method handlers ({len(api_handlers)} found)",
                    frequency=len(api_handlers),
                    confidence=0.8,
                    examples=[],
                )
            )

        # Route files
        route_modules = [
            m
            for m in modules
            if m.file_path
            and any(kw in m.file_path.lower() for kw in ["route", "api", "endpoint", "views"])
        ]

        if len(route_modules) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(m, "API route module")
                for m in route_modules[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="route_modules",
                    category=PatternCategory.API,
                    description=f"Dedicated route/API modules ({len(route_modules)} found)",
                    frequency=len(route_modules),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        return patterns

    def _detect_async_patterns(self) -> list[Pattern]:
        """Detect async/await patterns."""
        patterns: list[Pattern] = []

        functions = self.db.get_nodes(NodeType.FUNCTION)

        # Async functions (detected via properties or naming)
        async_funcs = [
            f
            for f in functions
            if f.properties.get("is_async")
            or f.name.startswith("async_")
            or "_async" in f.name.lower()
        ]

        if len(async_funcs) >= self.MIN_FREQUENCY:
            confidence = min(len(async_funcs) / len(functions), 1.0) if functions else 0.0
            patterns.append(
                Pattern(
                    name="async_functions",
                    category=PatternCategory.ASYNC,
                    description=f"Async/await pattern ({len(async_funcs)} async functions)",
                    frequency=len(async_funcs),
                    confidence=confidence,
                    examples=[],
                    anti_patterns=[
                        "Blocking calls in async functions",
                        "Not awaiting async calls",
                    ],
                )
            )

        return patterns

    def _detect_logging_patterns(self) -> list[Pattern]:
        """Detect logging patterns."""
        patterns: list[Pattern] = []

        functions = self.db.get_nodes(NodeType.FUNCTION)
        classes = self.db.get_nodes(NodeType.CLASS)

        # Logger classes
        logger_classes = [
            c for c in classes if "logger" in c.name.lower() or "logging" in c.name.lower()
        ]

        if len(logger_classes) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(logger_cls, "Logger class")
                for logger_cls in logger_classes[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="custom_loggers",
                    category=PatternCategory.LOGGING,
                    description=f"Custom logger classes ({len(logger_classes)} found)",
                    frequency=len(logger_classes),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                )
            )

        # Log functions
        log_funcs = [
            f
            for f in functions
            if f.name.lower() in ["log", "debug", "info", "warn", "warning", "error", "critical"]
        ]

        if len(log_funcs) >= self.MIN_FREQUENCY:
            patterns.append(
                Pattern(
                    name="log_level_functions",
                    category=PatternCategory.LOGGING,
                    description=f"Standard log level functions ({len(log_funcs)} found)",
                    frequency=len(log_funcs),
                    confidence=0.85,
                    examples=[],
                )
            )

        return patterns

    def _detect_state_patterns(self) -> list[Pattern]:
        """Detect state management patterns."""
        patterns: list[Pattern] = []

        classes = self.db.get_nodes(NodeType.CLASS)
        functions = self.db.get_nodes(NodeType.FUNCTION)

        # State/Store classes
        state_classes = [
            c
            for c in classes
            if any(
                kw in c.name.lower() for kw in ["state", "store", "context", "provider", "reducer"]
            )
        ]

        if len(state_classes) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(s, "State management class")
                for s in state_classes[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="state_management",
                    category=PatternCategory.STATE_MANAGEMENT,
                    description=f"State management classes ({len(state_classes)} found)",
                    frequency=len(state_classes),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        # Hooks (React pattern)
        hooks = [f for f in functions if f.name.startswith("use") and len(f.name) > 3]
        if len(hooks) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(h, "Hook function") for h in hooks[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="hooks_pattern",
                    category=PatternCategory.STATE_MANAGEMENT,
                    description=f"Hooks pattern (use* functions: {len(hooks)} found)",
                    frequency=len(hooks),
                    confidence=0.9,
                    examples=[e for e in examples if e],
                    anti_patterns=["Hooks outside of components", "Conditional hooks"],
                )
            )

        return patterns

    def _detect_component_patterns(self) -> list[Pattern]:
        """Detect component patterns."""
        patterns: list[Pattern] = []

        classes = self.db.get_nodes(NodeType.CLASS)
        functions = self.db.get_nodes(NodeType.FUNCTION)

        # Component classes/functions
        components = [
            c
            for c in classes
            if any(kw in c.name for kw in ["Component", "View", "Screen", "Page", "Widget"])
        ]

        # Also check for PascalCase functions (React functional components)
        pascal_funcs = [
            f
            for f in functions
            if f.name and f.name[0].isupper() and not f.name.isupper() and "_" not in f.name
        ]

        if len(components) >= self.MIN_FREQUENCY:
            examples = [
                self._node_to_example(c, "Component class") for c in components[: self.MAX_EXAMPLES]
            ]
            patterns.append(
                Pattern(
                    name="component_classes",
                    category=PatternCategory.COMPONENTS,
                    description=f"Component classes ({len(components)} found)",
                    frequency=len(components),
                    confidence=0.85,
                    examples=[e for e in examples if e],
                )
            )

        if len(pascal_funcs) >= self.MIN_FREQUENCY:
            patterns.append(
                Pattern(
                    name="functional_components",
                    category=PatternCategory.COMPONENTS,
                    description=f"Functional components (PascalCase: {len(pascal_funcs)} found)",
                    frequency=len(pascal_funcs),
                    confidence=0.7,  # Lower confidence as PascalCase may be other things
                    examples=[],
                )
            )

        return patterns

    # ==========================================================================
    # Helper methods
    # ==========================================================================

    def _analyze_suffixes(self, names: list[str]) -> Counter[str]:
        """Analyze common suffixes in names."""
        suffixes: list[str] = []

        for name in names:
            # Extract potential suffixes (CamelCase or snake_case)
            if "_" in name:
                parts = name.split("_")
                if len(parts) > 1 and parts[-1]:
                    suffixes.append(parts[-1])
            else:
                # CamelCase - find last uppercase segment
                matches = re.findall(r"[A-Z][a-z]+", name)
                if matches:
                    suffixes.append(matches[-1])

        return Counter(suffixes)

    def _analyze_prefixes(self, names: list[str]) -> Counter[str]:
        """Analyze common prefixes in names."""
        prefixes: list[str] = []

        for name in names:
            # Extract potential prefixes (CamelCase or snake_case)
            if "_" in name:
                parts = name.split("_")
                if len(parts) > 1 and parts[0]:
                    prefixes.append(parts[0])
            else:
                # CamelCase - find first lowercase segment or first word
                if name and name[0].islower():
                    match = re.match(r"^[a-z]+", name)
                    if match:
                        prefixes.append(match.group())

        return Counter(prefixes)

    def _get_examples_by_suffix(self, nodes: list[Node], suffix: str) -> list[PatternExample]:
        """Get example nodes that end with a suffix."""
        examples: list[PatternExample] = []
        for node in nodes:
            if node.name.endswith(suffix):
                example = self._node_to_example(node, f"Class with '{suffix}' suffix")
                if example:
                    examples.append(example)
                if len(examples) >= self.MAX_EXAMPLES:
                    break
        return examples

    def _get_examples_by_prefix(self, nodes: list[Node], prefix: str) -> list[PatternExample]:
        """Get example nodes that start with a prefix."""
        examples: list[PatternExample] = []
        for node in nodes:
            if node.name.lower().startswith(prefix.lower()):
                example = self._node_to_example(node, f"Function with '{prefix}' prefix")
                if example:
                    examples.append(example)
                if len(examples) >= self.MAX_EXAMPLES:
                    break
        return examples

    def _detect_casing_convention(self, functions: list[Node]) -> Pattern | None:
        """Detect the dominant casing convention for function names."""
        snake_case = 0
        camel_case = 0

        for f in functions:
            name = f.name
            if "_" in name and name.islower():
                snake_case += 1
            elif name and name[0].islower() and "_" not in name:
                camel_case += 1

        total = snake_case + camel_case
        if total < self.MIN_FREQUENCY:
            return None

        if snake_case > camel_case and snake_case >= self.MIN_FREQUENCY:
            confidence = snake_case / total
            return Pattern(
                name="snake_case_functions",
                category=PatternCategory.NAMING,
                description=f"Functions use snake_case ({snake_case}/{total})",
                frequency=snake_case,
                confidence=confidence,
                examples=[],
                anti_patterns=["Using camelCase for function names"],
            )
        elif camel_case > snake_case and camel_case >= self.MIN_FREQUENCY:
            confidence = camel_case / total
            return Pattern(
                name="camel_case_functions",
                category=PatternCategory.NAMING,
                description=f"Functions use camelCase ({camel_case}/{total})",
                frequency=camel_case,
                confidence=confidence,
                examples=[],
                anti_patterns=["Using snake_case for function names"],
            )

        return None

    def _detect_file_naming_patterns(self, modules: list[Node]) -> list[Pattern]:
        """Detect file naming patterns."""
        patterns: list[Pattern] = []

        # Analyze file extensions
        extensions: Counter[str] = Counter()
        for m in modules:
            if m.file_path:
                ext = Path(m.file_path).suffix
                if ext:
                    extensions[ext] += 1

        # Check for common patterns
        for ext, count in extensions.most_common(5):
            if count >= self.MIN_FREQUENCY:
                patterns.append(
                    Pattern(
                        name=f"file_extension_{ext.lstrip('.')}",
                        category=PatternCategory.NAMING,
                        description=f"Files with {ext} extension ({count} files)",
                        frequency=count,
                        confidence=0.95,
                        examples=[],
                    )
                )

        return patterns

    def _analyze_test_file_naming(self, test_modules: list[Node]) -> str:
        """Analyze test file naming convention."""
        patterns: dict[str, int] = defaultdict(int)

        for m in test_modules:
            if not m.file_path:
                continue
            name = Path(m.file_path).name

            if name.startswith("test_"):
                patterns["test_*.py"] += 1
            elif name.endswith("_test.py"):
                patterns["*_test.py"] += 1
            elif ".test." in name:
                patterns["*.test.*"] += 1
            elif ".spec." in name:
                patterns["*.spec.*"] += 1
            elif "/tests/" in m.file_path:
                patterns["tests/*.py"] += 1

        if patterns:
            most_common = max(patterns, key=lambda k: patterns[k])
            return f"Convention: {most_common}"
        return "Mixed conventions"

    def _node_to_example(self, node: Node, annotation: str) -> PatternExample | None:
        """Convert a node to a PatternExample."""
        if not node.file_path or not node.line_start or not node.line_end:
            return None

        # Try to read the source code
        code_snippet = self._read_source(node.file_path, node.line_start, node.line_end)

        return PatternExample(
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            code_snippet=code_snippet,
            annotation=annotation,
        )

    def _read_source(
        self, file_path: str, line_start: int, line_end: int, max_lines: int = 20
    ) -> str:
        """Read source code from a file."""
        try:
            # Resolve path relative to root
            if self._root_path:
                full_path = self._root_path / file_path
            else:
                full_path = Path(file_path)

            if not full_path.exists():
                return f"# Source at {file_path}:{line_start}-{line_end}"

            lines = full_path.read_text().splitlines()

            # Limit to max_lines
            actual_end = min(line_end, line_start + max_lines)
            snippet_lines = lines[line_start - 1 : actual_end]

            if line_end > actual_end:
                snippet_lines.append(f"# ... ({line_end - actual_end} more lines)")

            return "\n".join(snippet_lines)
        except Exception:
            return f"# Source at {file_path}:{line_start}-{line_end}"


__all__ = ["PatternDetector"]
