//! Sakura Agent v2 — Core
//!
//! High-performance audio processing pipeline.
//! Architecture: Rust core (audio + NLU) ↔ Python executor (Windows APIs)

mod audio;
mod stt;
mod nlu;
mod commands;
mod lua;
mod protocol;
mod ipc;

use std::sync::Arc;
use tokio::sync::mpsc;
use log::info;

#[tokio::main]
async fn main() {
    env_logger::init();

    info!("╔══════════════════════════════════════╗");
    info!("║     Sakura Agent v2.0.0              ║");
    info!("║     High-performance audio core      ║");
    info!("╚══════════════════════════════════════╝");

    // Load configuration
    let config = load_config().unwrap_or_else(|e| {
        log::warn!("Config load failed, using defaults: {}", e);
        Config::default()
    });

    // Load command definitions
    let commands = Arc::new(commands::load_all("commands/").unwrap_or_default());
    info!("Loaded {} commands", commands.len());

    // Create channels
    let (event_tx, _event_rx) = mpsc::channel::<protocol::Event>(64);
    let (action_tx, action_rx) = mpsc::channel::<protocol::Action>(64);

    // Start components
    let config = Arc::new(config);

    // IPC handler (communicates with Python executor)
    let ipc_handle = tokio::spawn(ipc::run(action_rx, event_tx.clone()));

    // Audio pipeline — run in std::thread to avoid blocking tokio
    let config_clone = config.clone();
    let commands_clone = commands.clone();
    let event_tx_clone = event_tx.clone();
    let action_tx_clone = action_tx.clone();
    let audio_handle = std::thread::Builder::new()
        .name("audio-pipeline".to_string())
        .spawn(move || {
            let rt = tokio::runtime::Runtime::new().unwrap();
            rt.block_on(audio::pipeline::run(
                config_clone,
                commands_clone,
                event_tx_clone,
                action_tx_clone,
            ));
        });

    // Lua engine (for scripted commands)
    let lua_handle = tokio::spawn(lua::engine::run(
        commands.clone(),
        event_tx.clone(),
        action_tx.clone(),
    ));

    info!("All components started");

    // Wait for shutdown
    tokio::select! {
        _ = ipc_handle => info!("IPC stopped"),
        _ = lua_handle => info!("Lua engine stopped"),
    }

    // Wait for audio thread
    if let Ok(handle) = audio_handle {
        let _ = handle.join();
    }

    info!("Sakura Agent v2 shutting down");
}

/// Load configuration from TOML file
fn load_config() -> Result<Config, Box<dyn std::error::Error>> {
    // Try multiple config locations
    let config_paths = vec![
        // Current directory
        std::path::PathBuf::from("config/default.toml"),
        // Parent directory
        std::path::PathBuf::from("../config/default.toml"),
        // AppData\Roaming
        dirs::config_dir().unwrap_or_default().join("sakura").join("config.toml"),
        // AppData\Local
        dirs::data_local_dir().unwrap_or_default().join("sakura").join("config.toml"),
    ];

    for path in &config_paths {
        if path.exists() {
            info!("Loading config from: {:?}", path);
            let content = std::fs::read_to_string(path)?;
            let config: Config = toml::from_str(&content)?;
            return Ok(config);
        }
    }

    info!("No config file found, using defaults");
    Ok(Config::default())
}

/// Agent configuration
#[derive(Debug, Clone, serde::Deserialize)]
pub struct Config {
    #[serde(default = "default_device_id")]
    pub device_id: String,

    #[serde(default = "default_vps_url")]
    pub vps_url: String,

    #[serde(default)]
    pub ws_token: String,

    #[serde(default = "default_sample_rate")]
    pub sample_rate: usize,

    #[serde(default = "default_frame_size")]
    pub frame_size: usize,

    #[serde(default = "default_pre_roll_sec")]
    pub pre_roll_seconds: f32,

    #[serde(default = "default_silence_sec")]
    pub silence_threshold_sec: f32,

    #[serde(default)]
    pub wake_words: Vec<String>,

    #[serde(default = "default_vosk_model")]
    pub wake_model: String,

    #[serde(default = "default_stt_model")]
    pub command_model: String,

    #[serde(default)]
    pub chain: ChainConfig,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct ChainConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,

    #[serde(default = "default_chain_timeout")]
    pub timeout_sec: f32,
}

impl Default for ChainConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            timeout_sec: default_chain_timeout(),
        }
    }
}

fn default_true() -> bool { true }
fn default_chain_timeout() -> f32 { 4.0 }

fn default_device_id() -> String { "pc".to_string() }
fn default_vps_url() -> String { "ws://localhost:8765".to_string() }
fn default_sample_rate() -> usize { 16000 }
fn default_frame_size() -> usize { 512 }
fn default_pre_roll_sec() -> f32 { 5.0 }
fn default_silence_sec() -> f32 { 0.3 }
fn default_vosk_model() -> String { "C:/Sakura/vosk-model-small-ru-0.22".to_string() }
fn default_stt_model() -> String { "C:/Sakura/vosk-model-ru-0.42".to_string() }

impl Default for Config {
    fn default() -> Self {
        Self {
            device_id: default_device_id(),
            vps_url: default_vps_url(),
            ws_token: String::new(),
            sample_rate: default_sample_rate(),
            frame_size: default_frame_size(),
            pre_roll_seconds: default_pre_roll_sec(),
            silence_threshold_sec: default_silence_sec(),
            wake_words: vec![
                "сакура".to_string(),
                "сакуру".to_string(),
                "сакуре".to_string(),
                "сакурой".to_string(),
                "sakura".to_string(),
            ],
            wake_model: default_vosk_model(),
            command_model: default_stt_model(),
            chain: ChainConfig {
                enabled: true,
                timeout_sec: default_chain_timeout(),
            },
        }
    }
}
