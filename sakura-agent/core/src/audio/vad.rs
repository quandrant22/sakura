//! Voice Activity Detection (VAD)

/// Energy-based VAD detector
pub struct Vad {
    threshold: f32,
    speech_frames: u32,
    min_speech_frames: u32,
}

impl Vad {
    /// Create a new VAD detector
    pub fn new() -> Self {
        Self {
            threshold: 0.02,
            speech_frames: 0,
            min_speech_frames: 2,
        }
    }

    /// Process an audio frame, return true if speech detected
    pub fn process(&mut self, frame: &[i16]) -> bool {
        let energy = self.rms_energy(frame);
        let is_speech = energy > self.threshold;

        if is_speech {
            self.speech_frames += 1;
        } else {
            self.speech_frames = 0;
        }

        self.speech_frames >= self.min_speech_frames
    }

    /// Calculate RMS energy
    fn rms_energy(&self, frame: &[i16]) -> f32 {
        if frame.is_empty() {
            return 0.0;
        }

        let sum: f64 = frame.iter()
            .map(|&s| {
                let normalized = s as f64 / 32768.0;
                normalized * normalized
            })
            .sum();

        (sum / frame.len() as f64).sqrt() as f32
    }

    /// Reset state
    pub fn reset(&mut self) {
        self.speech_frames = 0;
    }
}

impl Default for Vad {
    fn default() -> Self {
        Self::new()
    }
}
