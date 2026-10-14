-- Auth database schema as created by the code before the access-administration
-- tables were added (users profile columns included). Used to test that an
-- existing database opens unchanged and gains the new tables additively.
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    institution TEXT,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
    ON sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON sessions(user_id);

CREATE TABLE IF NOT EXISTS saved_configurations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    application TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    configuration_json TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_saved_configurations_user
    ON saved_configurations(user_id);

CREATE INDEX IF NOT EXISTS idx_saved_configurations_application
    ON saved_configurations(user_id, application);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    configuration_id TEXT,

    application TEXT NOT NULL,
    name TEXT NOT NULL,
    backend TEXT NOT NULL,
    status TEXT NOT NULL,

    configuration_snapshot_json TEXT NOT NULL,

    job_id TEXT,
    cluster TEXT,
    working_directory TEXT,
    output_directory TEXT,
    log_path TEXT,

    exit_code INTEGER,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',

    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (configuration_id)
        REFERENCES saved_configurations(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_experiments_user
    ON experiments(user_id);

CREATE INDEX IF NOT EXISTS idx_experiments_status
    ON experiments(user_id, status);

CREATE INDEX IF NOT EXISTS idx_experiments_application
    ON experiments(user_id, application);

CREATE INDEX IF NOT EXISTS idx_experiments_created
    ON experiments(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    application TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    UNIQUE(user_id, application)
);

CREATE INDEX IF NOT EXISTS idx_workspaces_user
    ON workspaces(user_id);

CREATE TABLE IF NOT EXISTS user_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,

    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,

    provider_username TEXT,
    provider_email TEXT,
    provider_profile_url TEXT,

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    UNIQUE(provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user
    ON user_identities(user_id);

CREATE INDEX IF NOT EXISTS idx_user_identities_provider
    ON user_identities(provider, provider_subject);

CREATE TABLE IF NOT EXISTS oauth_flows (
    state TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    return_to TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oauth_flows_expires
    ON oauth_flows(expires_at);

CREATE INDEX IF NOT EXISTS idx_oauth_flows_session
    ON oauth_flows(session_id);

CREATE TABLE IF NOT EXISTS experiment_events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    event_type TEXT NOT NULL,
    message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,

    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_experiment_events_experiment
    ON experiment_events(experiment_id, created_at);

CREATE INDEX IF NOT EXISTS idx_experiment_events_user
    ON experiment_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS user_roles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_by TEXT,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (created_by)
        REFERENCES users(id)
        ON DELETE SET NULL,

    UNIQUE(user_id, role)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user
    ON user_roles(user_id);

CREATE INDEX IF NOT EXISTS idx_user_roles_role
    ON user_roles(role);

CREATE TABLE IF NOT EXISTS control_audit_log (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    target_user_id TEXT,
    action TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,

    FOREIGN KEY (actor_user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (target_user_id)
        REFERENCES users(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_control_audit_actor
    ON control_audit_log(actor_user_id);

CREATE INDEX IF NOT EXISTS idx_control_audit_target
    ON control_audit_log(target_user_id);

CREATE INDEX IF NOT EXISTS idx_control_audit_created
    ON control_audit_log(created_at);
ALTER TABLE users ADD COLUMN research_role TEXT;
ALTER TABLE users ADD COLUMN country TEXT;
ALTER TABLE users ADD COLUMN default_application TEXT;
ALTER TABLE users ADD COLUMN default_execution_mode TEXT;
ALTER TABLE users ADD COLUMN updated_at REAL;
