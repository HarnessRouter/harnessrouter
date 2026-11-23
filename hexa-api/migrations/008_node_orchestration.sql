ALTER TABLE node_runs ADD COLUMN IF NOT EXISTS execution_kind VARCHAR(32) NOT NULL DEFAULT 'node';
ALTER TABLE node_runs ADD COLUMN IF NOT EXISTS foreach_index INTEGER;
CREATE INDEX IF NOT EXISTS ix_node_runs_foreach_index ON node_runs (run_id, node_id, foreach_index);
