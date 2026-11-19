ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_template_id BIGINT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_template_version_id BIGINT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_template_version INTEGER;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_source_template;
ALTER TABLE tasks ADD CONSTRAINT fk_tasks_source_template FOREIGN KEY (source_template_id) REFERENCES task_templates(id);
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_source_template_version;
ALTER TABLE tasks ADD CONSTRAINT fk_tasks_source_template_version FOREIGN KEY (source_template_version_id) REFERENCES template_versions(id);
