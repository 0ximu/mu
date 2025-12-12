"""Error handling framework for MU CLI."""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any


class ErrorCategory(Enum):
    """Categories for error classification and handling."""

    USER = "user"  # User misconfiguration, bad input
    SYSTEM = "system"  # Infrastructure/environment issues
    NETWORK = "network"  # External service failures
    DATA = "data"  # Malformed/corrupt data
    PERMISSION = "permission"  # Access denied
    TIMEOUT = "timeout"  # Operation timeout
    RESOURCE = "resource"  # Resource exhaustion (memory, disk)


class ExitCode(IntEnum):
    """MU CLI exit codes."""

    SUCCESS = 0
    CONFIG_ERROR = 1  # Configuration/auth error (user fixable)
    PARTIAL_SUCCESS = 2  # Some files skipped
    FATAL_ERROR = 3  # Unexpected crash
    GIT_ERROR = 4  # Git operation failed
    CONTRACT_VIOLATION = 5  # Architecture contract violated


class MUError(Exception):
    """Base exception for MU errors."""

    category: ErrorCategory = ErrorCategory.SYSTEM
    exit_code: ExitCode = ExitCode.FATAL_ERROR

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
        **extra_context: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        # Support both dict-style and kwargs-style context for backwards compatibility
        self.context = {**(context or {}), **extra_context}
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for JSON output."""
        result = {
            "error": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "exit_code": self.exit_code,
            **self.context,
        }
        if self.__cause__ is not None:
            result["cause"] = str(self.__cause__)
        return result


class ConfigError(MUError):
    """Configuration-related errors."""

    category = ErrorCategory.USER
    exit_code = ExitCode.CONFIG_ERROR


class ParseError(MUError):
    """File parsing errors."""

    category = ErrorCategory.DATA
    exit_code = ExitCode.PARTIAL_SUCCESS

    def __init__(
        self,
        message: str,
        file_path: str,
        line: int | None = None,
        cause: Exception | None = None,
        **context: Any,
    ):
        super().__init__(message, cause=cause, file_path=file_path, line=line, **context)
        self.file_path = file_path
        self.line = line


class UnsupportedLanguageError(MUError):
    """Language not supported."""

    category = ErrorCategory.DATA
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

    category = ErrorCategory.NETWORK
    exit_code = ExitCode.PARTIAL_SUCCESS


class LLMAuthError(LLMError):
    """LLM authentication failure."""

    category = ErrorCategory.PERMISSION
    exit_code = ExitCode.CONFIG_ERROR


class LLMRateLimitError(LLMError):
    """LLM rate limit exceeded."""

    category = ErrorCategory.NETWORK


class LLMTimeoutError(LLMError):
    """LLM request timeout."""

    category = ErrorCategory.TIMEOUT


class SecurityError(MUError):
    """Security-related errors."""

    category = ErrorCategory.PERMISSION
    exit_code = ExitCode.CONFIG_ERROR


class CacheError(MUError):
    """Cache-related errors."""

    category = ErrorCategory.SYSTEM
    exit_code = ExitCode.PARTIAL_SUCCESS


class MUTimeoutError(MUError):
    """Operation timed out (generic, non-LLM timeouts)."""

    category = ErrorCategory.TIMEOUT
    exit_code = ExitCode.FATAL_ERROR


class ResourceError(MUError):
    """Resource exhaustion errors (memory, disk, etc)."""

    category = ErrorCategory.RESOURCE
    exit_code = ExitCode.FATAL_ERROR


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


# Category-specific hints for user-friendly error messages
_CATEGORY_HINTS: dict[ErrorCategory, str] = {
    ErrorCategory.USER: "Check your configuration or input",
    ErrorCategory.SYSTEM: "This may be a bug - please report it",
    ErrorCategory.NETWORK: "Check your network connection and try again",
    ErrorCategory.DATA: "The data may be malformed or corrupted",
    ErrorCategory.PERMISSION: "Check your credentials or permissions",
    ErrorCategory.TIMEOUT: "The operation took too long - try again or increase timeout",
    ErrorCategory.RESOURCE: "System resources may be exhausted (memory, disk)",
}


def format_error_for_user(error: MUError, *, verbose: bool = False) -> str:
    """Format an error for CLI display with helpful context.

    Args:
        error: The MUError instance to format.
        verbose: If True, include additional details like cause chain.

    Returns:
        A user-friendly formatted error message.
    """
    lines = [f"Error: {error.message}"]

    # Add category-specific hint
    hint = _CATEGORY_HINTS.get(error.category)
    if hint:
        lines.append(f"Hint: {hint}")

    # Add context if available
    if error.context:
        context_items = [f"  {k}: {v}" for k, v in error.context.items() if v is not None]
        if context_items:
            lines.append("Context:")
            lines.extend(context_items)

    # Add cause chain in verbose mode
    if verbose and error.__cause__ is not None:
        lines.append(f"Caused by: {type(error.__cause__).__name__}: {error.__cause__}")

    return "\n".join(lines)


def get_error_hint(category: ErrorCategory) -> str:
    """Get the hint message for an error category.

    Args:
        category: The error category.

    Returns:
        The hint message for the category.
    """
    return _CATEGORY_HINTS.get(category, "An unexpected error occurred")
