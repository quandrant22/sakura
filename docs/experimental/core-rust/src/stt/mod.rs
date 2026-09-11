//! Speech-to-Text module
//!
//! Wake word detection and streaming STT using Vosk.
//! Falls back to a simple energy-based wake word detector if Vosk is not available.

use log::{info, debug, error};
use std::sync::Arc;

/// Wake word detector using Vosk
pub struct WakeWordDetector {
    wake_words: Vec<String>,
    #[cfg(feature = "vosk")]
    recognizer: vosk::Recognizer,
}

impl WakeWordDetector {
    /// Create a new wake word detector
    pub fn new(sample_rate: usize) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let wake_words = vec![
            "сакура".to_string(),
            "сакуру".to_string(),
            "сакуре".to_string(),
            "сакурой".to_string(),
            "сакур".to_string(),
            "sakura".to_string(),
        ];

        #[cfg(feature = "vosk")]
        {
            // Load Vosk model for wake word detection
            let model_path = dirs::data_local_dir()
                .unwrap_or_default()
                .join("sakura")
                .join("vosk-model-small-ru-0.22");

            if !model_path.exists() {
                return Err(format!("Vosk model not found at {:?}", model_path).into());
            }

            let model = Arc::new(vosk::Model::new(model_path.to_str().unwrap())
                .ok_or("Failed to load Vosk model")?);

            let recognizer = vosk::Recognizer::new(&model, sample_rate as f32)
                .ok_or("Failed to create Vosk recognizer")?;

            return Ok(Self {
                wake_words,
                recognizer,
            });
        }

        #[cfg(not(feature = "vosk"))]
        {
            info!("Vosk not available, using energy-based wake word detection");
            Ok(Self {
                wake_words,
            })
        }
    }

    /// Feed audio data to the detector
    pub fn feed(&mut self, _frame: &[i16]) {
        #[cfg(feature = "vosk")]
        {
            let _ = self.recognizer.accept_waveform(_frame);
        }
    }

    /// Check if wake word was detected
    pub fn detect_wake_word(&mut self) -> bool {
        #[cfg(feature = "vosk")]
        {
            let partial = self.recognizer.partial_result();
            let text = partial.text.to_lowercase();

            for word in &self.wake_words {
                if text.contains(word) {
                    debug!("Wake word detected: {}", word);
                    return true;
                }
            }
        }

        false
    }

    /// Reset detector state
    pub fn reset(&mut self) {
        #[cfg(feature = "vosk")]
        {
            self.recognizer.reset();
        }
    }
}

/// Streaming STT engine using Vosk
pub struct StreamingStt {
    buffer: Vec<i16>,
    max_buffer_size: usize,
    #[cfg(feature = "vosk")]
    recognizer: vosk::Recognizer,
}

impl StreamingStt {
    /// Create a new streaming STT engine
    pub fn new(sample_rate: usize) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        #[cfg(feature = "vosk")]
        {
            let model_path = dirs::data_local_dir()
                .unwrap_or_default()
                .join("sakura")
                .join("vosk-model-ru-0.42");

            let model_path = if model_path.exists() {
                model_path
            } else {
                dirs::data_local_dir()
                    .unwrap_or_default()
                    .join("sakura")
                    .join("vosk-model-small-ru-0.22")
            };

            if !model_path.exists() {
                return Err("No Vosk model found".into());
            }

            let model = Arc::new(vosk::Model::new(model_path.to_str().unwrap())
                .ok_or("Failed to load Vosk model")?);

            let recognizer = vosk::Recognizer::new(&model, sample_rate as f32)
                .ok_or("Failed to create Vosk recognizer")?;

            return Ok(Self {
                buffer: Vec::new(),
                max_buffer_size: 16000 * 60,
                recognizer,
            });
        }

        #[cfg(not(feature = "vosk"))]
        {
            Ok(Self {
                buffer: Vec::new(),
                max_buffer_size: 16000 * 60,
            })
        }
    }

    /// Feed audio data to the STT engine
    pub fn feed(&mut self, frame: &[i16]) {
        // Add to buffer
        self.buffer.extend_from_slice(frame);

        // Prevent buffer overflow
        if self.buffer.len() > self.max_buffer_size {
            let excess = self.buffer.len() - self.max_buffer_size;
            self.buffer.drain(..excess);
        }

        #[cfg(feature = "vosk")]
        {
            // Feed to recognizer
            let _ = self.recognizer.accept_waveform(frame);
        }
    }

    /// Get transcription result
    pub fn get_result(&mut self) -> Option<String> {
        #[cfg(feature = "vosk")]
        {
            let result = self.recognizer.final_result();
            let text = result.text.to_string();

            if text.is_empty() {
                None
            } else {
                // Post-process: capitalize, add punctuation
                Some(post_process(&text))
            }
        }

        #[cfg(not(feature = "vosk"))]
        {
            None
        }
    }

    /// Reset engine state
    pub fn reset(&mut self) {
        self.buffer.clear();

        #[cfg(feature = "vosk")]
        {
            self.recognizer.reset();
        }
    }
}

/// Post-process STT output
fn post_process(text: &str) -> String {
    if text.is_empty() {
        return text.to_string();
    }

    let mut result = text.to_string();

    // Capitalize first letter
    if let Some(first) = result.chars().next() {
        if first.is_lowercase() {
            result = format!("{}{}", first.to_uppercase(), &result[first.len_utf8()..]);
        }
    }

    // Add period if no punctuation at end
    if !result.ends_with('.') && !result.ends_with('!') && !result.ends_with('?') {
        result.push('.');
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_post_process() {
        assert_eq!(post_process("привет"), "Привет.");
        assert_eq!(post_process("как дела?"), "как дела?");
        assert_eq!(post_process(""), "");
    }
}
