-- MANDATE schema (PostgreSQL 17). Loaded by docker-entrypoint-initdb.d on an empty volume
-- and by the test suite. Change => `make clean && make run`.

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    principal       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    parent_id       TEXT REFERENCES tasks(id),
    profile         TEXT NOT NULL,
    purpose         TEXT,
    mandate         JSONB NOT NULL,
    classification  SMALLINT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    synthetic       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    scope_id          TEXT PRIMARY KEY,
    token_limit       BIGINT NOT NULL,
    spent             BIGINT NOT NULL DEFAULT 0,
    reserved          BIGINT NOT NULL DEFAULT 0,
    calls_limit       BIGINT NOT NULL,
    calls_used        BIGINT NOT NULL DEFAULT 0,
    concurrency_limit INT NOT NULL,
    active_calls      INT NOT NULL DEFAULT 0,
    CHECK (spent >= 0 AND reserved >= 0 AND active_calls >= 0 AND calls_used >= 0)
);

CREATE TABLE IF NOT EXISTS reservations (
    id          TEXT PRIMARY KEY,
    task_id     TEXT,
    scope_ids   TEXT[] NOT NULL,
    amount      BIGINT NOT NULL,
    actual      BIGINT,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | settled | uncertain
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_events (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    task_id         TEXT,
    principal       TEXT,
    kind            TEXT NOT NULL,     -- DECISION | POLICY_CHANGED | POLICY_REJECTED | ADMIN | ...
    channel         TEXT,              -- model | tool | mcp | task | delegate | playground | model_register
    target          TEXT,
    action          TEXT,              -- ALLOW | REDACT | BLOCK
    reason_code     TEXT,
    rule_id         TEXT,
    stage           TEXT,
    policy_version  TEXT,
    latency_ms      DOUBLE PRECISION,
    tool_invoked    BOOLEAN,
    synthetic       BOOLEAN NOT NULL DEFAULT false,
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_ts_idx   ON audit_events (ts);
CREATE INDEX IF NOT EXISTS audit_task_idx ON audit_events (task_id);
CREATE INDEX IF NOT EXISTS audit_rule_idx ON audit_events (rule_id);

-- Audit log is append-only: UPDATE/DELETE are rejected at the database level.
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_no_update ON audit_events;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();

CREATE TABLE IF NOT EXISTS policy_versions (
    seq           BIGSERIAL PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    content       TEXT NOT NULL,
    source        TEXT NOT NULL,      -- file | api | rollback:<seq> | startup
    accepted      BOOLEAN NOT NULL,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_registry (
    name                TEXT PRIMARY KEY,
    definition          JSONB NOT NULL,
    definition_hash     TEXT NOT NULL,
    status              TEXT NOT NULL,          -- approved | quarantined
    pending_definition  JSONB,
    approved_at         TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id              BIGSERIAL PRIMARY KEY,
    case_id         TEXT NOT NULL,
    key             TEXT NOT NULL,
    classification  SMALLINT NOT NULL,
    source_task     TEXT,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trusted document catalog: labels come from here, never from the model or the document itself.
CREATE TABLE IF NOT EXISTS documents (
    path    TEXT PRIMARY KEY,
    client  TEXT,
    label   SMALLINT NOT NULL,     -- 0 PUBLIC, 1 INTERNAL, 2 CONFIDENTIAL, 3 SECRET
    title   TEXT
);
