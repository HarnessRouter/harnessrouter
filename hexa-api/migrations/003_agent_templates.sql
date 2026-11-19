CREATE TABLE IF NOT EXISTS agent_templates (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    base VARCHAR(255) NOT NULL,
    default_model VARCHAR(255) NOT NULL,
    system_prompt TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_agent_templates_user_id ON agent_templates (user_id);
