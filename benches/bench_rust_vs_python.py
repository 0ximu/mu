"""Benchmarks comparing Rust core vs Python implementation.

Run with:
    pytest benches/bench_rust_vs_python.py -v --benchmark-enable

Or for a quick comparison:
    python benches/bench_rust_vs_python.py
"""

import tempfile
from pathlib import Path

import pytest

# Check if Rust core is available
try:
    from mu._core import parse_file as rust_parse_file
    from mu._core import parse_files as rust_parse_files
    from mu._core import (
        find_secrets as rust_find_secrets,
        redact_secrets as rust_redact_secrets,
        calculate_complexity as rust_calculate_complexity,
        FileInfo,
    )
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

from mu.parser import parse_file as py_parse_file


# Sample code for benchmarks - realistic file sizes
PYTHON_SMALL = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''

PYTHON_MEDIUM = '''
"""A medium-sized module for testing."""
import os
import sys
from typing import List, Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class User:
    """User model."""
    id: int
    name: str
    email: str
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "is_active": self.is_active,
        }


class UserService:
    """Service for managing users."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._users: Dict[int, User] = {}

    def create_user(self, name: str, email: str) -> User:
        """Create a new user."""
        user_id = len(self._users) + 1
        user = User(id=user_id, name=name, email=email)
        self._users[user_id] = user
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return self._users.get(user_id)

    def list_users(self, active_only: bool = False) -> List[User]:
        """List all users."""
        users = list(self._users.values())
        if active_only:
            users = [u for u in users if u.is_active]
        return users

    def update_user(self, user_id: int, **kwargs) -> Optional[User]:
        """Update user fields."""
        user = self._users.get(user_id)
        if not user:
            return None
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        return user

    def delete_user(self, user_id: int) -> bool:
        """Delete a user."""
        if user_id in self._users:
            del self._users[user_id]
            return True
        return False


def process_users(service: UserService, commands: List[Dict]) -> List[Any]:
    """Process a list of user commands."""
    results = []
    for cmd in commands:
        action = cmd.get("action")
        if action == "create":
            user = service.create_user(cmd["name"], cmd["email"])
            results.append(user.to_dict())
        elif action == "get":
            user = service.get_user(cmd["id"])
            results.append(user.to_dict() if user else None)
        elif action == "list":
            users = service.list_users(cmd.get("active_only", False))
            results.append([u.to_dict() for u in users])
        elif action == "delete":
            success = service.delete_user(cmd["id"])
            results.append({"deleted": success})
    return results
'''

PYTHON_LARGE = PYTHON_MEDIUM + '''

class OrderService:
    """Service for managing orders."""

    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self._orders: Dict[int, Dict] = {}

    def create_order(self, user_id: int, items: List[Dict]) -> Optional[Dict]:
        """Create a new order."""
        user = self.user_service.get_user(user_id)
        if not user:
            return None
        order_id = len(self._orders) + 1
        total = sum(item.get("price", 0) * item.get("quantity", 1) for item in items)
        order = {
            "id": order_id,
            "user_id": user_id,
            "items": items,
            "total": total,
            "status": "pending",
        }
        self._orders[order_id] = order
        return order

    def get_order(self, order_id: int) -> Optional[Dict]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def update_order_status(self, order_id: int, status: str) -> Optional[Dict]:
        """Update order status."""
        order = self._orders.get(order_id)
        if order:
            order["status"] = status
        return order


class InventoryService:
    """Service for managing inventory."""

    def __init__(self):
        self._items: Dict[str, int] = {}

    def add_stock(self, item_id: str, quantity: int) -> int:
        """Add stock for an item."""
        current = self._items.get(item_id, 0)
        self._items[item_id] = current + quantity
        return self._items[item_id]

    def remove_stock(self, item_id: str, quantity: int) -> Optional[int]:
        """Remove stock for an item."""
        current = self._items.get(item_id, 0)
        if current < quantity:
            return None
        self._items[item_id] = current - quantity
        return self._items[item_id]

    def get_stock(self, item_id: str) -> int:
        """Get current stock level."""
        return self._items.get(item_id, 0)

    def list_low_stock(self, threshold: int = 10) -> List[str]:
        """List items below threshold."""
        return [
            item_id
            for item_id, qty in self._items.items()
            if qty < threshold
        ]
''' * 3  # Repeat to make it larger


TYPESCRIPT_MEDIUM = '''
import { User, Order } from './types';
import { Database } from './database';

interface ServiceConfig {
    dbPath: string;
    maxConnections: number;
}

class UserService {
    private db: Database;
    private config: ServiceConfig;

    constructor(config: ServiceConfig) {
        this.config = config;
        this.db = new Database(config.dbPath);
    }

    async createUser(name: string, email: string): Promise<User> {
        const user = { id: Date.now(), name, email, isActive: true };
        await this.db.insert('users', user);
        return user;
    }

    async getUser(id: number): Promise<User | null> {
        return await this.db.findOne('users', { id });
    }

    async listUsers(activeOnly: boolean = false): Promise<User[]> {
        const query = activeOnly ? { isActive: true } : {};
        return await this.db.find('users', query);
    }

    async updateUser(id: number, updates: Partial<User>): Promise<User | null> {
        return await this.db.update('users', { id }, updates);
    }
}

class OrderService {
    private db: Database;
    private userService: UserService;

    constructor(db: Database, userService: UserService) {
        this.db = db;
        this.userService = userService;
    }

    async createOrder(userId: number, items: OrderItem[]): Promise<Order | null> {
        const user = await this.userService.getUser(userId);
        if (!user) return null;

        const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
        const order: Order = {
            id: Date.now(),
            userId,
            items,
            total,
            status: 'pending'
        };

        await this.db.insert('orders', order);
        return order;
    }
}

export { UserService, OrderService, ServiceConfig };
'''

CODE_WITH_SECRETS = '''
import os

# AWS credentials
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# GitHub token
GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

# Database connection
DB_URL = "postgresql://admin:supersecret123@db.example.com:5432/production"

# OpenAI API key
OPENAI_API_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"

def get_config():
    return {
        "aws_key": AWS_ACCESS_KEY,
        "db_url": DB_URL,
    }
'''

COMPLEX_CODE = '''
def complex_function(data, options=None):
    """A function with high cyclomatic complexity."""
    if not data:
        return None

    result = []
    for item in data:
        if item.get("type") == "A":
            if item.get("status") == "active":
                if item.get("priority") > 5:
                    result.append(process_high_priority(item))
                else:
                    result.append(process_normal(item))
            elif item.get("status") == "pending":
                result.append(process_pending(item))
            else:
                continue
        elif item.get("type") == "B":
            for sub in item.get("children", []):
                if sub.get("valid"):
                    try:
                        processed = transform(sub)
                        if processed:
                            result.append(processed)
                    except ValueError:
                        log_error(sub)
        elif item.get("type") == "C":
            match item.get("category"):
                case "cat1":
                    result.append(handle_cat1(item))
                case "cat2":
                    result.append(handle_cat2(item))
                case _:
                    result.append(handle_default(item))

    return result if result else None
'''


@pytest.fixture
def python_temp_file():
    """Create a temporary Python file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(PYTHON_MEDIUM)
        f.flush()
        yield Path(f.name)


@pytest.fixture
def multiple_files():
    """Create multiple temporary files."""
    files = []
    for i in range(100):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            code = f'''
def function_{i}(x: int) -> int:
    """Function {i}."""
    if x > 0:
        return x * 2
    return x

class Class_{i}:
    """Class {i}."""
    def method_{i}(self) -> str:
        return "result_{i}"
'''
            f.write(code)
            f.flush()
            files.append(Path(f.name))
    return files


class TestParsingSingleFile:
    """Benchmark single file parsing."""

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_parse_small(self, benchmark):
        """Rust: parse small Python file."""
        result = benchmark(rust_parse_file, PYTHON_SMALL, "test.py", "python")
        assert result.error is None

    def test_python_parse_small(self, benchmark, python_temp_file):
        """Python: parse small Python file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(PYTHON_SMALL)
            f.flush()
            path = Path(f.name)

        result = benchmark(py_parse_file, path, "python")
        assert result.success

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_parse_medium(self, benchmark):
        """Rust: parse medium Python file."""
        result = benchmark(rust_parse_file, PYTHON_MEDIUM, "test.py", "python")
        assert result.error is None

    def test_python_parse_medium(self, benchmark, python_temp_file):
        """Python: parse medium Python file."""
        result = benchmark(py_parse_file, python_temp_file, "python")
        assert result.success

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_parse_large(self, benchmark):
        """Rust: parse large Python file."""
        result = benchmark(rust_parse_file, PYTHON_LARGE, "test.py", "python")
        assert result.error is None

    def test_python_parse_large(self, benchmark):
        """Python: parse large Python file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(PYTHON_LARGE)
            f.flush()
            path = Path(f.name)

        result = benchmark(py_parse_file, path, "python")
        assert result.success

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_parse_typescript(self, benchmark):
        """Rust: parse TypeScript file."""
        result = benchmark(rust_parse_file, TYPESCRIPT_MEDIUM, "test.ts", "typescript")
        assert result.error is None


class TestParsingMultipleFiles:
    """Benchmark parallel file parsing."""

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_parse_100_files(self, benchmark, multiple_files):
        """Rust: parse 100 files in parallel."""
        file_infos = [
            FileInfo(path=str(f), source=f.read_text(), language="python")
            for f in multiple_files
        ]

        results = benchmark(rust_parse_files, file_infos)
        assert len(results) == 100
        assert all(r.error is None for r in results)

    def test_python_parse_100_files(self, benchmark, multiple_files):
        """Python: parse 100 files sequentially."""
        def parse_all():
            return [py_parse_file(f, "python") for f in multiple_files]

        results = benchmark(parse_all)
        assert len(results) == 100
        assert all(r.success for r in results)


class TestSecretDetection:
    """Benchmark secret detection."""

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_find_secrets(self, benchmark):
        """Rust: find secrets in code."""
        secrets = benchmark(rust_find_secrets, CODE_WITH_SECRETS)
        assert len(secrets) >= 4

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_redact_secrets(self, benchmark):
        """Rust: redact secrets from code."""
        redacted = benchmark(rust_redact_secrets, CODE_WITH_SECRETS)
        assert "REDACTED" in redacted
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted


class TestComplexity:
    """Benchmark complexity calculation."""

    @pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust core not available")
    def test_rust_complexity(self, benchmark):
        """Rust: calculate cyclomatic complexity."""
        complexity = benchmark(rust_calculate_complexity, COMPLEX_CODE, "python")
        assert complexity >= 10


def quick_comparison():
    """Quick comparison between Rust and Python (without pytest-benchmark)."""
    import time

    if not RUST_AVAILABLE:
        print("Rust core not available, skipping comparison")
        return

    print("=" * 60)
    print("Rust vs Python Performance Comparison")
    print("=" * 60)

    # Create temp files for Python parser
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(PYTHON_MEDIUM)
        f.flush()
        medium_path = Path(f.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(PYTHON_LARGE)
        f.flush()
        large_path = Path(f.name)

    # Single file parsing
    print("\n1. Single File Parsing (medium ~100 lines)")
    print("-" * 40)

    iterations = 100

    # Rust
    start = time.perf_counter()
    for _ in range(iterations):
        rust_parse_file(PYTHON_MEDIUM, "test.py", "python")
    rust_time = (time.perf_counter() - start) / iterations * 1000

    # Python
    start = time.perf_counter()
    for _ in range(iterations):
        py_parse_file(medium_path, "python")
    py_time = (time.perf_counter() - start) / iterations * 1000

    print(f"  Rust:   {rust_time:.3f} ms/file")
    print(f"  Python: {py_time:.3f} ms/file")
    print(f"  Speedup: {py_time / rust_time:.1f}x")

    # Large file parsing
    print("\n2. Large File Parsing (~300 lines)")
    print("-" * 40)

    iterations = 50

    # Rust
    start = time.perf_counter()
    for _ in range(iterations):
        rust_parse_file(PYTHON_LARGE, "test.py", "python")
    rust_time = (time.perf_counter() - start) / iterations * 1000

    # Python
    start = time.perf_counter()
    for _ in range(iterations):
        py_parse_file(large_path, "python")
    py_time = (time.perf_counter() - start) / iterations * 1000

    print(f"  Rust:   {rust_time:.3f} ms/file")
    print(f"  Python: {py_time:.3f} ms/file")
    print(f"  Speedup: {py_time / rust_time:.1f}x")

    # Multiple files (parallel vs sequential)
    print("\n3. Multiple Files (100 files)")
    print("-" * 40)

    # Create temp files
    temp_files = []
    for i in range(100):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(f"def func_{i}(): pass\nclass Class_{i}: pass\n")
            f.flush()
            temp_files.append(Path(f.name))

    file_infos = [
        FileInfo(path=str(f), source=f.read_text(), language="python")
        for f in temp_files
    ]

    # Rust (parallel)
    start = time.perf_counter()
    rust_parse_files(file_infos)
    rust_time = (time.perf_counter() - start) * 1000

    # Python (sequential)
    start = time.perf_counter()
    for f in temp_files:
        py_parse_file(f, "python")
    py_time = (time.perf_counter() - start) * 1000

    print(f"  Rust (parallel):     {rust_time:.1f} ms")
    print(f"  Python (sequential): {py_time:.1f} ms")
    print(f"  Speedup: {py_time / rust_time:.1f}x")

    # Secret detection
    print("\n4. Secret Detection")
    print("-" * 40)

    iterations = 1000

    start = time.perf_counter()
    for _ in range(iterations):
        rust_find_secrets(CODE_WITH_SECRETS)
    rust_time = (time.perf_counter() - start) / iterations * 1000

    print(f"  Rust: {rust_time:.3f} ms/scan")

    # Complexity calculation
    print("\n5. Complexity Calculation")
    print("-" * 40)

    iterations = 1000

    start = time.perf_counter()
    for _ in range(iterations):
        rust_calculate_complexity(COMPLEX_CODE, "python")
    rust_time = (time.perf_counter() - start) / iterations * 1000

    print(f"  Rust: {rust_time:.3f} ms/calculation")

    print("\n" + "=" * 60)
    print("Summary: Rust core provides significant speedups, especially")
    print("for parallel operations and large files.")
    print("=" * 60)


if __name__ == "__main__":
    quick_comparison()
