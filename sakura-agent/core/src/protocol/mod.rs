//! IPC Protocol definitions

use serde::{Deserialize, Serialize};

/// Events sent from agent to VPS
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    Registered {
        device_id: String,
        timestamp: f64,
        active_window: String,
        capabilities: Vec<String>,
        version: String,
    },

    Ping {
        device_id: String,
        timestamp: f64,
    },

    Listening {
        device_id: String,
        timestamp: f64,
    },

    SpeechRecognized {
        device_id: String,
        timestamp: f64,
        text: String,
    },

    CommandExecuted {
        device_id: String,
        timestamp: f64,
        id: String,
        success: bool,
    },

    Idle {
        device_id: String,
        timestamp: f64,
    },

    Error {
        device_id: String,
        timestamp: f64,
        message: String,
    },

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
    Command {
        target: String,
        args: String,
    },

    TtsChunk {
        audio: String,
    },

    TtsEnd,

    Reply {
        text: String,
    },

    MoodUpdate {
        params: serde_json::Value,
    },
}

impl Event {
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_default()
    }

    pub fn timestamp() -> f64 {
        chrono::Utc::now().timestamp() as f64
    }
}

impl Action {
    pub fn from_json(json: &str) -> Option<Self> {
        serde_json::from_str(json).ok()
    }
}

/// Agent capabilities
pub struct Capabilities;

impl Capabilities {
    pub const VOICE: &'static str = "voice";
    pub const TTS: &'static str = "tts";
    pub const SCREENSHOT: &'static str = "screenshot";
    pub const APPS: &'static str = "apps";
    pub const BROWSER: &'static str = "browser";
    pub const MUSIC: &'static str = "music";
    pub const SYSTEM: &'static str = "system";

    pub fn detect() -> Vec<String> {
        let mut caps = vec![
            Self::VOICE.to_string(),
            Self::TTS.to_string(),
        ];

        if cfg!(target_os = "windows") {
            caps.extend([
                Self::APPS.to_string(),
                Self::BROWSER.to_string(),
                Self::MUSIC.to_string(),
                Self::SYSTEM.to_string(),
            ]);
        }

        caps
    }
}
