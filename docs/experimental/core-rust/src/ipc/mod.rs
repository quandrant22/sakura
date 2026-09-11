//! IPC module for communication with Python executor
//!
//! Uses JSON over stdin/stdout for communication.

use std::io::{self, BufRead, Write};
use tokio::sync::mpsc;
use log::{info, error};

use crate::protocol::{Event, Action};

/// Run IPC handler
pub async fn run(
    mut action_rx: mpsc::Receiver<Action>,
    event_tx: mpsc::Sender<Event>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    info!("IPC handler started");

    // Start stdin reader thread
    let event_tx_clone = event_tx.clone();
    let stdin_handle = tokio::spawn(async move {
        if let Err(e) = read_stdin_loop(event_tx_clone).await {
            error!("Stdin reader error: {}", e);
        }
    });

    // Start stdout writer thread
    let stdout_handle = tokio::spawn(async move {
        if let Err(e) = write_stdout_loop(action_rx).await {
            error!("Stdout writer error: {}", e);
        }
    });

    // Wait for either to complete
    tokio::select! {
        _ = stdin_handle => info!("Stdin reader stopped"),
        _ = stdout_handle => info!("Stdout writer stopped"),
    }

    Ok(())
}

/// Read actions from stdin and forward to event channel
async fn read_stdin_loop(event_tx: mpsc::Sender<Event>) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let stdin = io::stdin();

    // Spawn blocking task for stdin reading
    let (tx, mut rx) = mpsc::channel::<String>(32);

    tokio::task::spawn_blocking(move || {
        let reader = stdin.lock();
        for line in reader.lines() {
            if let Ok(line) = line {
                if !line.is_empty() {
                    if tx.try_send(line).is_err() {
                        break;
                    }
                }
            }
        }
    });

    while let Some(line) = rx.recv().await {
        // Parse action from JSON
        if let Some(action) = Action::from_json(&line) {
            match action {
                Action::Command { target, args, request_id: _ } => {
                    // Convert to event and forward
                    let event = Event::CommandResult {
                        device_id: String::new(),
                        timestamp: Event::timestamp(),
                        action: format!("{}:{}", target, args),
                        result: String::new(),
                        success: true,
                        screenshot: String::new(),
                    };
                    let _ = event_tx.send(event).await;
                }
                _ => {
                    // Forward other actions as-is
                }
            }
        }
    }

    Ok(())
}

/// Write events to stdout
async fn write_stdout_loop(mut action_rx: mpsc::Receiver<Action>) -> Result<(), Box<dyn std::error::Error>> {
    let mut stdout = io::stdout();

    while let Some(action) = action_rx.recv().await {
        let json = action.to_json();
        if let Err(e) = writeln!(stdout, "{}", json) {
            error!("Failed to write to stdout: {}", e);
            break;
        }
        if let Err(e) = stdout.flush() {
            error!("Failed to flush stdout: {}", e);
            break;
        }
    }

    Ok(())
}

/// Send event to VPS via WebSocket
pub async fn send_event(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    event: &Event,
) -> Result<(), Box<dyn std::error::Error>> {
    use tokio_tungstenite::tungstenite::Message;
    use futures_util::SinkExt;

    let json = event.to_json();
    ws.send(Message::Text(json.into())).await?;
    Ok(())
}

/// Receive action from VPS via WebSocket
pub async fn recv_action(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
) -> Result<Option<Action>, Box<dyn std::error::Error>> {
    use tokio_tungstenite::tungstenite::Message;
    use futures_util::StreamExt;

    if let Some(msg) = ws.next().await {
        match msg? {
            Message::Text(text) => {
                Ok(Action::from_json(&text))
            }
            _ => Ok(None),
        }
    } else {
        Ok(None)
    }
}
