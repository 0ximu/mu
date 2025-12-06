"""Security module for MU - secret detection and redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class SecretCategory(Enum):
    """Categories of secrets for classification."""

    API_KEY = "api_key"
    PRIVATE_KEY = "private_key"
    PASSWORD = "password"
    TOKEN = "token"
    CONNECTION_STRING = "connection_string"
    CERTIFICATE = "certificate"
    OTHER = "other"


@dataclass
class SecretPattern:
    """Definition of a secret pattern for detection."""

    name: str
    pattern: str  # Regex pattern
    category: SecretCategory
    description: str
    confidence: float = 1.0  # 0.0-1.0, how confident the match is a real secret
    _compiled: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    def compile(self) -> re.Pattern[str]:
        """Compile and cache the regex pattern."""
        if self._compiled is None:
            self._compiled = re.compile(self.pattern, re.MULTILINE | re.IGNORECASE)
        return self._compiled


@dataclass
class RedactedSecret:
    """Information about a redacted secret."""

    pattern_name: str
    category: SecretCategory
    line_number: int
    start_pos: int
    end_pos: int
    original_length: int
    replacement: str


@dataclass
class ScanResult:
    """Result of scanning source code for secrets."""

    source: str  # Original source
    redacted_source: str  # Source with secrets replaced
    secrets: list[RedactedSecret] = field(default_factory=list)
    total_secrets_found: int = 0

    @property
    def has_secrets(self) -> bool:
        """Check if any secrets were found."""
        return self.total_secrets_found > 0


# Default patterns for common secret types
# These patterns are intentionally designed to have low false-positive rates
DEFAULT_PATTERNS: list[SecretPattern] = [
    # AWS
    SecretPattern(
        name="aws_access_key",
        pattern=r"(?:A3T[A-Z0-9]|AKIA|AIPA|AROA|AIDA|ASIA)[A-Z0-9]{16}",
        category=SecretCategory.API_KEY,
        description="AWS Access Key ID",
    ),
    SecretPattern(
        name="aws_secret_key",
        pattern=r"(?i)(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?",
        category=SecretCategory.API_KEY,
        description="AWS Secret Access Key",
    ),

    # GCP
    SecretPattern(
        name="gcp_api_key",
        pattern=r"AIza[0-9A-Za-z\-_]{35}",
        category=SecretCategory.API_KEY,
        description="Google Cloud Platform API Key",
    ),
    SecretPattern(
        name="gcp_service_account",
        pattern=r'"type"\s*:\s*"service_account"',
        category=SecretCategory.API_KEY,
        description="GCP Service Account JSON",
        confidence=0.9,
    ),

    # Azure
    SecretPattern(
        name="azure_storage_key",
        pattern=r"(?i)(?:AccountKey|azure_storage_key)\s*[=:]\s*['\"]?([A-Za-z0-9+/=]{88})['\"]?",
        category=SecretCategory.API_KEY,
        description="Azure Storage Account Key",
    ),
    SecretPattern(
        name="azure_connection_string",
        pattern=r"(?i)DefaultEndpointsProtocol=https?;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]+",
        category=SecretCategory.CONNECTION_STRING,
        description="Azure Storage Connection String",
    ),

    # Stripe
    SecretPattern(
        name="stripe_secret_key",
        pattern=r"sk_live_[0-9a-zA-Z]{24,}",
        category=SecretCategory.API_KEY,
        description="Stripe Secret Key (Live)",
    ),
    SecretPattern(
        name="stripe_test_key",
        pattern=r"sk_test_[0-9a-zA-Z]{24,}",
        category=SecretCategory.API_KEY,
        description="Stripe Secret Key (Test)",
        confidence=0.8,  # Test keys are less sensitive
    ),
    SecretPattern(
        name="stripe_restricted_key",
        pattern=r"rk_live_[0-9a-zA-Z]{24,}",
        category=SecretCategory.API_KEY,
        description="Stripe Restricted Key (Live)",
    ),

    # GitHub
    SecretPattern(
        name="github_pat",
        pattern=r"ghp_[0-9a-zA-Z]{36}",
        category=SecretCategory.TOKEN,
        description="GitHub Personal Access Token",
    ),
    SecretPattern(
        name="github_oauth",
        pattern=r"gho_[0-9a-zA-Z]{36}",
        category=SecretCategory.TOKEN,
        description="GitHub OAuth Token",
    ),
    SecretPattern(
        name="github_app_token",
        pattern=r"(?:ghu|ghs)_[0-9a-zA-Z]{36}",
        category=SecretCategory.TOKEN,
        description="GitHub App Token",
    ),
    SecretPattern(
        name="github_refresh_token",
        pattern=r"ghr_[0-9a-zA-Z]{36}",
        category=SecretCategory.TOKEN,
        description="GitHub Refresh Token",
    ),

    # GitLab
    SecretPattern(
        name="gitlab_pat",
        pattern=r"glpat-[0-9a-zA-Z\-_]{20,}",
        category=SecretCategory.TOKEN,
        description="GitLab Personal Access Token",
    ),

    # Slack
    SecretPattern(
        name="slack_token",
        pattern=r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*",
        category=SecretCategory.TOKEN,
        description="Slack Token",
    ),
    SecretPattern(
        name="slack_webhook",
        pattern=r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]+",
        category=SecretCategory.TOKEN,
        description="Slack Webhook URL",
    ),

    # Twilio
    SecretPattern(
        name="twilio_api_key",
        pattern=r"SK[0-9a-fA-F]{32}",
        category=SecretCategory.API_KEY,
        description="Twilio API Key",
    ),

    # SendGrid
    SecretPattern(
        name="sendgrid_api_key",
        pattern=r"SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}",
        category=SecretCategory.API_KEY,
        description="SendGrid API Key",
    ),

    # OpenAI
    SecretPattern(
        name="openai_api_key",
        pattern=r"sk-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20}",
        category=SecretCategory.API_KEY,
        description="OpenAI API Key (Legacy)",
    ),
    SecretPattern(
        name="openai_api_key_v2",
        pattern=r"sk-proj-[a-zA-Z0-9_-]{48,}",
        category=SecretCategory.API_KEY,
        description="OpenAI API Key (Project)",
    ),

    # Anthropic
    SecretPattern(
        name="anthropic_api_key",
        pattern=r"sk-ant-api[0-9]{2}-[a-zA-Z0-9_-]{95}",
        category=SecretCategory.API_KEY,
        description="Anthropic API Key",
    ),

    # Private Keys
    SecretPattern(
        name="rsa_private_key",
        pattern=r"-----BEGIN RSA PRIVATE KEY-----",
        category=SecretCategory.PRIVATE_KEY,
        description="RSA Private Key Header",
    ),
    SecretPattern(
        name="openssh_private_key",
        pattern=r"-----BEGIN OPENSSH PRIVATE KEY-----",
        category=SecretCategory.PRIVATE_KEY,
        description="OpenSSH Private Key Header",
    ),
    SecretPattern(
        name="ec_private_key",
        pattern=r"-----BEGIN EC PRIVATE KEY-----",
        category=SecretCategory.PRIVATE_KEY,
        description="EC Private Key Header",
    ),
    SecretPattern(
        name="pgp_private_key",
        pattern=r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
        category=SecretCategory.PRIVATE_KEY,
        description="PGP Private Key Header",
    ),
    SecretPattern(
        name="dsa_private_key",
        pattern=r"-----BEGIN DSA PRIVATE KEY-----",
        category=SecretCategory.PRIVATE_KEY,
        description="DSA Private Key Header",
    ),
    SecretPattern(
        name="encrypted_private_key",
        pattern=r"-----BEGIN ENCRYPTED PRIVATE KEY-----",
        category=SecretCategory.PRIVATE_KEY,
        description="Encrypted Private Key Header",
    ),

    # JWT tokens
    SecretPattern(
        name="jwt_token",
        pattern=r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        category=SecretCategory.TOKEN,
        description="JSON Web Token (JWT)",
        confidence=0.85,  # JWTs can appear in legitimate test code
    ),

    # Database connection strings
    SecretPattern(
        name="postgres_connection",
        pattern=r"(?i)postgres(?:ql)?://[^:]+:[^@]+@[^/]+/[^\s'\"]+",
        category=SecretCategory.CONNECTION_STRING,
        description="PostgreSQL Connection String",
    ),
    SecretPattern(
        name="mysql_connection",
        pattern=r"(?i)mysql://[^:]+:[^@]+@[^/]+/[^\s'\"]+",
        category=SecretCategory.CONNECTION_STRING,
        description="MySQL Connection String",
    ),
    SecretPattern(
        name="mongodb_connection",
        pattern=r"mongodb(?:\+srv)?://[^:]+:[^@]+@[^\s'\"]+",
        category=SecretCategory.CONNECTION_STRING,
        description="MongoDB Connection String",
    ),
    SecretPattern(
        name="redis_connection",
        pattern=r"redis://[^:]*:[^@]+@[^/]+",
        category=SecretCategory.CONNECTION_STRING,
        description="Redis Connection String with Password",
    ),

    # Generic password patterns (variable assignments)
    SecretPattern(
        name="password_assignment",
        pattern=r"(?i)(?:password|passwd|pwd|secret|api_key|apikey|access_token|auth_token)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
        category=SecretCategory.PASSWORD,
        description="Password/Secret Assignment",
        confidence=0.7,  # Higher false positive rate
    ),

    # Heroku
    SecretPattern(
        name="heroku_api_key",
        pattern=r"(?i)heroku.*['\"][0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}['\"]",
        category=SecretCategory.API_KEY,
        description="Heroku API Key",
    ),

    # NPM
    SecretPattern(
        name="npm_token",
        pattern=r"(?i)//registry\.npmjs\.org/:_authToken=.+",
        category=SecretCategory.TOKEN,
        description="NPM Auth Token",
    ),

    # Firebase
    SecretPattern(
        name="firebase_api_key",
        pattern=r"(?i)firebase.*['\"]AIza[0-9A-Za-z\-_]{35}['\"]",
        category=SecretCategory.API_KEY,
        description="Firebase API Key",
    ),

    # Generic high-entropy secrets (hex strings that look like secrets)
    SecretPattern(
        name="generic_secret_hex",
        pattern=r"(?i)(?:secret|token|key|password|credential)[_-]?(?:key|token|secret)?\s*[=:]\s*['\"]?[a-f0-9]{32,64}['\"]?",
        category=SecretCategory.OTHER,
        description="Generic Secret (Hex)",
        confidence=0.6,
    ),
]


class SecretScanner:
    """Scans source code for secrets and redacts them."""

    def __init__(
        self,
        patterns: list[SecretPattern] | None = None,
        min_confidence: float = 0.0,
    ):
        """Initialize the scanner.

        Args:
            patterns: List of patterns to use. Defaults to DEFAULT_PATTERNS.
            min_confidence: Minimum confidence threshold for matches.
        """
        self.patterns = patterns or DEFAULT_PATTERNS
        self.min_confidence = min_confidence

        # Pre-compile all patterns
        for pattern in self.patterns:
            pattern.compile()

    def scan(
        self,
        source: str,
        redact: bool = True,
    ) -> ScanResult:
        """Scan source code for secrets.

        Args:
            source: Source code to scan.
            redact: Whether to produce redacted output.

        Returns:
            ScanResult with findings and optionally redacted source.
        """
        secrets: list[RedactedSecret] = []
        redacted_source = source if redact else source

        # Track all matches to handle overlapping patterns
        all_matches: list[tuple[int, int, SecretPattern, re.Match[str]]] = []

        for pattern in self.patterns:
            if pattern.confidence < self.min_confidence:
                continue

            compiled = pattern.compile()
            for match in compiled.finditer(source):
                all_matches.append((match.start(), match.end(), pattern, match))

        # Sort by start position, then by length (longer matches first)
        all_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        # Remove overlapping matches (keep longer ones)
        filtered_matches: list[tuple[int, int, SecretPattern, re.Match[str]]] = []
        last_end = -1
        for start, end, pattern, match in all_matches:
            if start >= last_end:
                filtered_matches.append((start, end, pattern, match))
                last_end = end

        # Process matches in reverse order to maintain position validity
        for start, end, pattern, _match in reversed(filtered_matches):
            # Calculate line number
            line_number = source[:start].count("\n") + 1

            # Create replacement
            replacement = f":: REDACTED:{pattern.name}"

            secret = RedactedSecret(
                pattern_name=pattern.name,
                category=pattern.category,
                line_number=line_number,
                start_pos=start,
                end_pos=end,
                original_length=end - start,
                replacement=replacement,
            )
            secrets.append(secret)

            if redact:
                redacted_source = (
                    redacted_source[:start] + replacement + redacted_source[end:]
                )

        # Reverse to get chronological order
        secrets.reverse()

        return ScanResult(
            source=source,
            redacted_source=redacted_source,
            secrets=secrets,
            total_secrets_found=len(secrets),
        )

    def scan_file(
        self,
        file_path: str,
        redact: bool = True,
    ) -> ScanResult:
        """Scan a file for secrets.

        Args:
            file_path: Path to the file to scan.
            redact: Whether to produce redacted output.

        Returns:
            ScanResult with findings.
        """
        with open(file_path) as f:
            source = f.read()
        return self.scan(source, redact=redact)


def redact_secrets(
    source: str,
    patterns: list[SecretPattern] | None = None,
    min_confidence: float = 0.0,
) -> tuple[str, list[RedactedSecret]]:
    """Convenience function to redact secrets from source code.

    Args:
        source: Source code to scan.
        patterns: Optional list of patterns. Defaults to DEFAULT_PATTERNS.
        min_confidence: Minimum confidence threshold.

    Returns:
        Tuple of (redacted_source, list of RedactedSecret).
    """
    scanner = SecretScanner(patterns=patterns, min_confidence=min_confidence)
    result = scanner.scan(source, redact=True)
    return result.redacted_source, result.secrets


def load_custom_patterns(file_path: str) -> list[SecretPattern]:
    """Load custom patterns from a TOML file.

    Expected format:
    [[patterns]]
    name = "my_secret"
    pattern = "MY_SECRET_[A-Z0-9]{32}"
    category = "api_key"
    description = "My custom secret"
    confidence = 1.0
    """
    import tomllib
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Pattern file not found: {file_path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    patterns = []
    for p in data.get("patterns", []):
        category = SecretCategory(p.get("category", "other"))
        patterns.append(
            SecretPattern(
                name=p["name"],
                pattern=p["pattern"],
                category=category,
                description=p.get("description", ""),
                confidence=p.get("confidence", 1.0),
            )
        )

    return patterns


# Public API
__all__ = [
    "SecretCategory",
    "SecretPattern",
    "RedactedSecret",
    "ScanResult",
    "SecretScanner",
    "DEFAULT_PATTERNS",
    "redact_secrets",
    "load_custom_patterns",
]
