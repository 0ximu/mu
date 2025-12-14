# Security Module - Secret Detection & Redaction

The security module scans source code for secrets and redacts them before processing, preventing accidental exposure in MU output.

## Architecture

```
Source Code -> SecretScanner -> Pattern Matching -> Redaction
                    |                 |
              SecretPattern[]    RedactedSecret[]
```

### Core Components

| Class | Purpose |
|-------|---------|
| `SecretScanner` | Main scanner with pattern matching and redaction |
| `SecretPattern` | Pattern definition (regex + metadata) |
| `RedactedSecret` | Info about a redacted secret |
| `ScanResult` | Scan results with original and redacted source |

## Secret Categories

```python
class SecretCategory(Enum):
    API_KEY = "api_key"
    PRIVATE_KEY = "private_key"
    PASSWORD = "password"
    TOKEN = "token"
    CONNECTION_STRING = "connection_string"
    CERTIFICATE = "certificate"
    OTHER = "other"
```

## Built-in Patterns

The module includes patterns for:

| Provider | Patterns |
|----------|----------|
| AWS | Access Key ID, Secret Access Key |
| GCP | API Key, Service Account JSON |
| Azure | Storage Key, Connection String |
| Stripe | Live/Test Secret Keys |
| GitHub | PAT, OAuth, App Tokens |
| GitLab | Personal Access Token |
| Slack | Bot Tokens, Webhooks |
| OpenAI | API Keys (legacy + project) |
| Anthropic | API Keys |
| Database | PostgreSQL, MySQL, MongoDB, Redis connection strings |
| Generic | JWT tokens, Private keys (RSA, EC, PGP), Password assignments |

## Usage

### Basic Scanning

```python
from mu.security import SecretScanner, redact_secrets

scanner = SecretScanner()
result = scanner.scan(source_code)

if result.has_secrets:
    print(f"Found {result.total_secrets_found} secrets")
    for secret in result.secrets:
        print(f"  {secret.pattern_name} at line {secret.line_number}")

# Use redacted source for further processing
safe_source = result.redacted_source
```

### Convenience Function

```python
redacted, secrets = redact_secrets(source_code)
```

### File Scanning

```python
result = scanner.scan_file("/path/to/file.py")
```

## Redaction Format

Secrets are replaced with informative markers:

```python
# Before
api_key = "sk-proj-abc123xyz..."

# After
api_key = ":: REDACTED:openai_api_key"
```

The marker format `:: REDACTED:{pattern_name}` allows:
- LLMs to understand a secret was present
- Pattern identification for debugging
- Easy grep for redacted content

## Pattern Structure

```python
@dataclass
class SecretPattern:
    name: str           # Unique identifier
    pattern: str        # Regex pattern
    category: SecretCategory
    description: str    # Human-readable description
    confidence: float   # 0.0-1.0, likelihood of being real secret
```

### Confidence Levels

- **1.0**: Definite secret (AWS access key format)
- **0.85**: Very likely (JWT tokens)
- **0.7**: Probable (generic password assignments)
- **0.6**: Possible (high-entropy hex strings)

## Adding Custom Patterns

### In Code

```python
from mu.security import SecretPattern, SecretCategory, SecretScanner

custom_patterns = [
    SecretPattern(
        name="my_internal_token",
        pattern=r"MYAPP_[A-Z0-9]{32}",
        category=SecretCategory.TOKEN,
        description="MyApp Internal Token",
        confidence=1.0,
    ),
]

scanner = SecretScanner(patterns=DEFAULT_PATTERNS + custom_patterns)
```

### Via TOML File

Create `secrets.toml`:
```toml
[[patterns]]
name = "my_internal_token"
pattern = "MYAPP_[A-Z0-9]{32}"
category = "token"
description = "MyApp Internal Token"
confidence = 1.0
```

Load with:
```python
from mu.security import load_custom_patterns

custom = load_custom_patterns("secrets.toml")
scanner = SecretScanner(patterns=DEFAULT_PATTERNS + custom)
```

## Confidence Filtering

Skip low-confidence patterns to reduce false positives:

```python
# Only high-confidence matches
scanner = SecretScanner(min_confidence=0.8)

# All patterns including generic
scanner = SecretScanner(min_confidence=0.0)
```

## Integration Points

### With Scanner Module

```python
# In scanner/manifest generation
from mu.security import redact_secrets

for file_path in discovered_files:
    content = file_path.read_text()
    redacted, _ = redact_secrets(content)
    # Use redacted content for parsing
```

### With LLM Module

```python
# Before sending to LLM
from mu.security import SecretScanner

scanner = SecretScanner(min_confidence=0.7)
result = scanner.scan(function_body)

if result.has_secrets:
    # Send redacted version
    llm_input = result.redacted_source
```

## Pattern Design Guidelines

1. **Specificity**: More specific patterns = fewer false positives
2. **Anchoring**: Use word boundaries where appropriate (`\b`)
3. **Case sensitivity**: Most patterns use `IGNORECASE` flag
4. **Length requirements**: Specify minimum lengths for random tokens
5. **Context**: Include surrounding context (e.g., `password=`)

### Good Pattern Examples

```python
# Specific format (low false positive)
pattern=r"ghp_[0-9a-zA-Z]{36}"  # GitHub PAT

# Context-aware (medium confidence)
pattern=r"(?i)password\s*[=:]\s*['\"][^'\"]{8,}['\"]"

# Format + context (high confidence)
pattern=r"sk-proj-[a-zA-Z0-9_-]{48,}"  # OpenAI project key
```

### Bad Pattern Examples

```python
# Too broad (many false positives)
pattern=r"[A-Za-z0-9]{32}"  # Any 32-char alphanumeric

# No minimum length
pattern=r"api_key=.+"  # Matches api_key=test
```

## Anti-Patterns

1. **Never** skip security scanning on user-provided code
2. **Never** log redacted secrets (even with pattern name)
3. **Never** use low confidence patterns without filtering
4. **Never** parse secrets for validation - just redact
5. **Never** assume encoding - handle binary patterns too

## Testing

```bash
pytest tests/unit/test_security.py -v
```

Key test scenarios:
- Each built-in pattern type
- Overlapping patterns (longer wins)
- Custom pattern loading
- Confidence filtering
- Line number tracking
- Multi-occurrence redaction
