//! Audio capture and ring buffer for pre-roll buffering.

use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::mpsc;
use log::{info, debug, error};

use crate::protocol::Event;
use crate::vad::VadDetector;

/// Ring buffer for audio pre-roll (stores last N seconds)
pub struct AudioRingBuffer {
    buffer: VecDeque<Vec<i16>>,
    max_frames: usize,
}

impl AudioRingBuffer {
    /// Create a new ring buffer
    /// - seconds: how many seconds to buffer
    /// - frame_size: samples per frame
    /// - sample_rate: audio sample rate
    pub fn new(seconds: f32, frame_size: usize, sample_rate: usize) -> Self {
        let frames_per_second = sample_rate / frame_size;
        let max_frames = (frames_per_second as f32 * seconds) as usize;

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
    pub fn drain_all(&mut self) -> Vec<Vec<i16>> {
        self.buffer.drain(..).collect()
    }

    /// Get frame count
    pub fn len(&self) -> usize {
        self.buffer.len()
    }

    /// Clear the buffer
    pub fn clear(&mut self) {
        self.buffer.clear();
    }
}

/// Audio pipeline state
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PipelineState {
    /// Waiting for voice activity
    WaitingForVoice,
    /// Voice detected, buffering for wake word
    VoiceActive,
    /// Wake word detected, capturing command
    CapturingCommand,
}

/// Main audio pipeline
pub async fn run_pipeline(
    commands: Arc<Vec<crate::commands::CommandDef>>,
    event_tx: mpsc::Sender<Event>,
    action_tx: mpsc::Sender<crate::protocol::Action>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    info!("Starting audio pipeline...");

    // Audio parameters
    let sample_rate: usize = 16000;
    let frame_size: usize = 512; // 32ms at 16kHz
    let pre_roll_seconds: f32 = 5.0;

    // Create ring buffer for pre-roll
    let mut ring_buffer = AudioRingBuffer::new(pre_roll_seconds, frame_size, sample_rate);

    // Create VAD detector
    let mut vad = VadDetector::new(sample_rate, frame_size);

    // Create wake word detector
    let mut wake_detector = crate::stt::WakeWordDetector::new(sample_rate)?;

    // Create STT engine
    let mut stt_engine = crate::stt::StreamingStt::new(sample_rate)?;

    // State machine
    let mut state = PipelineState::WaitingForVoice;
    let mut silence_frames: u32 = 0;
    let silence_threshold: u32 = ((1.0 * sample_rate as f32) / frame_size as f32) as u32;

    // Open audio input stream
    let (tx, mut rx) = mpsc::channel::<Vec<i16>>(32);

    // Start audio capture in a separate std thread (cpal callbacks are not async-safe)
    let _capture_handle = {
        let tx = tx.clone();
        std::thread::Builder::new()
            .name("audio-capture".to_string())
            .spawn(move || {
                if let Err(e) = capture_audio_sync(tx, sample_rate, frame_size) {
                    error!("Audio capture error: {}", e);
                }
            })
    };

    info!("Audio pipeline ready. Waiting for voice...");

    // Process audio frames
    while let Some(frame) = rx.recv().await {
        // Run VAD on the frame
        let is_voice = vad.process(&frame);

        match state {
            PipelineState::WaitingForVoice => {
                // Always buffer audio for pre-roll
                ring_buffer.push(&frame);

                if is_voice {
                    // Voice started! Flush buffer to wake word detector
                    debug!("VAD: Voice started, flushing {} buffered frames", ring_buffer.len());

                    for buffered_frame in ring_buffer.drain_all() {
                        wake_detector.feed(&buffered_frame);
                    }

                    state = PipelineState::VoiceActive;
                    silence_frames = 0;

                    // Notify UI
                    let _ = event_tx.send(Event::Listening {
                        device_id: String::new(),
                        timestamp: chrono::Utc::now().timestamp() as f64,
                    }).await;
                }
            }

            PipelineState::VoiceActive => {
                // Feed to both wake word detector and STT
                wake_detector.feed(&frame);
                stt_engine.feed(&frame);

                // Check for wake word
                if wake_detector.detect_wake_word() {
                    info!("Wake word detected!");
                    state = PipelineState::CapturingCommand;
                    silence_frames = 0;

                    // Reset STT for new utterance
                    stt_engine.reset();

                    // Notify UI
                    let _ = event_tx.send(Event::WakeWordDetected {
                        device_id: String::new(),
                        timestamp: chrono::Utc::now().timestamp() as f64,
                    }).await;
                }

                // Track silence
                if is_voice {
                    silence_frames = 0;
                } else {
                    silence_frames += 1;

                    if silence_frames > silence_threshold {
                        debug!("VAD: Silence timeout, returning to wait state");
                        state = PipelineState::WaitingForVoice;
                        silence_frames = 0;
                        wake_detector.reset();
                        stt_engine.reset();
                    }
                }
            }

            PipelineState::CapturingCommand => {
                // Feed to STT
                stt_engine.feed(&frame);

                // Check if utterance is complete
                if !is_voice {
                    silence_frames += 1;

                    if silence_frames > silence_threshold {
                        // Utterance complete - get transcription
                        if let Some(text) = stt_engine.get_result() {
                            info!("STT result: {}", text);

                            // Send to VPS
                            let _ = event_tx.send(Event::SpeechRecognized {
                                device_id: String::new(),
                                text: text.clone(),
                                timestamp: chrono::Utc::now().timestamp() as f64,
                            }).await;

                            // Try to match command locally
                            if let Some(result) = crate::commands::match_command(&commands, &text) {
                                info!("Command matched: {} -> {}", text, result.action);

                                // Send action to Python executor
                                let _ = action_tx.send(crate::protocol::Action::Command {
                                    target: result.action,
                                    args: result.args,
                                    request_id: String::new(),
                                }).await;
                            }
                        }

                        // Return to waiting
                        state = PipelineState::WaitingForVoice;
                        silence_frames = 0;
                        wake_detector.reset();
                        stt_engine.reset();

                        // Notify idle
                        let _ = event_tx.send(Event::Idle {
                            device_id: String::new(),
                            timestamp: chrono::Utc::now().timestamp() as f64,
                        }).await;
                    }
                } else {
                    silence_frames = 0;
                }
            }
        }
    }

    Ok(())
}

/// Capture audio from microphone (blocking, runs on std thread)
fn capture_audio_sync(
    tx: mpsc::Sender<Vec<i16>>,
    sample_rate: usize,
    frame_size: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

    let host = cpal::default_host();
    let device = host.default_input_device()
        .ok_or("No input device available")?;

    info!("Using input device: {:?}", device.name());

    let config = cpal::StreamConfig {
        channels: 1,
        sample_rate: cpal::SampleRate(sample_rate as u32),
        buffer_size: cpal::BufferSize::Default,
    };

    let tx_clone = tx.clone();

    let stream = device.build_input_stream(
        &config,
        move |data: &[i16], _: &cpal::InputCallbackInfo| {
            for chunk in data.chunks(frame_size) {
                if chunk.len() == frame_size {
                    let _ = tx_clone.try_send(chunk.to_vec());
                }
            }
        },
        |err| log::error!("Audio stream error: {}", err),
        None,
    )?;

    stream.play()?;

    loop {
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}
