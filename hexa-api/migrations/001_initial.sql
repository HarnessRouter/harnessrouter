CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(128) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id BIGSERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    username VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_username ON auth_sessions (username);

CREATE TABLE IF NOT EXISTS app_workspaces (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    gateway_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    selected BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_app_workspaces_user_id ON app_workspaces (user_id);

CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT,
    title VARCHAR(255) NOT NULL DEFAULT '新对话',
    previous_response_id VARCHAR(255),
    agent_id VARCHAR(255) NOT NULL DEFAULT '',
    model VARCHAR(255) NOT NULL DEFAULT '',
    response_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    response_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    idempotency_key VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_id ON conversation_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_idempotency_key ON conversation_messages (idempotency_key);

CREATE TABLE IF NOT EXISTS idempotency_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    key VARCHAR(255) NOT NULL,
    conversation_id BIGINT,
    request_hash VARCHAR(64),
    http_status INTEGER NOT NULL DEFAULT 200,
    response_id VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    response_json TEXT,
    partial_text TEXT NOT NULL DEFAULT '',
    CONSTRAINT uq_idempotency_user_key UNIQUE (user_id, key)
);
CREATE INDEX IF NOT EXISTS ix_idempotency_requests_user_id ON idempotency_requests (user_id);
CREATE INDEX IF NOT EXISTS ix_idempotency_requests_key ON idempotency_requests (key);
CREATE INDEX IF NOT EXISTS ix_idempotency_requests_conversation_id ON idempotency_requests (conversation_id);

CREATE TABLE IF NOT EXISTS conversation_files (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    conversation_id BIGINT,
    gateway_id VARCHAR(255) NOT NULL,
    container_id VARCHAR(255),
    filename TEXT NOT NULL,
    media_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
    bytes INTEGER NOT NULL DEFAULT 0,
    direction VARCHAR(16) NOT NULL DEFAULT 'input'
);
CREATE INDEX IF NOT EXISTS ix_conversation_files_user_id ON conversation_files (user_id);
CREATE INDEX IF NOT EXISTS ix_conversation_files_conversation_id ON conversation_files (conversation_id);


-- Forward-compatible additions for databases initialized by an earlier revision.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_id VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS model VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS response_status VARCHAR(32) NOT NULL DEFAULT 'idle';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS response_error TEXT;
ALTER TABLE idempotency_requests ADD COLUMN IF NOT EXISTS conversation_id BIGINT;
ALTER TABLE idempotency_requests ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64);
ALTER TABLE idempotency_requests ADD COLUMN IF NOT EXISTS http_status INTEGER NOT NULL DEFAULT 200;
ALTER TABLE idempotency_requests ADD COLUMN IF NOT EXISTS partial_text TEXT NOT NULL DEFAULT '';
