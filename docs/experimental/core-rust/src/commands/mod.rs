//! Command matching module
//!
//! TOML-based command definitions with fuzzy matching.

use std::collections::HashMap;
use std::path::Path;
use serde::Deserialize;
use log::{info, debug};

/// Slot definition from TOML
#[derive(Debug, Clone, Deserialize)]
pub struct SlotDef {
    #[serde(default)]
    pub entity: String,
    #[serde(default)]
    pub context: Vec<String>,
    #[serde(default)]
    pub required: bool,
}

/// Command definition from TOML
#[derive(Debug, Clone, Deserialize)]
pub struct CommandDef {
    pub id: String,
    #[serde(default = "default_action_type")]
    pub cmd_type: String,
    #[serde(default)]
    pub action: String,
    #[serde(default)]
    pub args: String,
    #[serde(default)]
    pub phrases: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub keywords: Vec<String>,
    #[serde(default)]
    pub patterns: Vec<String>,
    #[serde(default)]
    pub slots: HashMap<String, SlotDef>,
    #[serde(default)]
    pub priority: i32,
    #[serde(default)]
    pub description: String,
}

fn default_action_type() -> String {
    "action".to_string()
}

/// Command match result
#[derive(Debug, Clone)]
pub struct MatchResult {
    pub command: CommandDef,
    pub action: String,
    pub args: String,
    pub confidence: f64,
    pub slots: HashMap<String, String>,
}

/// Load commands from TOML files
pub fn load_commands(dir_path: &str) -> Result<Vec<CommandDef>, Box<dyn std::error::Error>> {
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
        let data:toml::Value = toml::from_str(&content)?;

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

/// Match a voice command against all registered commands
pub fn match_command(commands: &[CommandDef], text: &str) -> Option<MatchResult> {
    if text.is_empty() {
        return None;
    }

    let text_lower = text.to_lowercase();
    let mut best_match: Option<MatchResult> = None;
    let mut best_score = 0.0;

    // Sort by priority (higher first)
    let mut sorted_cmds = commands.to_vec();
    sorted_cmds.sort_by(|a, b| b.priority.cmp(&a.priority));

    for cmd in &sorted_cmds {
        if let Some(result) = match_single_command(cmd, &text_lower) {
            if result.confidence > best_score {
                best_score = result.confidence;
                best_match = Some(result);

                // Perfect match
                if best_score >= 0.99 {
                    return best_match;
                }
            }
        }
    }

    best_match
}

/// Match a single command against text
fn match_single_command(cmd: &CommandDef, text: &str) -> Option<MatchResult> {
    // 1. Exact phrase match
    for (_lang, phrases) in &cmd.phrases {
        for phrase in phrases {
            let phrase_lower = phrase.to_lowercase();
            if text == phrase_lower {
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

    // 2. Substring match
    for (_lang, phrases) in &cmd.phrases {
        for phrase in phrases {
            let phrase_lower = phrase.to_lowercase();
            if text.contains(&phrase_lower) {
                let slots = extract_slots_simple(cmd, text, &phrase_lower);
                return Some(MatchResult {
                    command: cmd.clone(),
                    action: cmd.action.clone(),
                    args: fill_args(&cmd.args, &slots),
                    confidence: 0.9,
                    slots,
                });
            }
        }
    }

    // 3. Keyword match
    for keyword in &cmd.keywords {
        let kw_lower = keyword.to_lowercase();
        if text.contains(&kw_lower) {
            return Some(MatchResult {
                command: cmd.clone(),
                action: cmd.action.clone(),
                args: fill_args(&cmd.args, &HashMap::new()),
                confidence: 0.8,
                slots: HashMap::new(),
            });
        }
    }

    // 4. Fuzzy match (word overlap)
    for (_lang, phrases) in &cmd.phrases {
        for phrase in phrases {
            let phrase_words: Vec<&str> = phrase.split_whitespace().collect();
            let text_words: Vec<&str> = text.split_whitespace().collect();

            let overlap = phrase_words.iter()
                .filter(|w| text_words.contains(w))
                .count();

            if overlap >= 2 {
                let score = overlap as f64 / phrase_words.len().max(text_words.len()) as f64;
                if score >= 0.5 {
                    return Some(MatchResult {
                        command: cmd.clone(),
                        action: cmd.action.clone(),
                        args: fill_args(&cmd.args, &HashMap::new()),
                        confidence: score * 0.7,
                        slots: HashMap::new(),
                    });
                }
            }
        }
    }

    None
}

/// Simple slot extraction by removing the matched phrase
fn extract_slots_simple(cmd: &CommandDef, text: &str, phrase: &str) -> HashMap<String, String> {
    let mut slots = HashMap::new();
    let remaining = text.replace(phrase, "").trim().to_string();

    if !remaining.is_empty() && !cmd.slots.is_empty() {
        // Assign remaining text to the first slot
        if let Some((slot_name, _)) = cmd.slots.iter().next() {
            slots.insert(slot_name.clone(), remaining);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_match_command() {
        let mut cmd = CommandDef {
            id: "volume_up".to_string(),
            cmd_type: "action".to_string(),
            action: "volume_up".to_string(),
            args: "{delta}".to_string(),
            phrases: HashMap::new(),
            keywords: vec!["громче".to_string(), "прибавь".to_string()],
            patterns: Vec::new(),
            slots: HashMap::new(),
            priority: 15,
            description: "Increase volume".to_string(),
        };

        let commands = vec![cmd.clone()];

        let result = match_command(&commands, "громче");
        assert!(result.is_some());
        assert_eq!(result.unwrap().action, "volume_up");
    }
}
