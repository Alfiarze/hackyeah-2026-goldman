-- Requests per minute per agent / principal / gateway (budgets.rate_limits). One row per scope and minute.
CREATE TABLE IF NOT EXISTS rate_counters (
    scope   TEXT NOT NULL,
    bucket  TIMESTAMPTZ NOT NULL,
    n       INT NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, bucket)
);
-- circuit breaker: recent blocked decisions of one task
CREATE INDEX IF NOT EXISTS audit_task_block_idx ON audit_events (task_id, ts) WHERE action = 'BLOCK';
