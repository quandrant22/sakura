//! Ring buffer for audio pre-roll buffering

use std::collections::VecDeque;

/// Ring buffer that stores the last N seconds of audio
pub struct RingBuffer {
    buffer: VecDeque<Vec<i16>>,
    max_frames: usize,
}

impl RingBuffer {
    /// Create a new ring buffer
    pub fn new(duration_sec: f32, frame_size: usize, sample_rate: usize) -> Self {
        let frames_per_sec = sample_rate / frame_size;
        let max_frames = (frames_per_sec as f32 * duration_sec) as usize;

        Self {
            buffer: VecDeque::with_capacity(max_frames),
            max_frames,
        }
    }

    /// Push a frame, dropping oldest if full
    pub fn push(&mut self, frame: &[i16]) {
        if self.buffer.len() >= self.max_frames {
            self.buffer.pop_front();
        }
        self.buffer.push_back(frame.to_vec());
    }

    /// Drain all buffered frames
    pub fn drain(&mut self) -> Vec<Vec<i16>> {
        self.buffer.drain(..).collect()
    }

    /// Get frame count
    pub fn len(&self) -> usize {
        self.buffer.len()
    }

    /// Check if empty
    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }

    /// Clear the buffer
    pub fn clear(&mut self) {
        self.buffer.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ring_buffer() {
        let mut buf = RingBuffer::new(1.0, 512, 16000);
        assert!(buf.is_empty());

        buf.push(&vec![0i16; 512]);
        assert_eq!(buf.len(), 1);

        let frames = buf.drain();
        assert_eq!(frames.len(), 1);
        assert!(buf.is_empty());
    }
}
