//! Secret detection patterns.
//!
//! Patterns for detecting API keys, tokens, and other secrets.

use once_cell::sync::Lazy;
use regex::Regex;

/// A secret detection pattern.
pub struct SecretPattern {
    pub name: &'static str,
    pub regex: &'static Lazy<Regex>,
}

// Define patterns as separate statics
static AWS_ACCESS_KEY: Lazy<Regex> = Lazy::new(|| Regex::new(r"AKIA[0-9A-Z]{16}").unwrap());
static AWS_SECRET_KEY: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r#"(?i)(aws_secret_access_key|aws_secret_key)\s*[=:]\s*['"]?([A-Za-z0-9/+=]{40})['"]?"#,
    )
    .unwrap()
});
static GCP_API_KEY: Lazy<Regex> = Lazy::new(|| Regex::new(r"AIza[0-9A-Za-z\-_]{35}").unwrap());
static GITHUB_TOKEN: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"gh[pousr]_[A-Za-z0-9_]{36,}").unwrap());
static OPENAI_API_KEY: Lazy<Regex> = Lazy::new(|| Regex::new(r"sk-[A-Za-z0-9]{20,}").unwrap());
static OPENAI_PROJECT_KEY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"sk-proj-[A-Za-z0-9]{20,}").unwrap());
static STRIPE_LIVE_KEY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"sk_live_[A-Za-z0-9]{24,}").unwrap());
static STRIPE_TEST_KEY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"sk_test_[A-Za-z0-9]{24,}").unwrap());
static RSA_PRIVATE_KEY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"-----BEGIN RSA PRIVATE KEY-----").unwrap());
static PRIVATE_KEY: Lazy<Regex> = Lazy::new(|| Regex::new(r"-----BEGIN PRIVATE KEY-----").unwrap());
static OPENSSH_PRIVATE_KEY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"-----BEGIN OPENSSH PRIVATE KEY-----").unwrap());
static POSTGRES_URI: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"postgres(?:ql)?://[^:]+:[^@]+@[^\s]+").unwrap());
static MONGODB_URI: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"mongodb(?:\+srv)?://[^:]+:[^@]+@[^\s]+").unwrap());
static REDIS_URI: Lazy<Regex> = Lazy::new(|| Regex::new(r"redis://[^:]+:[^@]+@[^\s]+").unwrap());
static GENERIC_API_KEY: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?i)(api_key|apikey|api-key)\s*[=:]\s*['"]?([A-Za-z0-9_\-]{20,})['"]?"#).unwrap()
});
static GENERIC_SECRET: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?i)(secret|password|passwd|pwd)\s*[=:]\s*['"]?([^\s'"]{8,})['"]?"#).unwrap()
});
static BEARER_TOKEN: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?i)bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"#).unwrap()
});

/// Default secret patterns matching Python implementation.
pub static DEFAULT_PATTERNS: &[SecretPattern] = &[
    SecretPattern {
        name: "aws_access_key_id",
        regex: &AWS_ACCESS_KEY,
    },
    SecretPattern {
        name: "aws_secret_access_key",
        regex: &AWS_SECRET_KEY,
    },
    SecretPattern {
        name: "gcp_api_key",
        regex: &GCP_API_KEY,
    },
    SecretPattern {
        name: "github_token",
        regex: &GITHUB_TOKEN,
    },
    SecretPattern {
        name: "openai_api_key",
        regex: &OPENAI_API_KEY,
    },
    SecretPattern {
        name: "openai_project_key",
        regex: &OPENAI_PROJECT_KEY,
    },
    SecretPattern {
        name: "stripe_api_key",
        regex: &STRIPE_LIVE_KEY,
    },
    SecretPattern {
        name: "stripe_test_key",
        regex: &STRIPE_TEST_KEY,
    },
    SecretPattern {
        name: "rsa_private_key",
        regex: &RSA_PRIVATE_KEY,
    },
    SecretPattern {
        name: "private_key",
        regex: &PRIVATE_KEY,
    },
    SecretPattern {
        name: "openssh_private_key",
        regex: &OPENSSH_PRIVATE_KEY,
    },
    SecretPattern {
        name: "postgres_uri",
        regex: &POSTGRES_URI,
    },
    SecretPattern {
        name: "mongodb_uri",
        regex: &MONGODB_URI,
    },
    SecretPattern {
        name: "redis_uri",
        regex: &REDIS_URI,
    },
    SecretPattern {
        name: "generic_api_key",
        regex: &GENERIC_API_KEY,
    },
    SecretPattern {
        name: "generic_secret",
        regex: &GENERIC_SECRET,
    },
    SecretPattern {
        name: "bearer_token",
        regex: &BEARER_TOKEN,
    },
];

/// Check if text matches any secret pattern.
pub fn find_secrets(text: &str) -> Vec<(&'static str, usize, usize)> {
    let mut matches = Vec::new();

    for pattern in DEFAULT_PATTERNS {
        for m in pattern.regex.find_iter(text) {
            matches.push((pattern.name, m.start(), m.end()));
        }
    }

    matches
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_aws_access_key() {
        let text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE";
        let matches = find_secrets(text);
        assert!(!matches.is_empty());
    }

    #[test]
    fn test_github_token() {
        let text = "token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
        let matches = find_secrets(text);
        assert!(!matches.is_empty());
    }

    #[test]
    fn test_no_secrets() {
        let text = "def hello(): print('hello')";
        let matches = find_secrets(text);
        assert!(matches.is_empty());
    }
}
