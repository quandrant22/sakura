//! Sakura Audio Core
//!
//! High-performance audio processing pipeline for the Sakura agent.
//! Handles: microphone capture, VAD, wake word detection, STT, command matching.
//!
//! Architecture (inspired by Jarvis):
//! - Audio capture → Ring buffer (5s pre-roll)
//! - VAD detects voice start → flush buffer
//! - Wake word detection → start STT
//! - Streaming STT → command matching → IPC to Python executor

mod audio;
mod vad;
mod stt;
mod commands;
mod protocol;
mod ipc;

use std::sync::Arc;
use tokio::sync::mpsc;
use log::info;

#[tokio::main]
async fn main() {
    // Initialize logger
    env_logger::init();

    info!("Sakura Audio Core v{}", env!("CARGO_PKG_VERSION"));

    // Load command definitions
    let commands = match commands::load_commands("commands/") {
        Ok(cmds) => {
            info!("Loaded {} commands", cmds.len());
            Arc::new(cmds)
        }
        Err(e) => {
            log::error!("Failed to load commands: {}", e);
            Arc::new(Vec::new())
        }
    };

    // Create channels
    let (event_tx, _event_rx) = mpsc::channel::<protocol::Event>(32);
    let (action_tx, action_rx) = mpsc::channel::<protocol::Action>(32);

    // Start IPC handler (communicates with Python executor)
    let ipc_handle = tokio::spawn(ipc::run(action_rx, event_tx.clone()));

    // Start audio pipeline
    let audio_handle = tokio::spawn(audio::run_pipeline(
        commands,
        event_tx.clone(),
        action_tx.clone(),
    ));

    // Wait for shutdown
    tokio::select! {
        _ = ipc_handle => info!("IPC handler stopped"),
        _ = audio_handle => info!("Audio pipeline stopped"),
    }
}
