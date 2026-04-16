CREATE TABLE IF NOT EXISTS cobot_telemetry_raw (
    id                  BIGSERIAL PRIMARY KEY,
    event_id            UUID NOT NULL UNIQUE,
    robot_id            TEXT NOT NULL,
    line_id             TEXT NOT NULL,
    station_id          TEXT NOT NULL,
    produced_at         TIMESTAMPTZ NOT NULL,
    payload             JSONB NOT NULL,
    schema_version      TEXT NOT NULL DEFAULT '1.0.0',
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_ip           INET,
    content_type        TEXT,
    request_id          TEXT,
    checksum_sha256     TEXT
);

CREATE TABLE IF NOT EXISTS cobot_telemetry_latest (
    robot_id            TEXT PRIMARY KEY,
    line_id             TEXT NOT NULL,
    station_id          TEXT NOT NULL,
    produced_at         TIMESTAMPTZ NOT NULL,
    payload             JSONB NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cobot_measurements (
    id                  BIGSERIAL PRIMARY KEY,
    event_id            UUID NOT NULL UNIQUE REFERENCES cobot_telemetry_raw(event_id) ON DELETE CASCADE,
    robot_id            TEXT NOT NULL,
    line_id             TEXT NOT NULL,
    station_id          TEXT NOT NULL,
    produced_at         TIMESTAMPTZ NOT NULL,
    cycle_time_ms       INTEGER NOT NULL,
    power_watts         NUMERIC(10,2) NOT NULL,
    program_name        TEXT NOT NULL,
    status              TEXT NOT NULL,
    good_parts          INTEGER,
    reject_parts        INTEGER,
    temperature_c       NUMERIC(8,2),
    vibration_mm_s      NUMERIC(8,3)
);

CREATE TABLE IF NOT EXISTS cobot_aas_sync_status (
    event_id            UUID PRIMARY KEY REFERENCES cobot_telemetry_raw(event_id) ON DELETE CASCADE,
    robot_id            TEXT NOT NULL,
    sync_status         TEXT NOT NULL, -- PENDING, SUCCESS, FAILED
    last_error          TEXT,
    synced_at           TIMESTAMPTZ,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cobot_access_audit (
    id                  BIGSERIAL PRIMARY KEY,
    event_time          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_type          TEXT NOT NULL, -- human, service, partner
    actor_id            TEXT,
    action              TEXT NOT NULL, -- onboard_asset, sync_aas, read_latest, read_history
    target_resource     TEXT NOT NULL,
    result              TEXT NOT NULL, -- success, denied, failed
    correlation_id      TEXT,
    details             JSONB
);

CREATE INDEX IF NOT EXISTS idx_raw_robot_time
ON cobot_telemetry_raw(robot_id, produced_at DESC);

CREATE INDEX IF NOT EXISTS idx_meas_robot_time
ON cobot_measurements(robot_id, produced_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_payload_gin
ON cobot_telemetry_raw USING GIN (payload);