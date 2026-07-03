//! Streaming speech recognizer using Vosk

use std::sync::Arc;
use log::{info, debug};

/// Streaming speech recognizer
pub struct StreamingRecognizer {
    model: Arc<vosk::Model>,
    recognizer: vosk::Recognizer,
    partial: String,
    final_text: String,
}

impl StreamingRecognizer {
    /// Create a new streaming recognizer
    pub fn new(model_path: &str, sample_rate: usize) -> Result<Self, Box<dyn std::error::Error>> {
        let model = Arc::new(vosk::Model::new(model_path)
            .ok_or("Failed to load Vosk model")?);

        let mut recognizer = vosk::Recognizer::new(&model, sample_rate as f32)
            .ok_or("Failed to create Vosk recognizer")?;

        recognizer.set_words(true);

        info!("Streaming recognizer ready");

        Ok(Self {
            model,
            recognizer,
            partial: String::new(),
            final_text: String::new(),
        })
    }

    /// Feed audio frame, return partial or final text
    pub fn feed(&mut self, frame: &[i16]) -> String {
        match self.recognizer.accept_waveform(frame) {
            Ok(vosk::DecodingState::Running) => {
                // Partial result
                let partial = self.recognizer.partial_result();
                self.partial = partial.partial.to_string();
                self.partial.clone()
            }
            Ok(vosk::DecodingState::Finalized) => {
                // Final result
                let result = self.recognizer.result();
                if let Some(single) = result.single() {
                    let text = single.text.to_string();
                    if !text.is_empty() {
                        debug!("STT final: '{}'", text);
                        self.final_text = text.clone();
                        return text;
                    }
                }
                self.partial.clone()
            }
            Ok(vosk::DecodingState::Failed) => {
                self.partial.clone()
            }
            Err(_) => {
                self.partial.clone()
            }
        }
    }

    /// Get final result and reset
    pub fn get_final(&mut self) -> String {
        let result = self.recognizer.final_result();
        let text = if let Some(single) = result.single() {
            single.text.to_string()
        } else {
            String::new()
        };

        let final_text = if text.is_empty() {
            self.final_text.clone()
        } else {
            text
        };

        self.reset();
        final_text
    }

    /// Get current partial result
    pub fn partial(&self) -> &str {
        &self.partial
    }

    /// Reset recognizer
    pub fn reset(&mut self) {
        self.recognizer.reset();
        self.partial.clear();
        self.final_text.clear();
    }
}
