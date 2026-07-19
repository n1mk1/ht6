CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    task_version TEXT NOT NULL,
    difficulty_key TEXT NOT NULL DEFAULT '',
    hand_key TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(task_type, task_version, difficulty_key, hand_key)
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    duration_ms INTEGER,
    accuracy_score REAL,
    stability_score REAL,
    accuracy_band TEXT,
    stability_band TEXT,
    score_version TEXT,
    coverage_pct REAL,
    completion_time_seconds REAL,
    mean_dev_mm REAL,
    max_dev_mm REAL,
    rms_dev_mm REAL,
    tremor_rms_deg_s REAL,
    gyro_rms_deg_s REAL,
    peak_angular_velocity_deg_s REAL,
    calibration_valid INTEGER,
    quality_warnings_json TEXT NOT NULL,
    task_json TEXT NOT NULL,
    timing_json TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    percentiles_json TEXT,
    explanation_json TEXT,
    score_definitions_json TEXT,
    artifacts_json TEXT,
    original_payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(session_id, device_id)
);

CREATE TABLE deterministic_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_session_pk INTEGER NOT NULL REFERENCES sessions(id),
    current_session_pk INTEGER NOT NULL REFERENCES sessions(id),
    policy_version TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(reference_session_pk, current_session_pk, policy_version)
);

CREATE TABLE model_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_pk INTEGER NOT NULL UNIQUE REFERENCES sessions(id),
    reference_session_pk INTEGER REFERENCES sessions(id),
    status TEXT NOT NULL,
    adapter TEXT NOT NULL,
    model_version TEXT,
    regression_score REAL,
    regression_flag INTEGER,
    confidence REAL,
    overall_pattern TEXT,
    result_json TEXT,
    error_code TEXT,
    error_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX sessions_user_created_idx ON sessions(user_id, created_at DESC);
CREATE INDEX sessions_task_created_idx ON sessions(task_id, created_at DESC);
CREATE INDEX model_results_status_idx ON model_results(status);

