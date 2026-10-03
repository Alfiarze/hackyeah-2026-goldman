-- Human approval for high-risk tool calls (policy: approvals). Idempotent: applied on every start.
CREATE TABLE IF NOT EXISTS approvals (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES tasks(id),
    tool         TEXT NOT NULL,
    sink         TEXT,
    args_hash    TEXT NOT NULL,          -- the exact call that was approved, nothing else
    args_preview JSONB NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | denied | used
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ,
    decided_by   TEXT
);
CREATE INDEX IF NOT EXISTS approvals_lookup ON approvals (task_id, tool, args_hash, status);
