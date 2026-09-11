//! IPC Protocol definitions
//!
//! Typed events and actions for agent ↔ VPS communication.

use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

/// Events sent from agent to VPS
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    /// Agent registered with VPS
    Registered {
        device_id: String,
        timestamp: f64,
        active_window: String,
        system_info: serde_json::Value,
        capabilities: Vec<String>,
        version: String,
    },

    /// Heartbeat ping
    Ping {
        device_id: String,
        timestamp: f64,
        active_window: String,
        system_info: serde_json::Value,
    },

    /// Wake word detected
    WakeWordDetected {
        device_id: String,
        timestamp: f64,
    },

    /// Actively listening for command
    Listening {
        device_id: String,
        timestamp: f64,
    },

    /// Speech recognized
    SpeechRecognized {
        device_id: String,
        timestamp: f64,
        text: String,
    },

    /// Command was executed
    CommandExecuted {
        device_id: String,
        timestamp: f64,
        id: String,
        success: bool,
    },

    /// Returned to idle state
    Idle {
        device_id: String,
        timestamp: f64,
    },

    /// Error occurred
    Error {
        device_id: String,
        timestamp: f64,
        message: String,
    },

    /// Scanned applications list
    AppsList {
        device_id: String,
        timestamp: f64,
        apps: serde_json::Value,
    },

    /// Command result
    CommandResult {
        device_id: String,
        timestamp: f64,
        action: String,
        result: String,
        success: bool,
        screenshot: String,
    },
}

/// Actions sent from VPS to agent
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Action {
    /// Execute a command
    Command {
        target: String,
        args: String,
        request_id: String,
    },

    /// Text-to-speech audio chunk
    TtsChunk {
        audio: String, // base64 encoded PCM
    },

    /// End of TTS stream
    TtsEnd,

    /// Text reply from Sakura
    Reply {
        text: String,
        mood: serde_json::Value,
    },

    /// Mood update
    MoodUpdate {
        params: serde_json::Value,
    },

    /// State update request
    StateUpdate {
        state: String,
    },
}

impl Event {
    /// Convert to JSON string
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_default()
    }

    /// Get current timestamp
    pub fn timestamp() -> f64 {
        Utc::now().timestamp() as f64
    }
}

impl Action {
    /// Parse from JSON string
    pub fn from_json(json: &str) -> Option<Self> {
        serde_json::from_str(json).ok()
    }

    /// Convert to JSON string
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_default()
    }
}

/// Capabilities this agent supports
pub struct Capabilities;

impl Capabilities {
    pub const VOICE: &'static str = "voice";
    pub const TTS: &'static str = "tts";
    pub const SCREENSHOT: &'static str = "screenshot";
    pub const APPS: &'static str = "apps";
    pub const BROWSER: &'static str = "browser";
    pub const MUSIC: &'static str = "music";
    pub const KETTLE: &'static str = "kettle";
    pub const DICTATE: &'static str = "dictate";
    pub const SYSTEM: &'static str = "system";

    /// Auto-detect available capabilities
    pub fn detect() -> Vec<String> {
        let mut caps = Vec::new();

        // Audio capabilities are always available in Rust core
        caps.push(Self::VOICE.to_string());
        caps.push(Self::TTS.to_string());

        // Platform-specific capabilities
        if cfg!(target_os = "windows") {
            caps.extend([
                Self::APPS.to_string(),
                Self::BROWSER.to_string(),
                Self::MUSIC.to_string(),
                Self::DICTATE.to_string(),
                Self::SYSTEM.to_string(),
            ]);
        }

        caps
    }
}
