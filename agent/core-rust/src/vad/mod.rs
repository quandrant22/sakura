//! Voice Activity Detection (VAD)
//!
//! Energy-based VAD for detecting speech in audio frames.
//! Falls back to Silero VAD when available for better accuracy.

use log::debug;

/// VAD detector
pub struct VadDetector {
    sample_rate: usize,
    frame_size: usize,
    threshold: f32,
    speech_frames: u32,
    silence_frames: u32,
    min_speech_frames: u32,
    min_silence_frames: u32,
}

impl VadDetector {
    /// Create a new VAD detector
    pub fn new(sample_rate: usize, frame_size: usize) -> Self {
        Self {
            sample_rate,
            frame_size,
            threshold: 0.02, // Energy threshold
            speech_frames: 0,
            silence_frames: 0,
            min_speech_frames: 2,  // 64ms of speech before considering it speech
            min_silence_frames: 3, // 96ms of silence before considering it silence
        }
    }

    /// Process an audio frame and return true if speech is detected
    pub fn process(&mut self, frame: &[i16]) -> bool {
        // Calculate frame energy (RMS)
        let energy = self.calculate_energy(frame);

        // Check against threshold
        let is_speech = energy > self.threshold;

        if is_speech {
            self.speech_frames = 0;
            self.speech_frames += 1;
        } else {
            self.speech_frames = 0;
            self.silence_frames += 1;
        }

        // Return true only if we have enough consecutive speech frames
        self.speech_frames >= self.min_speech_frames
    }

    /// Calculate RMS energy of a frame
    fn calculate_energy(&self, frame: &[i16]) -> f32 {
        if frame.is_empty() {
            return 0.0;
        }

        let sum_squares: f64 = frame.iter()
            .map(|&sample| {
                let normalized = sample as f64 / 32768.0;
                normalized * normalized
            })
            .sum();

        let rms = (sum_squares / frame.len() as f64).sqrt();
        rms as f32
    }

    /// Reset VAD state
    pub fn reset(&mut self) {
        self.speech_frames = 0;
        self.silence_frames = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_energy_calculation() {
        let mut vad = VadDetector::new(16000, 512);

        // Silent frame
        let silent_frame = vec![0i16; 512];
        assert!(!vad.process(&silent_frame));

        // Speech-like frame (sine wave)
        let speech_frame: Vec<i16> = (0..512)
            .map(|i| {
                let t = i as f64 / 16000.0;
                (16000.0 * (2.0 * std::f64::consts::PI * 440.0 * t).sin()) as i16
            })
            .collect();

        // Need multiple frames to trigger
        assert!(!vad.process(&speech_frame));
        assert!(vad.process(&speech_frame));
    }
}
