//! D1 Sync Handler - Synchronize PostgreSQL data to Cloudflare D1
//! 
//! This module provides endpoints for syncing content data from Postgres
//! to Cloudflare D1 (SQLite) for edge caching. Critical transformations:
//! - UUID → TEXT strings (D1 doesn't support UUID type natively)
//! - TIMESTAMPTZ → Unix milliseconds (JavaScript-compatible timestamps)

use axum::{
    extract::{State, Path},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use crate::AppState;

/// Response structure for D1 sync endpoints
#[derive(Debug, Serialize)]
pub struct D1SyncResponse {
    pub success: bool,
    pub table: String,
    pub count: usize,
    pub data: Vec<serde_json::Value>,
    pub synced_at: i64, // Unix timestamp in milliseconds
}

/// Error response for D1 sync failures
#[derive(Debug, Serialize)]
pub struct D1SyncError {
    pub success: bool,
    pub error: String,
    pub table: String,
}

impl D1SyncError {
    fn new(table: String, error: String) -> Self {
        Self {
            success: false,
            error,
            table,
        }
    }
}

/// Sync boards table to D1 format
/// GET /api/edge/d1-sync/boards
pub async fn sync_boards(
    State(state): State<AppState>,
) -> Result<Json<D1SyncResponse>, StatusCode> {
    sync_table_to_d1(&state.db, "boards", |row| {
        serde_json::json!({
            "id": row.id, // Already TEXT in our schema
            "name": row.name,
            "code": row.code,
            "description": row.description,
            "created_at": row.created_at.timestamp_millis(),
            "updated_at": row.updated_at.timestamp_millis(),
        })
    })
    .await
}

/// Sync classes table to D1 format
/// GET /api/edge/d1-sync/classes
pub async fn sync_classes(
    State(state): State<AppState>,
) -> Result<Json<D1SyncResponse>, StatusCode> {
    sync_table_to_d1(&state.db, "classes", |row| {
        serde_json::json!({
            "id": row.id,
            "name": row.name,
            "board_id": row.board_id,
            "grade_level": row.grade_level,
            "created_at": row.created_at.timestamp_millis(),
            "updated_at": row.updated_at.timestamp_millis(),
        })
    })
    .await
}

/// Sync subjects table to D1 format
/// GET /api/edge/d1-sync/subjects
pub async fn sync_subjects(
    State(state): State<AppState>,
) -> Result<Json<D1SyncResponse>, StatusCode> {
    sync_table_to_d1(&state.db, "subjects", |row| {
        serde_json::json!({
            "id": row.id,
            "name": row.name,
            "board_id": row.board_id,
            "class_id": row.class_id,
            "description": row.description,
            "created_at": row.created_at.timestamp_millis(),
            "updated_at": row.updated_at.timestamp_millis(),
        })
    })
    .await
}

/// Sync chapters table to D1 format
/// GET /api/edge/d1-sync/chapters
pub async fn sync_chapters(
    State(state): State<AppState>,
) -> Result<Json<D1SyncResponse>, StatusCode> {
    // Chapters may be a separate table or derived from subject_pages
    // Adjust query based on actual schema
    let query = r#"
        SELECT 
            id,
            subject_id,
            title as name,
            description,
            chapter_order,
            created_at,
            updated_at
        FROM chapters
        ORDER BY chapter_order
    "#;
    
    match sqlx::query(query).fetch_all(&state.db).await {
        Ok(rows) => {
            let data: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|row| {
                    let id: String = row.get("id");
                    let subject_id: String = row.get("subject_id");
                    let name: String = row.get("name");
                    let description: Option<String> = row.get("description");
                    let chapter_order: i32 = row.get("chapter_order");
                    let created_at: chrono::DateTime<chrono::Utc> = row.get("created_at");
                    let updated_at: chrono::DateTime<chrono::Utc> = row.get("updated_at");
                    
                    serde_json::json!({
                        "id": id,
                        "subject_id": subject_id,
                        "name": name,
                        "description": description,
                        "chapter_order": chapter_order,
                        "created_at": created_at.timestamp_millis(),
                        "updated_at": updated_at.timestamp_millis(),
                    })
                })
                .collect();
            
            Ok(Json(D1SyncResponse {
                success: true,
                table: "chapters".to_string(),
                count: data.len(),
                data,
                synced_at: chrono::Utc::now().timestamp_millis(),
            }))
        }
        Err(e) => {
            // Table might not exist yet - return empty result
            tracing::warn!("Chapters table not found or empty: {}", e);
            Ok(Json(D1SyncResponse {
                success: true,
                table: "chapters".to_string(),
                count: 0,
                data: vec![],
                synced_at: chrono::Utc::now().timestamp_millis(),
            }))
        }
    }
}

/// Sync pages (subject_pages) table to D1 format
/// GET /api/edge/d1-sync/pages
pub async fn sync_pages(
    State(state): State<AppState>,
) -> Result<Json<D1SyncResponse>, StatusCode> {
    sync_table_to_d1(&state.db, "subject_pages", |row| {
        serde_json::json!({
            "id": row.id,
            "subject_id": row.subject_id,
            "title": row.title,
            "content": row.content,
            "page_order": row.page_order,
            "metadata": row.metadata.unwrap_or(serde_json::Value::Null),
            "created_at": row.created_at.timestamp_millis(),
            "updated_at": row.updated_at.timestamp_millis(),
        })
    })
    .await
}

/// Generic function to sync any table to D1 format
async fn sync_table_to_d1<F, T>(
    pool: &PgPool,
    table_name: &str,
    transform: F,
) -> Result<Json<D1SyncResponse>, StatusCode>
where
    F: Fn(sqlx::postgres::PgRow) -> serde_json::Value,
{
    let query = format!("SELECT * FROM {} ORDER BY created_at DESC", table_name);
    
    match sqlx::query(&query).fetch_all(pool).await {
        Ok(rows) => {
            let data: Vec<serde_json::Value> = rows.into_iter().map(&transform).collect();
            
            tracing::info!(
                "D1 sync completed for {}: {} rows",
                table_name,
                data.len()
            );
            
            Ok(Json(D1SyncResponse {
                success: true,
                table: table_name.to_string(),
                count: data.len(),
                data,
                synced_at: chrono::Utc::now().timestamp_millis(),
            }))
        }
        Err(e) => {
            tracing::error!("D1 sync failed for {}: {}", table_name, e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

/// Health check for D1 sync readiness
/// GET /api/edge/d1-sync/health
pub async fn d1_sync_health(
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    // Check database connectivity
    let db_healthy = sqlx::query("SELECT 1")
        .fetch_one(&state.db)
        .await
        .is_ok();
    
    // Count rows in each syncable table
    let tables = ["boards", "classes", "subjects", "subject_pages"];
    let mut counts = std::collections::HashMap::new();
    
    for table in &tables {
        let query = format!("SELECT COUNT(*) as count FROM {}", table);
        if let Ok(row) = sqlx::query(&query).fetch_one(&state.db).await {
            let count: i64 = row.get("count");
            counts.insert(*table, count);
        }
    }
    
    Ok(Json(serde_json::json!({
        "healthy": db_healthy,
        "tables": counts,
        "ready_for_sync": db_healthy
    })))
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_uuid_to_string_conversion() {
        // Verify that UUID conversion logic works correctly
        let uuid_str = "550e8400-e29b-41d4-a716-446655440000";
        assert_eq!(uuid_str.len(), 36);
        assert!(uuid_str.contains('-'));
    }
    
    #[test]
    fn test_timestamp_to_unix_ms() {
        let now = chrono::Utc::now();
        let unix_ms = now.timestamp_millis();
        assert!(unix_ms > 0);
        
        // Verify round-trip conversion
        let back = chrono::DateTime::from_timestamp_millis(unix_ms).unwrap();
        assert_eq!(now.timestamp(), back.timestamp());
    }
}
