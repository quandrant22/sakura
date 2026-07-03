//! Intent classification

use crate::commands::CommandDef;

/// Intent classification result
#[derive(Debug, Clone)]
pub struct Intent {
    pub id: String,
    pub confidence: f64,
    pub slots: std::collections::HashMap<String, String>,
}

/// Intent classifier using fuzzy matching
pub struct IntentClassifier;

impl IntentClassifier {
    /// Classify text into an intent
    pub fn classify(text: &str, commands: &[CommandDef]) -> Option<Intent> {
        if text.is_empty() || commands.is_empty() {
            return None;
        }

        let text_lower = text.to_lowercase();
        let mut best: Option<Intent> = None;
        let mut best_score = 0.0;

        for cmd in commands {
            // Check phrases
            for (_lang, phrases) in &cmd.phrases {
                for phrase in phrases {
                    let phrase_lower = phrase.to_lowercase();

                    // Exact match
                    if text_lower == phrase_lower {
                        return Some(Intent {
                            id: cmd.id.clone(),
                            confidence: 1.0,
                            slots: std::collections::HashMap::new(),
                        });
                    }

                    // Substring match
                    if text_lower.contains(&phrase_lower) {
                        let score = phrase_lower.len() as f64 / text_lower.len() as f64;
                        if score > best_score {
                            best_score = score;
                            best = Some(Intent {
                                id: cmd.id.clone(),
                                confidence: score * 0.9,
                                slots: std::collections::HashMap::new(),
                            });
                        }
                    }
                }
            }

            // Check keywords
            for keyword in &cmd.keywords {
                if text_lower.contains(&keyword.to_lowercase()) {
                    let score = 0.8;
                    if score > best_score {
                        best_score = score;
                        best = Some(Intent {
                            id: cmd.id.clone(),
                            confidence: score,
                            slots: std::collections::HashMap::new(),
                        });
                    }
                }
            }
        }

        best
    }
}
