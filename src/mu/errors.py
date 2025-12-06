"""Error handling framework for MU CLI."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """MU CLI exit codes."""

    SUCCESS = 0
    CONFIG_ERROR = 1  # Configuration/auth error (user fixable)
    PARTIAL_SUCCESS = 2  # Some files skipped
    FATAL_ERROR = 3  # Unexpected crash
    GIT_ERROR = 4  # Git operation failed


class MUError(Exception):
    """Base exception for MU errors."""

    exit_code: ExitCode = ExitCode.FATAL_ERROR

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for JSON output."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "exit_code": self.exit_code,
            **self.context,
        }


class ConfigError(MUError):
    """Configuration-related errors."""

    exit_code = ExitCode.CONFIG_ERROR


class ParseError(MUError):
    """File parsing errors."""

    exit_code = ExitCode.PARTIAL_SUCCESS

    def __init__(self, message: str, file_path: str, line: int | None = None, **context: Any):
        super().__init__(message, file_path=file_path, line=line, **context)
        self.file_path = file_path
        self.line = line


class UnsupportedLanguageError(MUError):
    """Language not supported."""

    exit_code = ExitCode.PARTIAL_SUCCESS

    def __init__(self, language: str, file_path: str):
        super().__init__(
            f"Unsupported language: {language}",
            language=language,
            file_path=file_path,
        )
        self.language = language
        self.file_path = file_path


class LLMError(MUError):
    """LLM API errors."""

    exit_code = ExitCode.PARTIAL_SUCCESS


class LLMAuthError(LLMError):
    """LLM authentication failure."""

    exit_code = ExitCode.CONFIG_ERROR


class LLMRateLimitError(LLMError):
    """LLM rate limit exceeded."""

    pass


class LLMTimeoutError(LLMError):
    """LLM request timeout."""

    pass


class SecurityError(MUError):
    """Security-related errors."""

    exit_code = ExitCode.CONFIG_ERROR


class CacheError(MUError):
    """Cache-related errors."""

    exit_code = ExitCode.PARTIAL_SUCCESS


class ProcessingResult:
    """Result of processing a file or batch of files."""

    def __init__(self) -> None:
        self.processed: list[str] = []
        self.skipped: list[dict[str, Any]] = []
        self.errors: list[MUError] = []

    @property
    def success(self) -> bool:
        """True if no fatal errors occurred."""
        return not any(e.exit_code == ExitCode.FATAL_ERROR for e in self.errors)

    @property
    def exit_code(self) -> ExitCode:
        """Determine exit code based on results."""
        if not self.errors:
            return ExitCode.SUCCESS
        if any(e.exit_code == ExitCode.CONFIG_ERROR for e in self.errors):
            return ExitCode.CONFIG_ERROR
        if any(e.exit_code == ExitCode.FATAL_ERROR for e in self.errors):
            return ExitCode.FATAL_ERROR
        if self.skipped or self.errors:
            return ExitCode.PARTIAL_SUCCESS
        return ExitCode.SUCCESS

    def add_processed(self, file_path: str) -> None:
        """Mark a file as successfully processed."""
        self.processed.append(file_path)

    def add_skipped(self, file_path: str, reason: str) -> None:
        """Mark a file as skipped."""
        self.skipped.append({"path": file_path, "reason": reason})

    def add_error(self, error: MUError) -> None:
        """Record an error."""
        self.errors.append(error)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for JSON output."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "processed": len(self.processed),
            "skipped": len(self.skipped),
            "errors": [e.to_dict() for e in self.errors],
            "skipped_files": self.skipped,
        }
