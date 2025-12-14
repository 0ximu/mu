"""Tests for MU security module - secret detection and redaction."""

import pytest
from pathlib import Path

from mu.security import (
    SecretCategory,
    SecretPattern,
    RedactedSecret,
    ScanResult,
    SecretScanner,
    DEFAULT_PATTERNS,
    redact_secrets,
)


class TestSecretPattern:
    """Test SecretPattern dataclass."""

    def test_pattern_creation(self):
        """Test creating a secret pattern."""
        pattern = SecretPattern(
            name="test_secret",
            pattern=r"SECRET_[A-Z0-9]{16}",
            category=SecretCategory.API_KEY,
            description="Test secret pattern",
        )

        assert pattern.name == "test_secret"
        assert pattern.category == SecretCategory.API_KEY
        assert pattern.confidence == 1.0

    def test_pattern_compile(self):
        """Test pattern compilation."""
        pattern = SecretPattern(
            name="test",
            pattern=r"\d{4}-\d{4}",
            category=SecretCategory.OTHER,
            description="Test",
        )

        compiled = pattern.compile()
        assert compiled is not None

        # Should cache the compiled pattern
        assert pattern.compile() is compiled

    def test_pattern_match(self):
        """Test pattern matching."""
        pattern = SecretPattern(
            name="test",
            pattern=r"API_KEY_[A-Z]{8}",
            category=SecretCategory.API_KEY,
            description="Test",
        )

        compiled = pattern.compile()
        assert compiled.search("my API_KEY_ABCDEFGH here")
        assert not compiled.search("no key here")


class TestSecretScanner:
    """Test SecretScanner class."""

    def test_scanner_initialization(self):
        """Test scanner initialization."""
        scanner = SecretScanner()
        assert len(scanner.patterns) > 0
        assert scanner.min_confidence == 0.0

    def test_scanner_with_custom_patterns(self):
        """Test scanner with custom patterns."""
        custom = [
            SecretPattern(
                name="custom",
                pattern=r"CUSTOM_[0-9]{8}",
                category=SecretCategory.OTHER,
                description="Custom pattern",
            )
        ]
        scanner = SecretScanner(patterns=custom)
        assert len(scanner.patterns) == 1

    def test_scanner_min_confidence(self):
        """Test minimum confidence filtering."""
        patterns = [
            SecretPattern(
                name="low_conf",
                pattern=r"LOW_[0-9]+",
                category=SecretCategory.OTHER,
                description="Low confidence",
                confidence=0.5,
            ),
            SecretPattern(
                name="high_conf",
                pattern=r"HIGH_[0-9]+",
                category=SecretCategory.OTHER,
                description="High confidence",
                confidence=0.9,
            ),
        ]
        scanner = SecretScanner(patterns=patterns, min_confidence=0.7)

        result = scanner.scan("LOW_123 and HIGH_456")
        # Only high confidence pattern should match
        assert result.total_secrets_found == 1
        assert result.secrets[0].pattern_name == "high_conf"


class TestSecretDetection:
    """Test detection of various secret types."""

    @pytest.fixture
    def scanner(self):
        """Create a scanner with default patterns."""
        return SecretScanner()

    # AWS Keys
    def test_detect_aws_access_key(self, scanner):
        """Test AWS access key detection."""
        source = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("aws" in s.pattern_name.lower() for s in result.secrets)

    def test_detect_aws_secret_key(self, scanner):
        """Test AWS secret key detection."""
        source = 'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
        result = scanner.scan(source)
        assert result.has_secrets

    # GCP Keys
    def test_detect_gcp_api_key(self, scanner):
        """Test GCP API key detection."""
        source = 'gcp_key = "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("gcp" in s.pattern_name.lower() for s in result.secrets)

    # Stripe Keys
    def test_detect_stripe_secret_key_live(self, scanner):
        """Test Stripe live secret key detection."""
        source = 'stripe_key = "sk_live_51H7XXXX1234567890abcdefg"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("stripe" in s.pattern_name.lower() for s in result.secrets)

    def test_detect_stripe_secret_key_test(self, scanner):
        """Test Stripe test secret key detection."""
        source = 'stripe_key = "sk_test_51H7XXXX1234567890abcdefg"'
        result = scanner.scan(source)
        assert result.has_secrets

    # GitHub Tokens
    def test_detect_github_pat(self, scanner):
        """Test GitHub Personal Access Token detection."""
        source = 'token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("github" in s.pattern_name.lower() for s in result.secrets)

    def test_detect_github_oauth(self, scanner):
        """Test GitHub OAuth token detection."""
        source = 'token = "gho_1234567890abcdefghijklmnopqrstuvwxyz"'
        result = scanner.scan(source)
        assert result.has_secrets

    # Slack Tokens
    def test_detect_slack_token(self, scanner):
        """Test Slack token detection."""
        source = 'slack_token = "xoxb-1234567890123-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("slack" in s.pattern_name.lower() for s in result.secrets)

    # Private Keys
    def test_detect_rsa_private_key(self, scanner):
        """Test RSA private key header detection."""
        source = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA04...
-----END RSA PRIVATE KEY-----"""
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("rsa" in s.pattern_name.lower() for s in result.secrets)

    def test_detect_openssh_private_key(self, scanner):
        """Test OpenSSH private key detection."""
        source = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAA...
-----END OPENSSH PRIVATE KEY-----"""
        result = scanner.scan(source)
        assert result.has_secrets

    def test_detect_ec_private_key(self, scanner):
        """Test EC private key detection."""
        source = "-----BEGIN EC PRIVATE KEY-----"
        result = scanner.scan(source)
        assert result.has_secrets

    # JWT Tokens
    def test_detect_jwt_token(self, scanner):
        """Test JWT token detection."""
        # Real JWT format with proper signature length
        source = 'token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("jwt" in s.pattern_name.lower() for s in result.secrets)

    # Database Connection Strings
    def test_detect_postgres_connection(self, scanner):
        """Test PostgreSQL connection string detection."""
        source = 'db_url = "postgresql://user:password123@localhost:5432/mydb"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("postgres" in s.pattern_name.lower() for s in result.secrets)

    def test_detect_mysql_connection(self, scanner):
        """Test MySQL connection string detection."""
        source = 'db_url = "mysql://root:secret@127.0.0.1/database"'
        result = scanner.scan(source)
        assert result.has_secrets

    def test_detect_mongodb_connection(self, scanner):
        """Test MongoDB connection string detection."""
        source = 'mongo_uri = "mongodb://admin:password@cluster0.mongodb.net/db"'
        result = scanner.scan(source)
        assert result.has_secrets

    def test_detect_mongodb_srv_connection(self, scanner):
        """Test MongoDB SRV connection string detection."""
        source = 'mongo_uri = "mongodb+srv://admin:password@cluster0.mongodb.net/db"'
        result = scanner.scan(source)
        assert result.has_secrets

    # SendGrid
    def test_detect_sendgrid_api_key(self, scanner):
        """Test SendGrid API key detection."""
        # SendGrid API key: SG.<22 chars>.<43 chars>
        source = 'key = "SG.abcdefghij_klmnopqrstu.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopq"'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("sendgrid" in s.pattern_name.lower() for s in result.secrets)

    # Azure
    def test_detect_azure_connection_string(self, scanner):
        """Test Azure storage connection string detection."""
        source = 'conn = "DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=abc123=="'
        result = scanner.scan(source)
        assert result.has_secrets
        assert any("azure" in s.pattern_name.lower() for s in result.secrets)


class TestSecretRedaction:
    """Test secret redaction functionality."""

    @pytest.fixture
    def scanner(self):
        """Create a scanner with default patterns."""
        return SecretScanner()

    def test_redact_single_secret(self, scanner):
        """Test redacting a single secret."""
        source = 'api_key = "AKIAIOSFODNN7EXAMPLE"'
        result = scanner.scan(source, redact=True)

        assert result.has_secrets
        assert "AKIAIOSFODNN7EXAMPLE" not in result.redacted_source
        assert ":: REDACTED:" in result.redacted_source

    def test_redact_multiple_secrets(self, scanner):
        """Test redacting multiple secrets."""
        source = """
config = {
    "aws_key": "AKIAIOSFODNN7EXAMPLE",
    "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
}
"""
        result = scanner.scan(source, redact=True)

        assert result.total_secrets_found >= 2
        assert "AKIAIOSFODNN7EXAMPLE" not in result.redacted_source
        assert "ghp_" not in result.redacted_source

    def test_redact_preserves_line_structure(self, scanner):
        """Test that redaction preserves line count."""
        source = """line1
line2 with AKIAIOSFODNN7EXAMPLE secret
line3"""
        result = scanner.scan(source, redact=True)

        original_lines = source.count("\n")
        redacted_lines = result.redacted_source.count("\n")
        assert original_lines == redacted_lines

    def test_no_redact_mode(self, scanner):
        """Test scanning without redaction."""
        source = 'key = "AKIAIOSFODNN7EXAMPLE"'
        result = scanner.scan(source, redact=False)

        assert result.has_secrets
        # Source should be unchanged
        assert result.redacted_source == source

    def test_redacted_secret_metadata(self, scanner):
        """Test that RedactedSecret contains correct metadata."""
        source = 'line1\nkey = "AKIAIOSFODNN7EXAMPLE"\nline3'
        result = scanner.scan(source, redact=True)

        assert len(result.secrets) >= 1
        secret = result.secrets[0]
        assert secret.line_number == 2
        assert secret.category == SecretCategory.API_KEY
        assert secret.original_length > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def scanner(self):
        """Create a scanner with default patterns."""
        return SecretScanner()

    def test_empty_source(self, scanner):
        """Test scanning empty source."""
        result = scanner.scan("")
        assert not result.has_secrets
        assert result.redacted_source == ""

    def test_no_secrets(self, scanner):
        """Test source with no secrets."""
        source = """
def hello():
    print("Hello, World!")
    return 42
"""
        result = scanner.scan(source)
        assert not result.has_secrets
        assert result.redacted_source == source

    def test_overlapping_patterns(self, scanner):
        """Test handling of overlapping pattern matches."""
        # Create patterns that might overlap
        patterns = [
            SecretPattern(
                name="short",
                pattern=r"SECRET",
                category=SecretCategory.OTHER,
                description="Short",
            ),
            SecretPattern(
                name="long",
                pattern=r"SECRET_[A-Z]+",
                category=SecretCategory.OTHER,
                description="Long",
            ),
        ]
        scanner = SecretScanner(patterns=patterns)
        source = "SECRET_VALUE here"
        result = scanner.scan(source)

        # Should handle overlaps gracefully (keep longer match)
        assert result.total_secrets_found >= 1

    def test_unicode_in_source(self, scanner):
        """Test handling of unicode characters."""
        source = """
# 日本語コメント
key = "AKIAIOSFODNN7EXAMPLE"
# Émojis: 🔑 🔒
"""
        result = scanner.scan(source)
        assert result.has_secrets

    def test_multiline_key(self, scanner):
        """Test detection of multiline private keys."""
        source = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA04...
...more key data...
-----END RSA PRIVATE KEY-----"""
        result = scanner.scan(source)
        assert result.has_secrets

    def test_key_in_comment(self, scanner):
        """Test detection of keys in comments (should still detect)."""
        source = '# Old key: AKIAIOSFODNN7EXAMPLE'
        result = scanner.scan(source)
        assert result.has_secrets

    def test_base64_like_strings(self, scanner):
        """Test that normal base64 strings aren't false positives."""
        source = """
# Normal base64 that shouldn't trigger
data = "SGVsbG8gV29ybGQh"  # "Hello World!" in base64
"""
        result = scanner.scan(source)
        # This should not match API key patterns
        assert not any(
            s.category == SecretCategory.API_KEY
            for s in result.secrets
        )


class TestConvenienceFunction:
    """Test the redact_secrets convenience function."""

    def test_redact_secrets_basic(self):
        """Test basic usage of redact_secrets function."""
        source = 'key = "AKIAIOSFODNN7EXAMPLE"'
        redacted, secrets = redact_secrets(source)

        assert len(secrets) >= 1
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted

    def test_redact_secrets_with_custom_patterns(self):
        """Test redact_secrets with custom patterns."""
        custom = [
            SecretPattern(
                name="custom",
                pattern=r"MYPREFIX_[A-Z0-9]{10}",
                category=SecretCategory.OTHER,
                description="Custom",
            )
        ]
        source = 'key = "MYPREFIX_ABCD123456"'
        redacted, secrets = redact_secrets(source, patterns=custom)

        assert len(secrets) == 1
        assert secrets[0].pattern_name == "custom"

    def test_redact_secrets_with_min_confidence(self):
        """Test redact_secrets with minimum confidence threshold."""
        # This should filter out low-confidence patterns
        source = 'password = "mysecretpassword"'
        redacted, secrets = redact_secrets(source, min_confidence=0.8)

        # Password patterns have lower confidence, may be filtered
        # The exact behavior depends on pattern confidence values


class TestDefaultPatterns:
    """Test the DEFAULT_PATTERNS list."""

    def test_default_patterns_not_empty(self):
        """Test that default patterns list is not empty."""
        assert len(DEFAULT_PATTERNS) > 0

    def test_default_patterns_have_required_fields(self):
        """Test that all default patterns have required fields."""
        for pattern in DEFAULT_PATTERNS:
            assert pattern.name
            assert pattern.pattern
            assert isinstance(pattern.category, SecretCategory)
            assert pattern.description
            assert 0.0 <= pattern.confidence <= 1.0

    def test_default_patterns_compile(self):
        """Test that all default patterns compile without error."""
        for pattern in DEFAULT_PATTERNS:
            try:
                compiled = pattern.compile()
                assert compiled is not None
            except Exception as e:
                pytest.fail(f"Pattern '{pattern.name}' failed to compile: {e}")

    def test_default_patterns_categories(self):
        """Test that patterns cover expected categories."""
        categories = {p.category for p in DEFAULT_PATTERNS}

        expected = {
            SecretCategory.API_KEY,
            SecretCategory.PRIVATE_KEY,
            SecretCategory.PASSWORD,
            SecretCategory.TOKEN,
            SecretCategory.CONNECTION_STRING,
        }

        for cat in expected:
            assert cat in categories, f"Missing category: {cat}"


class TestScanResult:
    """Test ScanResult dataclass."""

    def test_has_secrets_true(self):
        """Test has_secrets property when secrets exist."""
        result = ScanResult(
            source="test",
            redacted_source="test",
            secrets=[
                RedactedSecret(
                    pattern_name="test",
                    category=SecretCategory.API_KEY,
                    line_number=1,
                    start_pos=0,
                    end_pos=10,
                    original_length=10,
                    replacement=":: REDACTED:test",
                )
            ],
            total_secrets_found=1,
        )
        assert result.has_secrets

    def test_has_secrets_false(self):
        """Test has_secrets property when no secrets."""
        result = ScanResult(
            source="test",
            redacted_source="test",
            secrets=[],
            total_secrets_found=0,
        )
        assert not result.has_secrets
