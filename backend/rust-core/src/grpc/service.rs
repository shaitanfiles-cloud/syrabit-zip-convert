//! gRPC service implementation for Edge communication

use tonic::{Request, Response, Status, Streaming};
use tokio::sync::broadcast;
use sqlx::PgPool;
use crate::generated::syrabit::{
    neural_mesh_service_server::NeuralMeshService,
    ChatRequest, ChatResponse,
    RagQuery, RagResponse,
    AgentCommand, AgentResponse,
    HealthCheck,
    MetricsRequest, MetricsUpdate,
};

/// gRPC service implementation
pub struct NeuralMeshGrpcService {
    db: PgPool,
    metrics_tx: broadcast::Sender<MetricsUpdate>,
}

impl NeuralMeshGrpcService {
    pub fn new(db: PgPool, metrics_tx: broadcast::Sender<MetricsUpdate>) -> Self {
        Self { db, metrics_tx }
    }
}

impl Clone for NeuralMeshGrpcService {
    fn clone(&self) -> Self {
        Self {
            db: self.db.clone(),
            metrics_tx: self.metrics_tx.clone(),
        }
    }
}

#[tonic::async_trait]
impl NeuralMeshService for NeuralMeshGrpcService {
    type ChatStream = tokio_stream::wrappers::BroadcastStream<ChatResponse>;
    type StreamMetricsStream = tokio_stream::wrappers::BroadcastStream<MetricsUpdate>;

    /// Chat with AI assistant (streaming response)
    async fn chat(
        &self,
        request: Request<ChatRequest>,
    ) -> Result<Response<Self::ChatStream>, Status> {
        let msg = request.into_inner();
        tracing::info!("gRPC Chat request from user: {}", msg.user_id);

        // TODO: Implement actual chat logic with LLM
        // For now, return a simple response stream
        
        use tokio_stream::wrappers::BroadcastStream;
        let (tx, _rx) = broadcast::channel(10);
        
        Ok(Response::new(BroadcastStream::new(tx)))
    }

    /// RAG query with GraphRAG support
    async fn query_rag(
        &self,
        request: Request<RagQuery>,
    ) -> Result<Response<RagResponse>, Status> {
        let query = request.into_inner();
        tracing::info!("gRPC RAG query: {}", query.query);

        // Execute GraphRAG search
        let results = match crate::services::graph_rag::execute_graph_rag(&self.db, query).await {
            Ok(results) => results,
            Err(e) => {
                return Err(Status::internal(format!("GraphRAG failed: {}", e)));
            }
        };

        let rag_results = results.into_iter().map(|r| {
            crate::generated::syrabit::RagResult {
                document_id: r.document_id,
                content: r.content,
                score: r.score,
                metadata: r.metadata,
                related_ids: r.related_ids,
            }
        }).collect();

        let response = RagResponse {
            results: rag_results,
            latency_ms: 0, // TODO: Calculate actual latency
            search_type: "hybrid".to_string(),
            total_traversed: 0, // TODO: Track traversal count
        };

        Ok(Response::new(response))
    }

    /// Execute agent command
    async fn execute_agent(
        &self,
        request: Request<AgentCommand>,
    ) -> Result<Response<AgentResponse>, Status> {
        let command = request.into_inner();
        tracing::info!("gRPC Agent command: {} for agent {}", command.action, command.agent_id);

        // TODO: Implement actual agent execution

        let response = AgentResponse {
            command_id: uuid::Uuid::new_v4().to_string(),
            success: true,
            error_message: None,
            status: Some(crate::generated::syrabit::AgentStatus {
                agent_id: command.agent_id,
                state: "running".to_string(),
                current_task: "Processing command".to_string(),
                started_at: chrono::Utc::now().timestamp(),
                progress: std::collections::HashMap::new(),
            }),
        };

        Ok(Response::new(response))
    }

    /// Health check
    async fn health_check(
        &self,
        request: Request<HealthCheck>,
    ) -> Result<Response<HealthCheck>, Status> {
        let _msg = request.into_inner();
        
        // Check database connectivity
        let db_healthy = sqlx::query("SELECT 1")
            .fetch_one(&self.db)
            .await
            .is_ok();

        let response = HealthCheck {
            service: "syrabit-rust-core".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            uptime_seconds: 0, // TODO: Track actual uptime
            metrics: Some(crate::generated::syrabit::SystemMetrics {
                cpu_usage: 0.25,
                memory_usage: 0.45,
                active_connections: 10,
                requests_per_second: 100,
                avg_latency_ms: 15.0,
            }),
        };

        if !db_healthy {
            return Ok(Response::new(response));
        }

        Ok(Response::new(response))
    }

    /// Stream real-time metrics for JARVIS HUD
    async fn stream_metrics(
        &self,
        request: Request<MetricsRequest>,
    ) -> Result<Response<Self::StreamMetricsStream>, Status> {
        let _config = request.into_inner();
        tracing::info!("gRPC metrics stream requested");

        // Subscribe to metrics broadcasts
        let rx = self.metrics_tx.subscribe();
        
        use tokio_stream::wrappers::BroadcastStream;
        Ok(Response::new(BroadcastStream::new(rx)))
    }
}
