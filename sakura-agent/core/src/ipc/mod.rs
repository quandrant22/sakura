//! IPC module for communication

use tokio::sync::mpsc;
use log::{info, error};
use std::io::{self, BufRead, Write};

use crate::protocol::{Event, Action};

/// Run IPC handler
pub async fn run(
    action_rx: mpsc::Receiver<Action>,
    event_tx: mpsc::Sender<Event>,
) {
    info!("IPC handler started");

    // Stdin reader
    let event_tx_clone = event_tx.clone();
    let stdin_handle = tokio::spawn(async move {
        read_stdin(event_tx_clone).await;
    });

    // Stdout writer
    let stdout_handle = tokio::spawn(async move {
        write_stdout(action_rx).await;
    });

    tokio::select! {
        _ = stdin_handle => info!("Stdin reader stopped"),
        _ = stdout_handle => info!("Stdout writer stopped"),
    }
}

/// Read from stdin
async fn read_stdin(event_tx: mpsc::Sender<Event>) {
    let (tx, mut rx) = mpsc::channel::<String>(32);

    std::thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines() {
            if let Ok(line) = line {
                if !line.is_empty() {
                    let _ = tx.try_send(line);
                }
            }
        }
    });

    while let Some(line) = rx.recv().await {
        if let Some(action) = Action::from_json(&line) {
            match action {
                Action::Command { target, args } => {
                    let _ = event_tx.send(Event::CommandResult {
                        device_id: String::new(),
                        timestamp: Event::timestamp(),
                        action: format!("{}:{}", target, args),
                        result: String::new(),
                        success: true,
                        screenshot: String::new(),
                    }).await;
                }
                _ => {}
            }
        }
    }
}

/// Write to stdout
async fn write_stdout(mut action_rx: mpsc::Receiver<Action>) {
    let mut stdout = io::stdout();

    while let Some(action) = action_rx.recv().await {
        let json = serde_json::to_string(&action).unwrap_or_default();
        let _ = writeln!(stdout, "{}", json);
        let _ = stdout.flush();
    }
}
