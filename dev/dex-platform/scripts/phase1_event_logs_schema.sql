ALTER TABLE dex.event_logs
    ADD COLUMN IF NOT EXISTS collected_at DateTime DEFAULT timestamp AFTER timestamp;

ALTER TABLE dex.event_logs
    ADD COLUMN IF NOT EXISTS record_number UInt64 DEFAULT 0 AFTER log_type;

