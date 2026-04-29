//! WebSocket handler for JARVIS HUD real-time metrics streaming

use axum::{
    extract::{State, ws::{WebSocket, WebSocketUpgrade}},
    response::IntoResponse,
};
use futures::{sink::SinkExt, stream::StreamExt};
use tokio::sync::broadcast;
use crate::AppState;
use crate::generated::syrabit::MetricsUpdate;

/// Metrics broadcaster for WebSocket connections
pub struct MetricsBroadcaster {
    tx: broadcast::Sender<MetricsUpdate>,
}

impl MetricsBroadcaster {
    pub fn new(tx: broadcast::Sender<MetricsUpdate>) -> Self {
        Self { tx }
    }

    /// Run the metrics broadcaster task
    pub async fn run(self) {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(1));
        
        loop {
            interval.tick().await;
            
            // Generate system metrics
            let metrics = generate_metrics_update();
            
            // Broadcast to all connected WebSocket clients
            if let Err(e) = self.tx.send(metrics) {
                tracing::warn!("Failed to broadcast metrics: {}", e);
            }
        }
    }
}

fn generate_metrics_update() -> MetricsUpdate {
    use std::time::{SystemTime, UNIX_EPOCH};
    
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;

    MetricsUpdate {
        timestamp,
        system: Some(crate::generated::syrabit::SystemMetrics {
            cpu_usage: 0.25 + (rand::random::<f32>() * 0.1),
            memory_usage: 0.45 + (rand::random::<f32>() * 0.05),
            active_connections: 50 + rand::random::<i32>() % 20,
            requests_per_second: 100 + rand::random::<i32>() % 50,
            avg_latency_ms: 15.0 + (rand::random::<f32>() * 5.0),
        }),
        agents: Some(crate::generated::syrabit::ActiveAgents {
            total: 5,
            idle: 2,
            running: 2,
            paused: 1,
            error: 0,
        }),
        health: Some(crate::generated::syrabit::NodeHealth {
            healthy: true,
            load_factor: 0.35,
            warnings: vec![],
        }),
    }
}

/// WebSocket endpoint handler for metrics streaming
pub async fn metrics_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(|socket| handle_socket(socket, state.metrics_tx))
}

async fn handle_socket(socket: WebSocket, tx: broadcast::Sender<MetricsUpdate>) {
    let (mut sender, mut receiver) = socket.split();
    
    // Subscribe to metrics broadcasts
    let mut rx = tx.subscribe();
    
    // Spawn task to receive messages from client (mostly for ping/pong)
    let recv_task = tokio::spawn(async move {
        while let Some(msg) = receiver.next().await {
            match msg {
                Ok(axum::extract::ws::Message::Close(_)) => break,
                Ok(_) => {}
                Err(e) => {
                    tracing::warn!("WebSocket error: {}", e);
                    break;
                }
            }
        }
    });

    // Send metrics updates to client
    let send_task = tokio::spawn(async move {
        while let Ok(metrics) = rx.recv().await {
            let json = serde_json::to_string(&metrics).unwrap_or_default();
            if sender
                .send(axum::extract::ws::Message::Text(json.into()))
                .await
                .is_err()
            {
                break;
            }
        }
    });

    // Wait for either task to complete
    tokio::select! {
        _ = recv_task => {},
        _ = send_task => {},
    }

    tracing::info!("WebSocket client disconnected");
}

// Add rand dependency to Cargo.toml for random metrics generation
