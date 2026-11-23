CREATE TABLE IF NOT EXISTS command_receipts (
    id BIGSERIAL PRIMARY KEY,
    node_run_id BIGINT NOT NULL REFERENCES node_runs(id),
    command_id VARCHAR(255) NOT NULL UNIQUE,
    request_hash VARCHAR(64) NOT NULL,
    side_effect_state VARCHAR(32) NOT NULL DEFAULT 'not_started',
    reconciliation_required BOOLEAN NOT NULL DEFAULT FALSE,
    response_id VARCHAR(255),
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_command_receipt_node_run UNIQUE (node_run_id)
);
CREATE INDEX IF NOT EXISTS ix_command_receipts_node_run_id ON command_receipts (node_run_id);
CREATE INDEX IF NOT EXISTS ix_command_receipts_request_hash ON command_receipts (request_hash);
