-- Migration 001: Initial schema for Neural Mesh Core

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgvector for vector embeddings (if available)
CREATE EXTENSION IF NOT EXISTS vector;

-- Boards table (e.g., CBSE, ICSE, State Boards)
CREATE TABLE IF NOT EXISTS boards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Classes/Grades table
CREATE TABLE IF NOT EXISTS classes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    board_id UUID REFERENCES boards(id) ON DELETE CASCADE,
    grade_level INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(board_id, grade_level)
);

-- Subjects table
CREATE TABLE IF NOT EXISTS subjects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    board_id UUID REFERENCES boards(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Subject Pages (lessons/content)
CREATE TABLE IF NOT EXISTS subject_pages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    page_order INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Staff Users table
CREATE TABLE IF NOT EXISTS staff_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'staff',
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- OTP Records table
CREATE TABLE IF NOT EXISTS otp_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone VARCHAR(20) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    is_used BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Documents table for RAG
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768), -- Adjust dimension based on embedding model
    metadata JSONB,
    document_type VARCHAR(50) NOT NULL,
    source_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Graph Edges table for knowledge graph
CREATE TABLE IF NOT EXISTS graph_edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL,
    target_id UUID NOT NULL,
    edge_type VARCHAR(50) NOT NULL,
    weight FLOAT DEFAULT 1.0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_classes_board_id ON classes(board_id);
CREATE INDEX IF NOT EXISTS idx_subjects_board_class ON subjects(board_id, class_id);
CREATE INDEX IF NOT EXISTS idx_subject_pages_subject_id ON subject_pages(subject_id);
CREATE INDEX IF NOT EXISTS idx_staff_users_phone ON staff_users(phone);
CREATE INDEX IF NOT EXISTS idx_otp_records_phone ON otp_records(phone);
CREATE INDEX IF NOT EXISTS idx_otp_records_expires ON otp_records(expires_at);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id);

-- Vector similarity index (if pgvector is available)
CREATE INDEX IF NOT EXISTS idx_documents_embedding 
ON documents USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Insert default admin user (for testing)
INSERT INTO staff_users (phone, name, role, is_active)
VALUES ('+1234567890', 'System Admin', 'admin', true)
ON CONFLICT (phone) DO NOTHING;
