//! Vibe Commands - Fun aliases with personality-driven output
//!
//! These commands provide friendly, colorful interfaces to MU functionality:
//!
//! - `yolo` - Impact analysis (what breaks if you change something?)
//! - `sus` - Risk assessment / warnings before touching code
//! - `wtf` - Git archaeology (why does this code exist?)
//! - `omg` - OMEGA compressed context (S-expression format)
//! - `vibe` - Pattern conformance checking
//! - `zen` - Cache cleanup and reset
//!
//! Each command outputs helpful information with colorful, personality-driven
//! messages that make code analysis more engaging and fun.

pub mod conventions;
pub mod omg;
pub mod sus;
pub mod vibe;
pub mod wtf;
pub mod yolo;
pub mod zen;
