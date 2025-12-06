# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

1. **DO NOT** create a public GitHub issue for security vulnerabilities
2. Email security concerns to: [security contact - to be configured]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Resolution Timeline**: Depends on severity
  - Critical: 24-72 hours
  - High: 1-2 weeks
  - Medium: 2-4 weeks
  - Low: Next release cycle

### Disclosure Policy

- We follow coordinated disclosure
- Security fixes are released before public disclosure
- Credit given to reporters (unless anonymity requested)

## Security Measures

### Code Security

- All PRs require security review for sensitive changes
- Automated secret scanning in CI
- Dependency vulnerability scanning
- Static analysis with security-focused rules

### Data Security

- No telemetry or data collection
- Secret redaction enabled by default
- Local-only mode available
- No persistent storage of processed code

### LLM Integration Security

When using `--llm` flag:
- Secrets are redacted before sending to LLM
- Use `--local` for fully offline processing
- API keys stored in environment variables only
- No caching of LLM responses containing code

## Known Security Considerations

### File System Access

MU reads files from the filesystem. Ensure:
- Run MU only on trusted codebases
- Be cautious with symlinks (may traverse outside intended directory)
- Large files are truncated to prevent memory exhaustion

### LLM Data Transmission

When `--llm` is used without `--local`:
- Compressed code representations are sent to LLM providers
- Use `--no-redact` only if you understand the implications
- Review provider privacy policies

## Security Updates

Security updates are:
- Released as patch versions (x.x.PATCH)
- Announced in release notes
- Documented in CHANGELOG with [SECURITY] tag
