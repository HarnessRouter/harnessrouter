CREATE TABLE IF NOT EXISTS task_artifacts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT,
    task_id BIGINT NOT NULL,
    run_id BIGINT NOT NULL,
    node_run_id BIGINT NOT NULL,
    gateway_file_id VARCHAR(255) NOT NULL,
    gateway_container_id VARCHAR(255) NOT NULL,
    filename TEXT NOT NULL,
    media_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
    bytes INTEGER NOT NULL DEFAULT 0,
    cleanup_status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_task_artifacts_user_id ON task_artifacts (user_id);
CREATE INDEX IF NOT EXISTS ix_task_artifacts_workspace_id ON task_artifacts (workspace_id);
CREATE INDEX IF NOT EXISTS ix_task_artifacts_task_id ON task_artifacts (task_id);
CREATE INDEX IF NOT EXISTS ix_task_artifacts_run_id ON task_artifacts (run_id);
CREATE INDEX IF NOT EXISTS ix_task_artifacts_node_run_id ON task_artifacts (node_run_id);
