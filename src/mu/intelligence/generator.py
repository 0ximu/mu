"""Code template generator using detected patterns.

Generates boilerplate code that matches codebase patterns, including:
- Hooks, components, services, repositories
- API routes, controllers, models
- Test files for existing modules

Uses detected patterns to ensure generated code follows
existing conventions and styles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mu.intelligence.models import (
    GeneratedFile,
    GenerateResult,
    Pattern,
    PatternCategory,
    TemplateType,
)
from mu.intelligence.patterns import PatternDetector

if TYPE_CHECKING:
    from mu.kernel import MUbase


class CodeGenerator:
    """Generates code templates based on detected patterns.

    Analyzes the codebase to determine:
    - Language (Python, TypeScript, etc.)
    - Naming conventions (snake_case, camelCase, PascalCase)
    - File organization patterns
    - Import styles
    - Testing conventions

    Then generates code that matches these patterns.
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the code generator.

        Args:
            mubase: The MUbase database to analyze.
        """
        self.db = mubase
        self._detector = PatternDetector(mubase)
        self._patterns: list[Pattern] | None = None
        self._language: str | None = None
        self._root_path: Path | None = None

    def generate(
        self,
        template_type: TemplateType | str,
        name: str,
        options: dict[str, Any] | None = None,
    ) -> GenerateResult:
        """Generate code following codebase patterns.

        Args:
            template_type: What to generate (hook, component, service, etc.)
            name: Name for the generated code (e.g., "UserProfile", "useAuth")
            options: Additional options (entity, fields, etc.)

        Returns:
            GenerateResult with generated files
        """
        # Normalize template type
        if isinstance(template_type, str):
            template_type = TemplateType(template_type)

        # Load patterns if not cached
        if self._patterns is None:
            result = self._detector.detect()
            self._patterns = result.patterns

        # Detect primary language
        self._detect_language()

        # Get root path
        stats = self.db.stats()
        root_path_str = stats.get("root_path")
        self._root_path = Path(root_path_str) if root_path_str else Path.cwd()

        options = options or {}

        # Route to appropriate generator
        generators = {
            TemplateType.HOOK: self._generate_hook,
            TemplateType.COMPONENT: self._generate_component,
            TemplateType.SERVICE: self._generate_service,
            TemplateType.REPOSITORY: self._generate_repository,
            TemplateType.API_ROUTE: self._generate_api_route,
            TemplateType.TEST: self._generate_test,
            TemplateType.MODEL: self._generate_model,
            TemplateType.CONTROLLER: self._generate_controller,
        }

        generator = generators.get(template_type)
        if generator:
            return generator(name, options)

        raise ValueError(f"Unknown template type: {template_type}")

    def _detect_language(self) -> str:
        """Detect the primary language of the codebase."""
        if self._language:
            return self._language

        # Check for language-specific patterns
        naming_patterns = self._get_patterns_by_category(PatternCategory.NAMING)

        # Check file extensions
        for pattern in naming_patterns:
            if "file_extension_py" in pattern.name:
                self._language = "python"
                return "python"
            if "file_extension_ts" in pattern.name or "file_extension_tsx" in pattern.name:
                self._language = "typescript"
                return "typescript"
            if "file_extension_js" in pattern.name or "file_extension_jsx" in pattern.name:
                self._language = "javascript"
                return "javascript"
            if "file_extension_go" in pattern.name:
                self._language = "go"
                return "go"
            if "file_extension_rs" in pattern.name:
                self._language = "rust"
                return "rust"

        # Default to Python
        self._language = "python"
        return "python"

    def _get_patterns_by_category(self, category: PatternCategory) -> list[Pattern]:
        """Get patterns for a specific category."""
        if not self._patterns:
            return []
        return [p for p in self._patterns if p.category == category]

    def _get_naming_style(self) -> str:
        """Detect the naming style (snake_case or camelCase)."""
        naming_patterns = self._get_patterns_by_category(PatternCategory.NAMING)
        for pattern in naming_patterns:
            if "snake_case" in pattern.name:
                return "snake_case"
            if "camel_case" in pattern.name:
                return "camelCase"
        # Default based on language
        if self._language in ("python", "rust"):
            return "snake_case"
        return "camelCase"

    def _to_snake_case(self, name: str) -> str:
        """Convert name to snake_case."""
        # Handle PascalCase -> snake_case
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def _to_pascal_case(self, name: str) -> str:
        """Convert name to PascalCase."""
        # Handle snake_case -> PascalCase
        if "_" in name:
            return "".join(word.capitalize() for word in name.split("_"))
        # Already PascalCase or camelCase
        return name[0].upper() + name[1:] if name else ""

    def _to_camel_case(self, name: str) -> str:
        """Convert name to camelCase."""
        pascal = self._to_pascal_case(name)
        return pascal[0].lower() + pascal[1:] if pascal else ""

    def _find_similar_file(self, suffix: str) -> str | None:
        """Find an existing file with a similar suffix to use as location reference."""
        from mu.kernel.schema import NodeType

        modules = self.db.get_nodes(NodeType.MODULE)
        for m in modules:
            if m.file_path and m.file_path.endswith(suffix):
                return str(Path(m.file_path).parent)
        return None

    # ==========================================================================
    # Template Generators
    # ==========================================================================

    def _generate_hook(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a React-style hook."""
        # Ensure name starts with 'use'
        if not name.startswith("use"):
            name = f"use{self._to_pascal_case(name)}"

        patterns_used = []
        suggestions = []

        # Detect if hooks pattern exists
        state_patterns = self._get_patterns_by_category(PatternCategory.STATE_MANAGEMENT)
        has_hooks = any("hooks" in p.name.lower() for p in state_patterns)

        if has_hooks:
            patterns_used.append("hooks_pattern")

        # Find hooks directory
        hooks_dir = self._find_similar_file("hooks/") or "src/hooks"

        # Detect language for hook
        lang = self._detect_language()

        if lang == "typescript":
            content = self._generate_ts_hook(name, options)
            ext = ".ts"
            test_ext = ".test.ts"
        else:
            content = self._generate_js_hook(name, options)
            ext = ".js"
            test_ext = ".test.js"

        # Primary file
        primary_path = f"{hooks_dir}/{name}{ext}"
        files = [
            GeneratedFile(
                path=primary_path,
                content=content,
                description=f"Custom hook: {name}",
                is_primary=True,
            )
        ]

        # Test file
        test_patterns = self._get_patterns_by_category(PatternCategory.TESTING)
        if test_patterns:
            patterns_used.append("test_file_organization")
            test_content = self._generate_hook_test(name, lang)
            test_path = f"{hooks_dir}/__tests__/{name}{test_ext}"
            files.append(
                GeneratedFile(
                    path=test_path,
                    content=test_content,
                    description=f"Tests for {name}",
                    is_primary=False,
                )
            )

        # Check for barrel file pattern
        import_patterns = self._get_patterns_by_category(PatternCategory.IMPORTS)
        has_barrel = any("barrel" in p.name.lower() for p in import_patterns)
        if has_barrel:
            suggestions.append(
                f"Add export to {hooks_dir}/index{ext}: export {{ {name} }} from './{name}'"
            )

        return GenerateResult(
            template_type=TemplateType.HOOK,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=suggestions,
        )

    def _generate_ts_hook(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript hook content."""
        state_type = options.get("state_type", "unknown")
        return_type = options.get(
            "return_type", f"{self._to_pascal_case(name.replace('use', ''))}Result"
        )

        return f"""import {{ useState, useCallback }} from 'react';

interface {return_type} {{
  data: {state_type} | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}}

/**
 * {name} - Custom hook for {name.replace("use", "").lower()} functionality.
 *
 * @returns {return_type}
 */
export function {name}(): {return_type} {{
  const [data, setData] = useState<{state_type} | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {{
    setLoading(true);
    setError(null);
    try {{
      // TODO: Implement fetch logic
      setData(null);
    }} catch (err) {{
      setError(err instanceof Error ? err : new Error('Unknown error'));
    }} finally {{
      setLoading(false);
    }}
  }}, []);

  return {{ data, loading, error, refetch }};
}}

export default {name};
"""

    def _generate_js_hook(self, name: str, options: dict[str, Any]) -> str:
        """Generate JavaScript hook content."""
        return f"""import {{ useState, useCallback }} from 'react';

/**
 * {name} - Custom hook for {name.replace("use", "").lower()} functionality.
 *
 * @returns {{{{ data: any, loading: boolean, error: Error | null, refetch: Function }}}}
 */
export function {name}() {{
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {{
    setLoading(true);
    setError(null);
    try {{
      // TODO: Implement fetch logic
      setData(null);
    }} catch (err) {{
      setError(err);
    }} finally {{
      setLoading(false);
    }}
  }}, []);

  return {{ data, loading, error, refetch }};
}}

export default {name};
"""

    def _generate_hook_test(self, name: str, lang: str) -> str:
        """Generate hook test file."""
        if lang == "typescript":
            return f"""import {{ renderHook, act }} from '@testing-library/react';
import {{ {name} }} from '../{name}';

describe('{name}', () => {{
  it('should return initial state', () => {{
    const {{ result }} = renderHook(() => {name}());

    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  }});

  it('should handle refetch', async () => {{
    const {{ result }} = renderHook(() => {name}());

    await act(async () => {{
      await result.current.refetch();
    }});

    // TODO: Add assertions for data after fetch
  }});
}});
"""
        return f"""import {{ renderHook, act }} from '@testing-library/react';
import {{ {name} }} from '../{name}';

describe('{name}', () => {{
  it('should return initial state', () => {{
    const {{ result }} = renderHook(() => {name}());

    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  }});
}});
"""

    def _generate_component(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a UI component."""
        name = self._to_pascal_case(name)
        patterns_used = []
        suggestions = []

        # Find components directory
        components_dir = self._find_similar_file("components/") or "src/components"

        lang = self._detect_language()

        if lang == "typescript":
            content = self._generate_ts_component(name, options)
            ext = ".tsx"
            test_ext = ".test.tsx"
        else:
            content = self._generate_js_component(name, options)
            ext = ".jsx"
            test_ext = ".test.jsx"

        # Primary file
        primary_path = f"{components_dir}/{name}{ext}"
        files = [
            GeneratedFile(
                path=primary_path,
                content=content,
                description=f"Component: {name}",
                is_primary=True,
            )
        ]

        # Check for component patterns
        component_patterns = self._get_patterns_by_category(PatternCategory.COMPONENTS)
        if component_patterns:
            patterns_used.append("component_classes")

        # Test file
        test_patterns = self._get_patterns_by_category(PatternCategory.TESTING)
        if test_patterns:
            patterns_used.append("test_file_organization")
            test_content = self._generate_component_test(name, lang)
            test_path = f"{components_dir}/__tests__/{name}{test_ext}"
            files.append(
                GeneratedFile(
                    path=test_path,
                    content=test_content,
                    description=f"Tests for {name}",
                    is_primary=False,
                )
            )

        return GenerateResult(
            template_type=TemplateType.COMPONENT,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=suggestions,
        )

    def _generate_ts_component(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript component."""
        props_interface = options.get("props", "")
        return f'''import React from 'react';

interface {name}Props {{
  {props_interface if props_interface else "// Add props here"}
}}

/**
 * {name} component.
 */
export function {name}({{ }}: {name}Props): React.ReactElement {{
  return (
    <div className="{self._to_camel_case(name)}">
      {{/* TODO: Implement {name} */}}
    </div>
  );
}}

export default {name};
'''

    def _generate_js_component(self, name: str, options: dict[str, Any]) -> str:
        """Generate JavaScript component."""
        return f'''import React from 'react';

/**
 * {name} component.
 */
export function {name}(props) {{
  return (
    <div className="{self._to_camel_case(name)}">
      {{/* TODO: Implement {name} */}}
    </div>
  );
}}

export default {name};
'''

    def _generate_component_test(self, name: str, lang: str) -> str:
        """Generate component test file."""
        return f"""import {{ render, screen }} from '@testing-library/react';
import {{ {name} }} from '../{name}';

describe('{name}', () => {{
  it('should render without crashing', () => {{
    render(<{name} />);
    // TODO: Add assertions
  }});
}});
"""

    def _generate_service(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a service class."""
        name = self._to_pascal_case(name)
        if not name.endswith("Service"):
            name = f"{name}Service"

        patterns_used = []
        suggestions = []

        # Check for service pattern
        arch_patterns = self._get_patterns_by_category(PatternCategory.ARCHITECTURE)
        has_service_pattern = any("service" in p.name.lower() for p in arch_patterns)
        if has_service_pattern:
            patterns_used.append("service_layer")

        lang = self._detect_language()

        if lang == "python":
            content = self._generate_py_service(name, options)
            ext = ".py"
            service_dir = self._find_similar_file("services/") or "src/services"
            test_ext = ".py"
            test_prefix = "test_"
        elif lang == "typescript":
            content = self._generate_ts_service(name, options)
            ext = ".ts"
            service_dir = self._find_similar_file("services/") or "src/services"
            test_ext = ".test.ts"
            test_prefix = ""
        else:
            content = self._generate_ts_service(name, options)
            ext = ".ts"
            service_dir = "src/services"
            test_ext = ".test.ts"
            test_prefix = ""

        snake_name = self._to_snake_case(name)
        primary_path = f"{service_dir}/{snake_name}{ext}"

        files = [
            GeneratedFile(
                path=primary_path,
                content=content,
                description=f"Service: {name}",
                is_primary=True,
            )
        ]

        # Test file
        test_patterns = self._get_patterns_by_category(PatternCategory.TESTING)
        if test_patterns:
            patterns_used.append("test_file_organization")
            test_content = self._generate_service_test(name, lang)
            if lang == "python":
                test_path = f"tests/unit/{test_prefix}{snake_name}{test_ext}"
            else:
                test_path = f"{service_dir}/__tests__/{snake_name}{test_ext}"
            files.append(
                GeneratedFile(
                    path=test_path,
                    content=test_content,
                    description=f"Tests for {name}",
                    is_primary=False,
                )
            )

        return GenerateResult(
            template_type=TemplateType.SERVICE,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=suggestions,
        )

    def _generate_py_service(self, name: str, options: dict[str, Any]) -> str:
        """Generate Python service class."""
        return f'''"""Service for {name.replace("Service", "").lower()} operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class {name}:
    """{name} handles business logic for {name.replace("Service", "").lower()} operations."""

    def get(self, id: str) -> dict | None:
        """Get an entity by ID.

        Args:
            id: The entity ID.

        Returns:
            The entity if found, None otherwise.
        """
        # TODO: Implement
        raise NotImplementedError

    def create(self, data: dict) -> dict:
        """Create a new entity.

        Args:
            data: The entity data.

        Returns:
            The created entity.
        """
        # TODO: Implement
        raise NotImplementedError

    def update(self, id: str, data: dict) -> dict | None:
        """Update an entity.

        Args:
            id: The entity ID.
            data: The updated data.

        Returns:
            The updated entity if found, None otherwise.
        """
        # TODO: Implement
        raise NotImplementedError

    def delete(self, id: str) -> bool:
        """Delete an entity.

        Args:
            id: The entity ID.

        Returns:
            True if deleted, False if not found.
        """
        # TODO: Implement
        raise NotImplementedError
'''

    def _generate_ts_service(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript service class."""
        entity = options.get("entity", "Entity")
        return f"""/**
 * {name} - Handles business logic for {name.replace("Service", "").lower()} operations.
 */
export class {name} {{
  /**
   * Get an entity by ID.
   */
  async get(id: string): Promise<{entity} | null> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  /**
   * Create a new entity.
   */
  async create(data: Partial<{entity}>): Promise<{entity}> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  /**
   * Update an entity.
   */
  async update(id: string, data: Partial<{entity}>): Promise<{entity} | null> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  /**
   * Delete an entity.
   */
  async delete(id: string): Promise<boolean> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}
}}

export default {name};
"""

    def _generate_service_test(self, name: str, lang: str) -> str:
        """Generate service test file."""
        snake_name = self._to_snake_case(name)
        if lang == "python":
            return f'''"""Tests for {name}."""

import pytest

from {snake_name} import {name}


class Test{name}:
    """Tests for {name}."""

    def test_get_returns_none_when_not_found(self) -> None:
        """Test that get returns None for missing entity."""
        service = {name}()
        # TODO: Implement test
        pass

    def test_create_returns_entity(self) -> None:
        """Test that create returns the created entity."""
        service = {name}()
        # TODO: Implement test
        pass
'''
        return f"""import {{ {name} }} from '../{snake_name}';

describe('{name}', () => {{
  let service: {name};

  beforeEach(() => {{
    service = new {name}();
  }});

  describe('get', () => {{
    it('should return null when entity not found', async () => {{
      const result = await service.get('non-existent');
      expect(result).toBeNull();
    }});
  }});
}});
"""

    def _generate_repository(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a repository/store class."""
        name = self._to_pascal_case(name)
        if not any(name.endswith(s) for s in ["Repository", "Repo", "Store"]):
            name = f"{name}Repository"

        patterns_used = []
        suggestions = []

        # Check for repository pattern
        arch_patterns = self._get_patterns_by_category(PatternCategory.ARCHITECTURE)
        has_repo_pattern = any("repository" in p.name.lower() for p in arch_patterns)
        if has_repo_pattern:
            patterns_used.append("repository_pattern")

        lang = self._detect_language()

        if lang == "python":
            content = self._generate_py_repository(name, options)
            ext = ".py"
        else:
            content = self._generate_ts_repository(name, options)
            ext = ".ts"

        snake_name = self._to_snake_case(name)
        repo_dir = self._find_similar_file("repositories/") or "src/repositories"

        files = [
            GeneratedFile(
                path=f"{repo_dir}/{snake_name}{ext}",
                content=content,
                description=f"Repository: {name}",
                is_primary=True,
            )
        ]

        return GenerateResult(
            template_type=TemplateType.REPOSITORY,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=suggestions,
        )

    def _generate_py_repository(self, name: str, options: dict[str, Any]) -> str:
        """Generate Python repository class."""
        return f'''"""Repository for {name.replace("Repository", "").lower()} data access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class {name}(ABC, Generic[T]):
    """Abstract repository for {name.replace("Repository", "").lower()} data access."""

    @abstractmethod
    def find_by_id(self, id: str) -> T | None:
        """Find entity by ID."""
        ...

    @abstractmethod
    def find_all(self) -> list[T]:
        """Find all entities."""
        ...

    @abstractmethod
    def save(self, entity: T) -> T:
        """Save an entity."""
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete an entity by ID."""
        ...
'''

    def _generate_ts_repository(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript repository class."""
        entity = options.get("entity", "Entity")
        return f"""/**
 * {name} - Data access layer for {name.replace("Repository", "").lower()} entities.
 */
export interface {name}<T> {{
  findById(id: string): Promise<T | null>;
  findAll(): Promise<T[]>;
  save(entity: T): Promise<T>;
  delete(id: string): Promise<boolean>;
}}

export class {name}Impl implements {name}<{entity}> {{
  async findById(id: string): Promise<{entity} | null> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  async findAll(): Promise<{entity}[]> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  async save(entity: {entity}): Promise<{entity}> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}

  async delete(id: string): Promise<boolean> {{
    // TODO: Implement
    throw new Error('Not implemented');
  }}
}}
"""

    def _generate_api_route(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate an API route handler."""
        snake_name = self._to_snake_case(name)
        patterns_used = []
        suggestions = []

        # Check for API patterns
        api_patterns = self._get_patterns_by_category(PatternCategory.API)
        if api_patterns:
            patterns_used.append("http_method_handlers")

        lang = self._detect_language()

        if lang == "python":
            content = self._generate_py_api_route(name, options)
            ext = ".py"
            route_dir = self._find_similar_file("routes/") or "src/routes"
        else:
            content = self._generate_ts_api_route(name, options)
            ext = ".ts"
            route_dir = self._find_similar_file("api/") or "src/app/api"

        files = [
            GeneratedFile(
                path=f"{route_dir}/{snake_name}{ext}",
                content=content,
                description=f"API route: {name}",
                is_primary=True,
            )
        ]

        return GenerateResult(
            template_type=TemplateType.API_ROUTE,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=suggestions,
        )

    def _generate_py_api_route(self, name: str, options: dict[str, Any]) -> str:
        """Generate Python API route (FastAPI style)."""
        snake_name = self._to_snake_case(name)
        return f'''"""API routes for {name}."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/{snake_name}", tags=["{name}"])


@router.get("/")
async def list_{snake_name}():
    """List all {name}s."""
    # TODO: Implement
    return []


@router.get("/{{id}}")
async def get_{snake_name}(id: str):
    """Get a {name} by ID."""
    # TODO: Implement
    raise HTTPException(status_code=404, detail="{name} not found")


@router.post("/")
async def create_{snake_name}(data: dict):
    """Create a new {name}."""
    # TODO: Implement
    return {{"id": "new", **data}}


@router.put("/{{id}}")
async def update_{snake_name}(id: str, data: dict):
    """Update a {name}."""
    # TODO: Implement
    return {{"id": id, **data}}


@router.delete("/{{id}}")
async def delete_{snake_name}(id: str):
    """Delete a {name}."""
    # TODO: Implement
    return {{"deleted": True}}
'''

    def _generate_ts_api_route(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript API route (Next.js App Router style)."""
        return f"""import {{ NextRequest, NextResponse }} from 'next/server';

/**
 * GET /{name.lower()} - List all {name}s
 */
export async function GET(request: NextRequest) {{
  try {{
    // TODO: Implement
    return NextResponse.json([]);
  }} catch (error) {{
    return NextResponse.json(
      {{ error: 'Failed to fetch {name}s' }},
      {{ status: 500 }}
    );
  }}
}}

/**
 * POST /{name.lower()} - Create a new {name}
 */
export async function POST(request: NextRequest) {{
  try {{
    const data = await request.json();
    // TODO: Implement
    return NextResponse.json({{ id: 'new', ...data }}, {{ status: 201 }});
  }} catch (error) {{
    return NextResponse.json(
      {{ error: 'Failed to create {name}' }},
      {{ status: 500 }}
    );
  }}
}}
"""

    def _generate_test(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a test file for an existing module."""
        snake_name = self._to_snake_case(name)
        patterns_used = []

        lang = self._detect_language()

        # Check for testing patterns
        test_patterns = self._get_patterns_by_category(PatternCategory.TESTING)
        if test_patterns:
            patterns_used.append("test_file_organization")

        if lang == "python":
            content = self._generate_py_test(name, options)
            test_path = f"tests/unit/test_{snake_name}.py"
        else:
            content = self._generate_ts_test(name, options)
            test_path = f"src/__tests__/{snake_name}.test.ts"

        files = [
            GeneratedFile(
                path=test_path,
                content=content,
                description=f"Tests for {name}",
                is_primary=True,
            )
        ]

        return GenerateResult(
            template_type=TemplateType.TEST,
            name=f"test_{snake_name}",
            files=files,
            patterns_used=patterns_used,
            suggestions=[],
        )

    def _generate_py_test(self, name: str, options: dict[str, Any]) -> str:
        """Generate Python test file."""
        pascal_name = self._to_pascal_case(name)
        return f'''"""Tests for {name}."""

import pytest


class Test{pascal_name}:
    """Test suite for {pascal_name}."""

    def test_placeholder(self) -> None:
        """Placeholder test - replace with real tests."""
        # TODO: Implement tests for {name}
        assert True
'''

    def _generate_ts_test(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript test file."""
        pascal_name = self._to_pascal_case(name)
        snake_name = self._to_snake_case(name)
        return f"""import {{ {pascal_name} }} from '../{snake_name}';

describe('{pascal_name}', () => {{
  it('should pass placeholder test', () => {{
    // TODO: Implement tests for {name}
    expect(true).toBe(true);
  }});
}});
"""

    def _generate_model(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a data model/entity class."""
        name = self._to_pascal_case(name)
        patterns_used = []

        # Check for model pattern
        arch_patterns = self._get_patterns_by_category(PatternCategory.ARCHITECTURE)
        has_model_pattern = any("model" in p.name.lower() for p in arch_patterns)
        if has_model_pattern:
            patterns_used.append("model_layer")

        lang = self._detect_language()
        fields = options.get("fields", [])

        if lang == "python":
            content = self._generate_py_model(name, fields)
            ext = ".py"
        else:
            content = self._generate_ts_model(name, fields)
            ext = ".ts"

        snake_name = self._to_snake_case(name)
        models_dir = self._find_similar_file("models/") or "src/models"

        files = [
            GeneratedFile(
                path=f"{models_dir}/{snake_name}{ext}",
                content=content,
                description=f"Model: {name}",
                is_primary=True,
            )
        ]

        return GenerateResult(
            template_type=TemplateType.MODEL,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=[],
        )

    def _generate_py_model(self, name: str, fields: list[dict[str, str]]) -> str:
        """Generate Python model (dataclass)."""
        field_lines = []
        for field in fields:
            field_name = field.get("name", "field")
            field_type = field.get("type", "str")
            field_lines.append(f"    {field_name}: {field_type}")

        fields_str = "\n".join(field_lines) if field_lines else "    pass"

        return f'''"""Data model for {name}."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class {name}:
    """{name} entity."""

    id: str
{fields_str}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {{
            "id": self.id,
            # TODO: Add fields
        }}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> {name}:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            # TODO: Add fields
        )
'''

    def _generate_ts_model(self, name: str, fields: list[dict[str, str]]) -> str:
        """Generate TypeScript model (interface + class)."""
        field_lines = []
        for f in fields:
            field_name = f.get("name", "field")
            field_type = f.get("type", "string")
            field_lines.append(f"  {field_name}: {field_type};")

        fields_str = "\n".join(field_lines) if field_lines else "  // Add fields here"

        return f"""/**
 * {name} entity interface.
 */
export interface I{name} {{
  id: string;
{fields_str}
}}

/**
 * {name} entity class.
 */
export class {name} implements I{name} {{
  id: string;

  constructor(data: Partial<I{name}>) {{
    this.id = data.id ?? '';
    // TODO: Initialize fields
  }}

  toJSON(): I{name} {{
    return {{
      id: this.id,
      // TODO: Add fields
    }};
  }}

  static fromJSON(data: I{name}): {name} {{
    return new {name}(data);
  }}
}}
"""

    def _generate_controller(self, name: str, options: dict[str, Any]) -> GenerateResult:
        """Generate a controller/handler class."""
        name = self._to_pascal_case(name)
        if not any(name.endswith(s) for s in ["Controller", "Handler"]):
            name = f"{name}Controller"

        patterns_used = []

        # Check for controller pattern
        arch_patterns = self._get_patterns_by_category(PatternCategory.ARCHITECTURE)
        has_controller_pattern = any("controller" in p.name.lower() for p in arch_patterns)
        if has_controller_pattern:
            patterns_used.append("controller_pattern")

        lang = self._detect_language()

        if lang == "python":
            content = self._generate_py_controller(name, options)
            ext = ".py"
        else:
            content = self._generate_ts_controller(name, options)
            ext = ".ts"

        snake_name = self._to_snake_case(name)
        controllers_dir = self._find_similar_file("controllers/") or "src/controllers"

        files = [
            GeneratedFile(
                path=f"{controllers_dir}/{snake_name}{ext}",
                content=content,
                description=f"Controller: {name}",
                is_primary=True,
            )
        ]

        return GenerateResult(
            template_type=TemplateType.CONTROLLER,
            name=name,
            files=files,
            patterns_used=patterns_used,
            suggestions=[],
        )

    def _generate_py_controller(self, name: str, options: dict[str, Any]) -> str:
        """Generate Python controller class."""
        service_name = name.replace("Controller", "Service")
        return f'''"""Controller for {name.replace("Controller", "").lower()} operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class {name}:
    """{name} handles incoming requests for {name.replace("Controller", "").lower()}."""

    # service: {service_name}

    def index(self) -> list[dict]:
        """List all resources."""
        # TODO: Implement
        return []

    def show(self, id: str) -> dict | None:
        """Show a single resource."""
        # TODO: Implement
        return None

    def create(self, data: dict) -> dict:
        """Create a new resource."""
        # TODO: Implement
        return data

    def update(self, id: str, data: dict) -> dict | None:
        """Update a resource."""
        # TODO: Implement
        return None

    def destroy(self, id: str) -> bool:
        """Delete a resource."""
        # TODO: Implement
        return False
'''

    def _generate_ts_controller(self, name: str, options: dict[str, Any]) -> str:
        """Generate TypeScript controller class."""
        service_name = name.replace("Controller", "Service")
        return f"""/**
 * {name} - Handles incoming requests for {name.replace("Controller", "").lower()}.
 */
export class {name} {{
  // private service: {service_name};

  /**
   * List all resources.
   */
  async index(): Promise<unknown[]> {{
    // TODO: Implement
    return [];
  }}

  /**
   * Show a single resource.
   */
  async show(id: string): Promise<unknown | null> {{
    // TODO: Implement
    return null;
  }}

  /**
   * Create a new resource.
   */
  async create(data: unknown): Promise<unknown> {{
    // TODO: Implement
    return data;
  }}

  /**
   * Update a resource.
   */
  async update(id: string, data: unknown): Promise<unknown | null> {{
    // TODO: Implement
    return null;
  }}

  /**
   * Delete a resource.
   */
  async destroy(id: string): Promise<boolean> {{
    // TODO: Implement
    return false;
  }}
}}
"""


__all__ = ["CodeGenerator"]
