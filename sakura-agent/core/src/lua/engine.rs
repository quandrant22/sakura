//! Lua engine for scripted commands

use std::sync::Arc;
use tokio::sync::mpsc;
use log::{info, error};

use crate::protocol::Event;
use crate::commands::CommandDef;

/// Lua engine state
pub struct LuaEngine {
    commands: Arc<Vec<CommandDef>>,
}

impl LuaEngine {
    /// Create a new Lua engine
    pub fn new(commands: Arc<Vec<CommandDef>>) -> Self {
        Self { commands }
    }

    /// Execute a Lua script
    pub fn execute(&self, script: &str) -> Result<String, String> {
        // Placeholder — mlua integration goes here
        info!("Lua execution: {} bytes", script.len());
        Ok("ok".to_string())
    }
}

/// Run the Lua engine
pub async fn run(
    commands: Arc<Vec<CommandDef>>,
    _event_tx: mpsc::Sender<Event>,
    _action_tx: mpsc::Sender<crate::protocol::Action>,
) {
    info!("Lua engine started");

    let _engine = LuaEngine::new(commands);

    // Keep alive
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}
