"""MU Scanner - Codebase filesystem analysis."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from mu.config import MUConfig
from mu.logging import get_logger

# Language detection by file extension
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
}

# Supported languages for MU transformation
SUPPORTED_LANGUAGES = {"python", "typescript", "javascript", "csharp", "go", "rust", "java"}


@dataclass
class FileInfo:
    """Information about a scanned file."""

    path: str
    language: str
    size_bytes: int
    hash: str
    lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "hash": self.hash,
            "lines": self.lines,
        }


@dataclass
class SkippedItem:
    """Information about a skipped file or directory."""

    path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "reason": self.reason}


@dataclass
class ScanStats:
    """Statistics from a codebase scan."""

    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "languages": self.languages,
        }


@dataclass
class ScanResult:
    """Result of scanning a codebase."""

    version: str = "1.0"
    root: str = ""
    scanned_at: str = ""
    files: list[FileInfo] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)
    skipped: list[SkippedItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": self.root,
            "scanned_at": self.scanned_at,
            "files": [f.to_dict() for f in self.files],
            "stats": self.stats.to_dict(),
            "skipped": [s.to_dict() for s in self.skipped],
        }


def detect_language(file_path: Path) -> str | None:
    """Detect programming language from file extension."""
    ext = file_path.suffix.lower()
    return LANGUAGE_EXTENSIONS.get(ext)


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file content."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()[:16]}"


def count_lines(file_path: Path) -> int:
    """Count lines in a file."""
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def should_ignore(path: Path, ignore_patterns: list[str], root: Path) -> str | None:
    """Check if path should be ignored. Returns reason if ignored, None otherwise."""
    rel_path = str(path.relative_to(root))

    # Check against ignore patterns
    for pattern in ignore_patterns:
        # Handle directory patterns (ending with /)
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")
            if any(part == dir_pattern for part in path.parts):
                return "ignore_pattern"
        # Handle glob patterns
        elif fnmatch(rel_path, pattern) or fnmatch(path.name, pattern):
            return "ignore_pattern"

    return None


def scan_codebase(root: Path, config: MUConfig) -> ScanResult:
    """Scan a codebase and return structured manifest.

    Args:
        root: Root directory to scan
        config: MU configuration

    Returns:
        ScanResult with file information and statistics
    """
    logger = get_logger()
    root = root.resolve()

    result = ScanResult(
        root=str(root),
        scanned_at=datetime.now(UTC).isoformat(),
    )

    ignore_patterns = config.scanner.ignore
    max_size = config.scanner.max_file_size_kb * 1024
    include_hidden = config.scanner.include_hidden

    logger.info(f"Scanning {root}")
    logger.debug(f"Ignore patterns: {ignore_patterns}")

    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)

        # Filter hidden directories if not included
        if not include_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        # Filter ignored directories
        filtered_dirs = []
        for dirname in dirnames:
            dir_path = current_dir / dirname
            reason = should_ignore(dir_path, ignore_patterns, root)
            if reason:
                result.skipped.append(
                    SkippedItem(
                        path=str(dir_path.relative_to(root)),
                        reason=reason,
                    )
                )
            else:
                filtered_dirs.append(dirname)
        dirnames[:] = filtered_dirs

        # Process files
        for filename in filenames:
            file_path = current_dir / filename

            # Skip hidden files if not included
            if not include_hidden and filename.startswith("."):
                continue

            # Check ignore patterns
            reason = should_ignore(file_path, ignore_patterns, root)
            if reason:
                result.skipped.append(
                    SkippedItem(
                        path=str(file_path.relative_to(root)),
                        reason=reason,
                    )
                )
                continue

            # Check file size
            try:
                size = file_path.stat().st_size
                if size > max_size:
                    result.skipped.append(
                        SkippedItem(
                            path=str(file_path.relative_to(root)),
                            reason="file_too_large",
                        )
                    )
                    continue
            except OSError:
                continue

            # Detect language
            language = detect_language(file_path)
            if language is None:
                result.skipped.append(
                    SkippedItem(
                        path=str(file_path.relative_to(root)),
                        reason="unknown_extension",
                    )
                )
                continue

            # Check if language is supported (for non-config files)
            if language not in SUPPORTED_LANGUAGES and language not in {
                "yaml",
                "json",
                "toml",
                "markdown",
            }:
                result.skipped.append(
                    SkippedItem(
                        path=str(file_path.relative_to(root)),
                        reason="unsupported_language",
                    )
                )
                continue

            # Gather file info
            lines = count_lines(file_path)
            file_hash = compute_file_hash(file_path)

            file_info = FileInfo(
                path=str(file_path.relative_to(root)),
                language=language,
                size_bytes=size,
                hash=file_hash,
                lines=lines,
            )
            result.files.append(file_info)

            # Update stats
            result.stats.total_files += 1
            result.stats.total_lines += lines
            result.stats.languages[language] = result.stats.languages.get(language, 0) + 1

    logger.info(f"Found {result.stats.total_files} files, {result.stats.total_lines} lines")
    return result
