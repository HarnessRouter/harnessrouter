CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT,
    title VARCHAR(255) NOT NULL DEFAULT '未命名任务',
    description TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    current_revision INTEGER NOT NULL DEFAULT 0,
    current_result_json TEXT NOT NULL DEFAULT '{}',
    input_text TEXT NOT NULL DEFAULT '',
    archived_status VARCHAR(32)
);
CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id);
CREATE INDEX IF NOT EXISTS ix_tasks_workspace_id ON tasks (workspace_id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS current_revision_id BIGINT;

CREATE TABLE IF NOT EXISTS workflow_revisions (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    revision INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    CONSTRAINT uq_workflow_revision_task_revision UNIQUE (task_id, revision)
);
CREATE INDEX IF NOT EXISTS ix_workflow_revisions_task_id ON workflow_revisions (task_id);
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_current_revision;
ALTER TABLE tasks ADD CONSTRAINT fk_tasks_current_revision FOREIGN KEY (current_revision_id) REFERENCES workflow_revisions(id);

CREATE TABLE IF NOT EXISTS task_runs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    workflow_revision INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    kind VARCHAR(32) NOT NULL DEFAULT 'normal',
    idempotency_key VARCHAR(255),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    request_hash VARCHAR(64) NOT NULL DEFAULT '',
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    target_node VARCHAR(255),
    superseded_by BIGINT,
    CONSTRAINT uq_task_run_key UNIQUE (task_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_task_runs_task_id ON task_runs (task_id);
CREATE INDEX IF NOT EXISTS ix_task_runs_status ON task_runs (status);
CREATE INDEX IF NOT EXISTS ix_task_runs_idempotency_key ON task_runs (idempotency_key);
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS workflow_revision_id BIGINT;
ALTER TABLE task_runs DROP CONSTRAINT IF EXISTS fk_task_runs_workflow_revision;
ALTER TABLE task_runs ADD CONSTRAINT fk_task_runs_workflow_revision FOREIGN KEY (workflow_revision_id) REFERENCES workflow_revisions(id);

CREATE TABLE IF NOT EXISTS node_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    node_id VARCHAR(255) NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'idle',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT,
    error_code VARCHAR(64),
    response_id VARCHAR(255),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_node_runs_run_id ON node_runs (run_id);
CREATE INDEX IF NOT EXISTS ix_node_runs_node_id ON node_runs (node_id);

CREATE TABLE IF NOT EXISTS run_decisions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    node_id VARCHAR(255) NOT NULL,
    input_refs_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_run_decisions_run_id ON run_decisions (run_id);

CREATE TABLE IF NOT EXISTS task_commands (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    key VARCHAR(255) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    response_json TEXT NOT NULL,
    CONSTRAINT uq_task_command_key UNIQUE (task_id, key)
);
CREATE INDEX IF NOT EXISTS ix_task_commands_task_id ON task_commands (task_id);

CREATE TABLE IF NOT EXISTS task_templates (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT,
    title VARCHAR(255) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_task_templates_workspace_id ON task_templates (workspace_id);

CREATE TABLE IF NOT EXISTS template_versions (
    id BIGSERIAL PRIMARY KEY,
    template_id BIGINT NOT NULL,
    version INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    CONSTRAINT uq_template_version UNIQUE (template_id, version)
);
CREATE INDEX IF NOT EXISTS ix_template_versions_template_id ON template_versions (template_id);

UPDATE tasks
SET current_revision_id = revisions.id
FROM workflow_revisions revisions
WHERE revisions.task_id = tasks.id
  AND revisions.revision = tasks.current_revision
  AND tasks.current_revision_id IS NULL;

UPDATE task_runs
SET workflow_revision_id = revisions.id
FROM workflow_revisions revisions
WHERE revisions.task_id = task_runs.task_id
  AND revisions.revision = task_runs.workflow_revision
  AND task_runs.workflow_revision_id IS NULL;
