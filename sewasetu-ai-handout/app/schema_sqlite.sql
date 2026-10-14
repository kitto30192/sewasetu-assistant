-- Sewa Setu Old Age Pension Portal - schema
-- NOTE: seed.sql (shipped separately) loads after this and contains the
-- production data. Do not re-run against a live database.

CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_no  TEXT,
    applicant_name  TEXT,
    mobile          TEXT,
    dob             TEXT,
    gender          TEXT,
    marital_status  TEXT,
    husband_name    TEXT,
    husband_employer TEXT,
    village         TEXT,
    block           TEXT,
    bank_account    TEXT,
    ifsc            TEXT,
    doc_path        TEXT,
    status          TEXT DEFAULT 'PENDING',
    submitted_at    TEXT,
    decided_at      TEXT,
    decided_by      TEXT
);

-- Status portal accounts (created at submission time)
CREATE TABLE IF NOT EXISTS portal_users (
    mobile        TEXT PRIMARY KEY,
    password_hash TEXT
);

CREATE TABLE IF NOT EXISTS otps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mobile     TEXT,
    code       TEXT,
    created_at TEXT
);

CREATE INDEX idx_app_mobile ON applications(mobile);
CREATE INDEX idx_app_status ON applications(status);

-- Who did what to an application, and when (submit / withdraw / approve / reject / deemed).
CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    action         TEXT,
    actor          TEXT,
    note           TEXT,
    at             TEXT
);
CREATE INDEX idx_audit_app ON audit_log(application_id);
CREATE INDEX idx_app_status_submitted ON applications(status, submitted_at);

-- OAuth 2.1 authorization server (third-party applications acting for a citizen or officer)
CREATE TABLE IF NOT EXISTS oauth_keys (
    kid         TEXT PRIMARY KEY,
    private_pem TEXT,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS oauth_clients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     TEXT UNIQUE,
    client_name   TEXT,
    redirect_uris TEXT,
    secret_hash   TEXT,
    kind          TEXT,           -- dcr | cimd
    created_at    TEXT,
    fetched_at    TEXT
);
CREATE TABLE IF NOT EXISTS oauth_requests (          -- an authorization in progress (login -> consent)
    id             TEXT PRIMARY KEY,
    params         TEXT,
    subject        TEXT,
    role           TEXT,
    pending_mobile TEXT,
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash      TEXT PRIMARY KEY,
    client_id      TEXT,
    redirect_uri   TEXT,
    scope          TEXT,
    code_challenge TEXT,
    resource       TEXT,
    subject        TEXT,
    role           TEXT,
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (   -- one row per sign-in; expires_at is the session's absolute end
    token_hash  TEXT PRIMARY KEY,
    client_id   TEXT,
    client_name TEXT,
    subject    TEXT,
    role       TEXT,
    scope      TEXT,
    resource   TEXT,
    created_at TEXT,
    expires_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS oauth_program_tokens (     -- admin-issued, long-lived, for unattended use
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    jti        TEXT UNIQUE,
    label      TEXT,
    subject    TEXT,
    audience   TEXT,
    issued_by  TEXT,
    created_at TEXT,
    expires_at TEXT,
    revoked_at TEXT
);
