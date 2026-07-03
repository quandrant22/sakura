//! TOML-based command definitions

use std::collections::HashMap;
use std::path::Path;
use serde::Deserialize;
use log::info;

/// Slot definition
#[derive(Debug, Clone, Deserialize)]
pub struct SlotDef {
    #[serde(default)]
    pub entity: String,
    #[serde(default)]
    pub context: Vec<String>,
    #[serde(default = "default_true")]
    pub required: bool,
}

fn default_true() -> bool { true }

/// Command definition
#[derive(Debug, Clone, Deserialize)]
pub struct CommandDef {
    pub id: String,
    #[serde(default = "default_action")]
    pub action: String,
    #[serde(default)]
    pub args: String,
    #[serde(default)]
    pub phrases: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub keywords: Vec<String>,
    #[serde(default)]
    pub slots: HashMap<String, SlotDef>,
    #[serde(default)]
    pub priority: i32,
    #[serde(default)]
    pub description: String,
}

fn default_action() -> String { String::new() }

/// Command match result
#[derive(Debug, Clone)]
pub struct MatchResult {
    pub command: CommandDef,
    pub action: String,
    pub args: String,
    pub confidence: f64,
    pub slots: HashMap<String, String>,
}

/// Load all commands from directory
pub fn load_all(dir_path: &str) -> Result<Vec<CommandDef>, Box<dyn std::error::Error>> {
    let dir = Path::new(dir_path);
    if !dir.exists() {
        info!("Commands directory not found: {}", dir_path);
        return Ok(Vec::new());
    }

    let mut commands = Vec::new();

    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();

        if !path.is_dir() {
            continue;
        }

        let toml_file = path.join("command.toml");
        if !toml_file.exists() {
            continue;
        }

        let content = std::fs::read_to_string(&toml_file)?;
        let data: toml::Value = toml::from_str(&content)?;

        if let Some(cmds) = data.get("commands").and_then(|v| v.as_array()) {
            for cmd_data in cmds {
                if let Ok(cmd) = cmd_data.clone().try_into::<CommandDef>() {
                    commands.push(cmd);
                }
            }
        }
    }

    info!("Loaded {} commands from {}", commands.len(), dir_path);
    Ok(commands)
}

/// Match text against commands
pub fn match_command(commands: &[CommandDef], text: &str) -> Option<MatchResult> {
    if text.is_empty() || commands.is_empty() {
        return None;
    }

    let text_lower = text.to_lowercase();
    let mut best: Option<MatchResult> = None;
    let mut best_score = 0.0;

    // Sort by priority
    let mut sorted = commands.to_vec();
    sorted.sort_by(|a, b| b.priority.cmp(&a.priority));

    for cmd in &sorted {
        // Exact phrase match
        for (_lang, phrases) in &cmd.phrases {
            for phrase in phrases {
                if text_lower == phrase.to_lowercase() {
                    return Some(MatchResult {
                        command: cmd.clone(),
                        action: cmd.action.clone(),
                        args: fill_args(&cmd.args, &HashMap::new()),
                        confidence: 1.0,
                        slots: HashMap::new(),
                    });
                }
            }
        }

        // Substring match
        for (_lang, phrases) in &cmd.phrases {
            for phrase in phrases {
                if text_lower.contains(&phrase.to_lowercase()) {
                    let slots = extract_simple(cmd, text, &phrase);
                    let score = 0.9;
                    if score > best_score {
                        best_score = score;
                        best = Some(MatchResult {
                            command: cmd.clone(),
                            action: cmd.action.clone(),
                            args: fill_args(&cmd.args, &slots),
                            confidence: score,
                            slots,
                        });
                    }
                }
            }
        }

        // Keyword match
        for keyword in &cmd.keywords {
            if text_lower.contains(&keyword.to_lowercase()) {
                let score = 0.8;
                if score > best_score {
                    best_score = score;
                    best = Some(MatchResult {
                        command: cmd.clone(),
                        action: cmd.action.clone(),
                        args: fill_args(&cmd.args, &HashMap::new()),
                        confidence: score,
                        slots: HashMap::new(),
                    });
                }
            }
        }
    }

    best
}

/// Simple slot extraction
fn extract_simple(cmd: &CommandDef, text: &str, phrase: &str) -> HashMap<String, String> {
    let mut slots = HashMap::new();
    let remaining = text.replace(phrase, "").trim().to_string();

    if !remaining.is_empty() && !cmd.slots.is_empty() {
        if let Some((name, _)) = cmd.slots.iter().next() {
            slots.insert(name.clone(), remaining);
        }
    }

    slots
}

/// Fill argument template with slot values
fn fill_args(template: &str, slots: &HashMap<String, String>) -> String {
    let mut result = template.to_string();
    for (name, value) in slots {
        result = result.replace(&format!("{{{}}}", name), value);
    }
    result
}
