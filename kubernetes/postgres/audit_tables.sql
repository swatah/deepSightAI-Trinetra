-- Audit logs table with immutability (WORM)
-- T1.5.6: Immutable storage for audit logs

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    resource_name VARCHAR(255),
    timestamp TIMESTAMPTZ NOT NULL,
    outcome VARCHAR(20) NOT NULL,
    ip_address INET,
    user_agent TEXT,
    request_id UUID,
    changes JSONB,
    error_message TEXT,
    metadata JSONB,
    -- Immutability: create timestamp that never changes
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) WITH (autovacuum_enabled = false);

-- Enable Row Level Security (RLS)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Create policy to deny all UPDATE and DELETE operations
-- For UPDATE: restrict based on a condition that is always false
CREATE POLICY audit_deny_update ON audit_logs
    FOR UPDATE
    USING (false);

-- For DELETE: also deny
CREATE POLICY audit_deny_delete ON audit_logs
    FOR DELETE
    USING (false);

-- Optional: also deny UPDATE via trigger with explicit error (defense in depth)
CREATE OR REPLACE FUNCTION audit_prevent_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable and cannot be modified or deleted';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_prevent_update
BEFORE UPDATE ON audit_logs
FOR EACH ROW
EXECUTE FUNCTION audit_prevent_modification();

CREATE TRIGGER audit_prevent_delete
BEFORE DELETE ON audit_logs
FOR EACH ROW
EXECUTE FUNCTION audit_prevent_modification();

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs (resource_type, resource_id);

-- Optional: tablespace encryption handled at storage layer (TDE)
-- This script assumes PostgreSQL TDE is configured at tablespace level.
