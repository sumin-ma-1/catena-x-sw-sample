CREATE TABLE IF NOT EXISTS edc_exchange_metrics (
    id                      BIGSERIAL PRIMARY KEY,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempt_id              UUID NOT NULL UNIQUE,
    asset_id                TEXT NOT NULL,
    provider_protocol_url   TEXT NOT NULL,
    consumer_management_url TEXT NOT NULL,
    result                  TEXT NOT NULL, -- SUCCESS, FAILED
    failure_stage           TEXT,          -- discover, negotiation, transfer, fetch
    contract_negotiation_id TEXT,
    contract_agreement_id   TEXT,
    transfer_process_id     TEXT,
    fetched_status_code     INTEGER,
    duration_ms             INTEGER NOT NULL,
    error_message           TEXT,
    detail                  JSONB
);

CREATE INDEX IF NOT EXISTS idx_edc_exchange_metrics_event_time
ON edc_exchange_metrics(event_time DESC);

CREATE INDEX IF NOT EXISTS idx_edc_exchange_metrics_result
ON edc_exchange_metrics(result, event_time DESC);
