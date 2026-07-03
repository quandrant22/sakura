use std::sync::mpsc;
use log::{info, error, warn};

pub fn start_capture(
    tx: mpsc::Sender<Vec<i16>>,
    sample_rate: usize,
    frame_size: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

    // Use WASAPI on Windows for better compatibility
    #[cfg(target_os = "windows")]
    let host = cpal::host_from_id(cpal::HostId::Wasapi).unwrap_or_else(|_| cpal::default_host());
    #[cfg(not(target_os = "windows"))]
    let host = cpal::default_host();

    info!("Host: {:?}", host.id());

    let device = host.default_input_device().ok_or("No input device")?;
    info!("Device: {:?}", device.name());

    // Get default config
    let default_cfg = match device.default_input_config() {
        Ok(c) => Some(c),
        Err(e) => {
            warn!("No default config: {}", e);
            None
        }
    };

    // Try default config first
    if let Some(supported) = default_cfg {
        let config: cpal::StreamConfig = supported.into();
        info!("Trying default: ch={} rate={}", config.channels, config.sample_rate.0);

        let t = tx.clone();
        match device.build_input_stream(
            &config,
            move |data: &[f32], _: &cpal::InputCallbackInfo| {
                for chunk in data.chunks(frame_size) {
                    if chunk.len() == frame_size {
                        let _ = t.send(chunk.iter().map(|&s| (s * 32767.0) as i16).collect());
                    }
                }
            },
            |err| error!("Audio err: {}", err),
            None,
        ) {
            Ok(stream) => {
                stream.play()?;
                info!("Audio capture started!");
                loop { std::thread::sleep(std::time::Duration::from_secs(1)); }
            }
            Err(e) => warn!("Default config failed: {}", e),
        }
    }

    // Try all supported configs
    let configs: Vec<_> = device.supported_input_configs()?.collect();
    info!("Trying {} configs", configs.len());

    for cfg in &configs {
        let fmt = cfg.sample_format();
        let ch = cfg.channels();
        let min_r = cfg.min_sample_rate().0;
        let max_r = cfg.max_sample_rate().0;

        for rate in [48000, 44100, 16000, 32000, 22050] {
            if rate < min_r || rate > max_r { continue; }

            let sc = cpal::StreamConfig {
                channels: ch,
                sample_rate: cpal::SampleRate(rate),
                buffer_size: cpal::BufferSize::Default,
            };

            let t = tx.clone();
            let build_result = match fmt {
                cpal::SampleFormat::F32 => {
                    device.build_input_stream(&sc, move |d: &[f32], _: &_| {
                        for c in d.chunks(frame_size) {
                            if c.len() == frame_size {
                                let _ = t.send(c.iter().map(|&x| (x * 32767.0) as i16).collect());
                            }
                        }
                    }, |e| error!("e: {}", e), None)
                }
                cpal::SampleFormat::I16 => {
                    device.build_input_stream(&sc, move |d: &[i16], _: &_| {
                        for c in d.chunks(frame_size) {
                            if c.len() == frame_size { let _ = t.send(c.to_vec()); }
                        }
                    }, |e| error!("e: {}", e), None)
                }
                cpal::SampleFormat::U16 => {
                    device.build_input_stream(&sc, move |d: &[u16], _: &_| {
                        for c in d.chunks(frame_size) {
                            if c.len() == frame_size {
                                let _ = t.send(c.iter().map(|&x| (x as i16).wrapping_add(i16::MIN)).collect());
                            }
                        }
                    }, |e| error!("e: {}", e), None)
                }
                cpal::SampleFormat::F64 => {
                    device.build_input_stream(&sc, move |d: &[f64], _: &_| {
                        for c in d.chunks(frame_size) {
                            if c.len() == frame_size {
                                let _ = t.send(c.iter().map(|&x| (x * 32767.0) as i16).collect());
                            }
                        }
                    }, |e| error!("e: {}", e), None)
                }
                _ => continue,
            };

            if let Ok(stream) = build_result {
                if stream.play().is_ok() {
                    info!("Audio OK: fmt={:?} ch={} rate={}", fmt, ch, rate);
                    loop { std::thread::sleep(std::time::Duration::from_secs(1)); }
                }
            }
        }
    }

    Err("No audio config worked".into())
}
