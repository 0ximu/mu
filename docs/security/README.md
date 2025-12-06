# Security Documentation

This directory contains security-related documentation for the MU project.

## Contents

| Document | Description |
|----------|-------------|
| [SECURITY.md](SECURITY.md) | Security policy and vulnerability reporting |
| [threat-model.md](threat-model.md) | Threat modeling and risk assessment |

## Security Principles

MU follows these security principles:

### 1. Privacy First
- No code leaves your machine without explicit consent
- Local-only mode available (`--local` flag)
- Secret detection and redaction by default

### 2. Defense in Depth
- Multiple layers of secret detection
- Input validation at all boundaries
- Secure defaults

### 3. Least Privilege
- Minimal filesystem access
- No network calls unless LLM mode enabled
- Read-only operations by default

## Reporting Vulnerabilities

See [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.

## Security Features

### Secret Detection

MU automatically detects and redacts:
- API keys and tokens
- Passwords and credentials
- Private keys (RSA, SSH, PGP)
- Connection strings
- AWS/GCP/Azure credentials

### Local Mode

Use `--local` flag to ensure no data leaves your machine:
```bash
mu compress ./src --llm --local
```

This uses Ollama for LLM summarization without external API calls.

## Security Checklist for Contributors

When contributing to MU:

- [ ] No hardcoded secrets in code or tests
- [ ] New secret patterns added to `SecretScanner` if discovered
- [ ] Input validation for file paths and user input
- [ ] No `eval()` or `exec()` on user-controlled data
- [ ] Subprocess calls use `shell=False`
- [ ] Encoding errors handled gracefully
