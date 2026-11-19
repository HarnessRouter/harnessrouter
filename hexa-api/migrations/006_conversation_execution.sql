ALTER TABLE idempotency_requests ADD COLUMN IF NOT EXISTS execution_json TEXT;
