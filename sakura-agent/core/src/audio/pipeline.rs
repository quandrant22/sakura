//! Audio pipeline — Jarvis-style architecture with real Vosk

use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::mpsc;
use log::{info, debug, error};

use crate::Config;
use crate::protocol::Event;
use crate::commands::{self, CommandDef};
use crate::stt::wake_word::WakeWordDetector;
use crate::stt::recognizer::StreamingRecognizer;
use super::{capture, vad::Vad};

/// Ring buffer for pre-roll audio
struct RingBuffer {
    buffer: VecDeque<Vec<i16>>,
    max_frames: usize,
}

impl RingBuffer {
    fn new(duration_sec: f32, frame_size: usize, sample_rate: usize) -> Self {
        let frames_per_sec = sample_rate / frame_size;
        let max_frames = (frames_per_sec as f32 * duration_sec) as usize;
        Self {
            buffer: VecDeque::with_capacity(max_frames),
            max_frames,
        }
    }

    fn push(&mut self, frame: &[i16]) {
        if self.buffer.len() >= self.max_frames {
            self.buffer.pop_front();
        }
        self.buffer.push_back(frame.to_vec());
    }

    fn drain(&mut self) -> Vec<Vec<i16>> {
        self.buffer.drain(..).collect()
    }

    fn len(&self) -> usize {
        self.buffer.len()
    }

    fn clear(&mut self) {
        self.buffer.clear();
    }
}

/// Pipeline state
#[derive(Debug, Clone, Copy, PartialEq)]
enum State {
    WaitingForVoice,
    VoiceActive,
    CapturingCommand,
    Executing,
}

/// Run the audio pipeline
pub async fn run(
    config: Arc<Config>,
    commands: Arc<Vec<CommandDef>>,
    event_tx: mpsc::Sender<Event>,
    action_tx: mpsc::Sender<crate::protocol::Action>,
) {
    info!("Starting audio pipeline with Vosk...");

    // Initialize Vosk components
    // Search order: current dir → parent dir → system data dir
    let wake_model_path = {
        let local = std::path::PathBuf::from(&config.wake_model);
        let parent = std::path::PathBuf::from("..").join(&config.wake_model);
        if local.exists() {
            local
        } else if parent.exists() {
            parent
        } else {
            dirs::data_local_dir()
                .unwrap_or_default()
                .join("sakura")
                .join(&config.wake_model)
        }
    };

    let command_model_path = {
        let local = std::path::PathBuf::from(&config.command_model);
        let parent = std::path::PathBuf::from("..").join(&config.command_model);
        if local.exists() {
            local
        } else if parent.exists() {
            parent
        } else {
            dirs::data_local_dir()
                .unwrap_or_default()
                .join("sakura")
                .join(&config.command_model)
        }
    };

    // Use ONE model for both wake word and STT
    info!("Loading Vosk model: {:?}", command_model_path);
    let mut wake_detector = None;
    let mut stt = None;

    match WakeWordDetector::new(
        command_model_path.to_str().unwrap_or(""),
        config.sample_rate,
        config.wake_words.clone(),
    ) {
        Ok(d) => {
            info!("Vosk model loaded OK");
            wake_detector = Some(d);
        }
        Err(e) => {
            log::error!("Vosk failed: {}", e);
        }
    }

    // Create components
    let mut ring_buffer = RingBuffer::new(
        config.pre_roll_seconds,
        config.frame_size,
        config.sample_rate,
    );
    let mut vad = Vad::new();
    let mut state = State::WaitingForVoice;
    let mut silence_frames: u32 = 0;
    let silence_threshold = (0.3 * config.sample_rate as f32 / config.frame_size as f32) as u32;

    // Command audio buffer
    let mut command_audio: Vec<i16> = Vec::new();

    // Start audio capture
    info!("Starting audio capture thread...");
    let (tx, rx) = std::sync::mpsc::channel::<Vec<i16>>();
    let sample_rate = config.sample_rate;
    let frame_size = config.frame_size;

    let capture_handle = std::thread::Builder::new()
        .name("audio-capture".to_string())
        .spawn(move || {
            info!("Capture thread started");
            match capture::start_capture(tx, sample_rate, frame_size) {
                Ok(_) => info!("Capture thread finished normally"),
                Err(e) => error!("Capture error: {}", e),
            }
        });

    match capture_handle {
        Ok(h) => info!("Capture thread spawned"),
        Err(e) => error!("Failed to spawn capture thread: {}", e),
    }

    info!("Pipeline ready. Waiting for audio...");

    // Main loop
    while let Ok(frame) = rx.recv() {
        let is_voice = vad.process(&frame);

        match state {
            State::WaitingForVoice => {
                // Buffer for pre-roll
                ring_buffer.push(&frame);

                // Feed to wake word detector (if available)
                let wake_detected = if let Some(ref mut detector) = wake_detector {
                    detector.feed(&frame)
                } else {
                    // No wake word detector — auto-detect on voice
                    is_voice
                };

                if wake_detected {
                    debug!("Wake word detected! Flushing {} pre-roll frames", ring_buffer.len());
                    state = State::VoiceActive;
                    silence_frames = 0;

                    // Reset STT for new utterance
                    if let Some(ref mut stt) = stt {
                        stt.reset();
                    }
                    command_audio.clear();

                    let _ = event_tx.send(Event::Listening {
                        device_id: config.device_id.clone(),
                        timestamp: chrono::Utc::now().timestamp() as f64,
                    }).await;
                }
            }

            State::VoiceActive => {
                // Feed to STT while tracking silence
                if let Some(ref mut stt) = stt {
                    let partial = stt.feed(&frame);
                    if !partial.is_empty() {
                        debug!("[STT] {}", partial);
                    }
                }

                if is_voice {
                    silence_frames = 0;
                    command_audio.extend_from_slice(&frame);
                } else {
                    silence_frames += 1;

                    if silence_frames > silence_threshold {
                        // Get final transcription
                        let text = if let Some(ref mut stt) = stt {
                            stt.get_final()
                        } else {
                            String::new()
                        };

                        if !text.is_empty() {
                            info!("[STT] '{}'", text);

                            // Match command
                            if let Some(result) = commands::match_command(&commands, &text) {
                                info!("Command matched: {} -> {}", text, result.action);

                                let _ = event_tx.send(Event::SpeechRecognized {
                                    device_id: config.device_id.clone(),
                                    timestamp: chrono::Utc::now().timestamp() as f64,
                                    text: text.clone(),
                                }).await;

                                // Send action to executor
                                let _ = action_tx.send(crate::protocol::Action::Command {
                                    target: result.action,
                                    args: result.args,
                                }).await;
                            } else {
                                debug!("No command matched for: '{}'", text);
                            }
                        }

                        // Return to waiting
                        state = State::WaitingForVoice;
                        silence_frames = 0;
                        command_audio.clear();
                        ring_buffer.clear();

                        let _ = event_tx.send(Event::Idle {
                            device_id: config.device_id.clone(),
                            timestamp: chrono::Utc::now().timestamp() as f64,
                        }).await;
                    }
                }
            }

            State::Executing => {
                state = State::WaitingForVoice;
            }

            _ => {}
        }
    }
}
