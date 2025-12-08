//! HTTP server for MU daemon.
//!
//! Provides REST API for:
//! - Status and health checks
//! - MUQL query execution
//! - Graph operations (deps, impact, cycles)
//! - Build and scan triggers

mod http;
pub mod mcp;
pub mod projects;
pub mod state;
mod websocket;

pub use http::create_router;
pub use projects::ProjectManager;
pub use state::{AppState, GraphEvent};
