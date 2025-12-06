# Threat Model

This document outlines the threat model for MU, identifying potential security risks and mitigations.

## System Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Source     │────▶│     MU      │────▶│   Output    │
│  Code       │     │  Pipeline   │     │   (.mu)     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼ (optional)
                    ┌─────────────┐
                    │  LLM API    │
                    │  Provider   │
                    └─────────────┘
```

## Assets

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| Source Code | High | User's proprietary codebase |
| Secrets | Critical | API keys, passwords, tokens in code |
| LLM API Keys | High | User's API credentials |
| MU Output | Medium | Compressed representation of code |

## Threat Actors

1. **Malicious Codebase**: Attacker-controlled code processed by MU
2. **Network Attacker**: Man-in-the-middle on LLM API calls
3. **Malicious Dependency**: Compromised npm/pip package
4. **Insider**: Developer with access to MU internals

## Threats and Mitigations

### T1: Secret Exposure via LLM

**Threat**: Secrets in code are sent to external LLM providers

**Risk**: High

**Mitigations**:
- ✅ `SecretScanner` detects and redacts secrets before LLM calls
- ✅ `--local` flag for fully offline processing
- ✅ `--no-redact` requires explicit opt-in
- ⚠️ Pattern-based detection may miss novel secret formats

### T2: Path Traversal

**Threat**: Malicious input causes MU to read files outside intended directory

**Risk**: Medium

**Mitigations**:
- ✅ Path validation in scanner
- ✅ Symlink handling with depth limits
- ⚠️ Consider adding strict chroot-like isolation

### T3: Denial of Service via Large Files

**Threat**: Processing extremely large files exhausts memory

**Risk**: Low

**Mitigations**:
- ✅ `max_file_size_kb` configuration limit
- ✅ Streaming processing for large codebases
- ✅ Truncation of oversized outputs

### T4: Code Injection via Malicious AST

**Threat**: Specially crafted code exploits parser vulnerabilities

**Risk**: Low

**Mitigations**:
- ✅ Tree-sitter is memory-safe (written in C with fuzzing)
- ✅ No `eval()` or `exec()` on parsed content
- ✅ Output is data, not executed code

### T5: Dependency Vulnerabilities

**Threat**: Vulnerabilities in third-party packages

**Risk**: Medium

**Mitigations**:
- ✅ Minimal dependencies
- ✅ Dependabot alerts enabled
- ⚠️ Add `pip-audit` to CI pipeline

### T6: LLM API Key Exposure

**Threat**: User's LLM API keys leaked

**Risk**: High

**Mitigations**:
- ✅ Keys read from environment variables only
- ✅ Keys never logged or cached
- ✅ Keys never included in MU output

### T7: Man-in-the-Middle on LLM Calls

**Threat**: Attacker intercepts code sent to LLM API

**Risk**: Medium

**Mitigations**:
- ✅ HTTPS enforced for all API calls
- ✅ Certificate validation enabled
- ⚠️ Consider certificate pinning for high-security environments

## Data Flow Security

### Input Validation

| Input | Validation |
|-------|------------|
| File paths | Normalized, checked for traversal |
| File content | Encoding detection, size limits |
| CLI arguments | Type validation via Click |
| Config files | Schema validation |

### Output Sanitization

| Output | Sanitization |
|--------|--------------|
| MU format | Secrets redacted |
| JSON export | Proper escaping |
| LLM prompts | Secrets redacted |
| Error messages | No sensitive paths |

## Security Testing

### Automated

- [ ] Secret detection test suite
- [ ] Path traversal test cases
- [ ] Large file handling tests
- [ ] Dependency vulnerability scanning

### Manual

- [ ] Annual security review
- [ ] Penetration testing for major releases
- [ ] Code audit for cryptographic operations

## Incident Response

1. **Detection**: User reports or automated monitoring
2. **Triage**: Assess severity and impact
3. **Containment**: Disable affected features if needed
4. **Fix**: Develop and test patch
5. **Release**: Push security update
6. **Disclosure**: Notify users, update documentation

## Future Considerations

- [ ] Sandboxed execution environment
- [ ] Content Security Policy for HTML exports
- [ ] Signed releases
- [ ] SBOM (Software Bill of Materials) generation
