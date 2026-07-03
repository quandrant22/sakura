//! Wake word detection using Vosk

use std::sync::Arc;
use log::{info, debug};

/// Wake word detector using Vosk partial results
pub struct WakeWordDetector {
    model: Arc<vosk::Model>,
    recognizer: vosk::Recognizer,
    wake_words: Vec<String>,
    partial: String,
}

impl WakeWordDetector {
    /// Create a new wake word detector
    pub fn new(model_path: &str, sample_rate: usize, wake_words: Vec<String>) -> Result<Self, Box<dyn std::error::Error>> {
        let model = Arc::new(vosk::Model::new(model_path)
            .ok_or("Failed to load Vosk model")?);

        let mut recognizer = vosk::Recognizer::new(&model, sample_rate as f32)
            .ok_or("Failed to create Vosk recognizer")?;

        recognizer.set_words(true);

        info!("Wake word detector ready with {} words", wake_words.len());

        Ok(Self {
            model,
            recognizer,
            wake_words,
            partial: String::new(),
        })
    }

    /// Feed audio frame and check for wake word
    pub fn feed(&mut self, frame: &[i16]) -> bool {
        let _ = self.recognizer.accept_waveform(frame);

        let partial_result = self.recognizer.partial_result();
        self.partial = partial_result.partial.to_lowercase();

        for word in &self.wake_words {
            if self.partial.contains(&word.to_lowercase()) {
                debug!("Wake word detected: '{}' in '{}'", word, self.partial);
                self.reset();
                return true;
            }
        }

        false
    }

    /// Get current partial result
    pub fn partial(&self) -> &str {
        &self.partial
    }

    /// Reset recognizer state
    pub fn reset(&mut self) {
        self.recognizer.reset();
        self.partial.clear();
    }
}
