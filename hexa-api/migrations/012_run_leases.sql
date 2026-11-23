ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(255);
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS lease_fence BIGINT NOT NULL DEFAULT 0;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS lease_heartbeat_at TIMESTAMPTZ;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_task_runs_lease_owner ON task_runs (lease_owner);
CREATE INDEX IF NOT EXISTS ix_task_runs_lease_expires_at ON task_runs (lease_expires_at);
