CREATE TABLE IF NOT EXISTS run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES task_runs(id),
    node_run_id BIGINT NULL REFERENCES node_runs(id),
    event_type VARCHAR(64) NOT NULL,
    event_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_run_events_run_id_id ON run_events (run_id, id);
CREATE INDEX IF NOT EXISTS ix_run_events_node_run_id ON run_events (node_run_id);
