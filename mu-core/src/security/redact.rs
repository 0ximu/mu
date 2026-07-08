//! Secret redaction functionality.

use super::patterns::find_secrets;
use crate::types::RedactedSecret;

/// Redact secrets from source code.
///
/// Returns the redacted source with secrets replaced.
pub fn redact(source: &str) -> String {
    let (redacted, _) = redact_secrets(source);
    redacted
}

/// Redact secrets from source code.
///
/// Returns the redacted source and a list of detected secrets.
pub fn redact_secrets(source: &str) -> (String, Vec<RedactedSecret>) {
    let mut redacted = source.to_string();
    let mut secrets = Vec::new();

    // Find all secrets
    let matches = find_secrets(source);

    // Different patterns can produce overlapping ranges (e.g. a generic
    // secret spanning a postgres URI). Replacing one shifts the other's
    // offsets and replace_range then panics. Keep only non-overlapping
    // matches: earliest start wins, longest on ties.
    let mut sorted_matches: Vec<_> = matches.into_iter().collect();
    sorted_matches.sort_by(|a, b| a.1.cmp(&b.1).then(b.2.cmp(&a.2)));

    let mut kept: Vec<(&str, usize, usize)> = Vec::new();
    let mut last_end = 0usize;
    for m in sorted_matches {
        if m.1 >= last_end {
            last_end = m.2;
            kept.push(m);
        }
    }

    // Replace back-to-front so earlier offsets stay valid
    for (pattern_name, start, end) in kept.iter().rev() {
        let replacement = format!(":: REDACTED:{}", pattern_name);
        redacted.replace_range(*start..*end, &replacement);
    }

    for (pattern_name, start, end) in kept {
        // Calculate line and column
        let (line_number, start_col, end_col) = position_to_line_col_full(source, start, end);

        secrets.push(RedactedSecret {
            pattern_name: pattern_name.to_string(),
            line_number,
            start_col,
            end_col,
        });
    }

    (redacted, secrets)
}

/// Convert byte position to line number and column.
pub fn position_to_line_col(source: &str, position: usize) -> (u32, u32) {
    let mut line = 1u32;
    let mut col = 1u32;

    for (i, c) in source.char_indices() {
        if i >= position {
            break;
        }
        if c == '\n' {
            line += 1;
            col = 1;
        } else {
            col += 1;
        }
    }

    (line, col)
}

/// Convert byte position to line number and column (with end position).
fn position_to_line_col_full(source: &str, start: usize, end: usize) -> (u32, u32, u32) {
    let mut line = 1u32;
    let mut col = 1u32;
    let mut start_col = 1u32;

    for (i, c) in source.char_indices() {
        if i == start {
            start_col = col;
        }
        if i >= end {
            break;
        }
        if c == '\n' {
            line += 1;
            col = 1;
        } else {
            col += 1;
        }
    }

    (line, start_col, col)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_redact_aws_key() {
        let source = "key = AKIAIOSFODNN7EXAMPLE";
        let (redacted, secrets) = redact_secrets(source);
        assert!(redacted.contains("REDACTED:aws_access_key_id"));
        assert_eq!(secrets.len(), 1);
    }

    #[test]
    fn test_overlapping_matches_do_not_panic() {
        // GENERIC_SECRET spans the whole assignment while POSTGRES_URI matches
        // the URI inside it; overlapping ranges used to go stale after the
        // inner replacement and panic in replace_range.
        let source = "password=postgres://admin:hunter2@db.example.com/prod";
        let (redacted, secrets) = redact_secrets(source);
        assert!(redacted.contains("REDACTED:"));
        assert!(!redacted.contains("hunter2"));
        assert!(!secrets.is_empty());
    }

    #[test]
    fn test_no_secrets() {
        let source = "def hello(): pass";
        let (redacted, secrets) = redact_secrets(source);
        assert_eq!(redacted, source);
        assert!(secrets.is_empty());
    }

    #[test]
    fn test_position_to_line_col() {
        let source = "line1\nline2\nline3";
        // "line2" starts at position 6
        let (line, col) = position_to_line_col(source, 6);
        assert_eq!(line, 2);
        assert_eq!(col, 1);
    }
}
