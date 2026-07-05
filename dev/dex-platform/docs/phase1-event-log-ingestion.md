# Phase 1 - Event Log Ingestion

## Current Design

The Windows agent collects from the classic Windows `System` and `Application`
event logs and sends events to:

```text
POST /eventlogs
```

The API stores events in `dex.event_logs`.

## Important Fields

- `timestamp`: original Windows event occurrence time
- `collected_at`: time the API received the event
- `hostname`: endpoint hostname
- `log_type`: Windows log channel, such as `System` or `Application`
- `record_number`: Windows event log record number used for checkpointing
- `source`: Windows event source
- `event_id`: Windows event ID
- `level`: readable event level, such as `Information`, `Warning`, or `Error`
- `message`: event message text captured from string inserts

## Duplicate Prevention

The agent saves a local checkpoint file:

```text
agent/state/eventlog_checkpoints.json
```

The checkpoint tracks the last successfully sent `record_number` for each log
channel. The checkpoint is updated only after the API accepts the event batch.

If the event log rolls over or is cleared, the agent resets safely to a small
recent backfill window instead of rereading the full log.

## Verification Commands

Check API health:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/
```

Check API routes:

```powershell
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).paths
```

Check recent event rows:

```powershell
docker exec clickhouse clickhouse-client --query "SELECT timestamp, collected_at, hostname, log_type, record_number, source, event_id, level, left(message, 100) AS message FROM dex.event_logs WHERE record_number > 0 ORDER BY collected_at DESC LIMIT 10 FORMAT Vertical"
```

Check for duplicate event records:

```powershell
docker exec clickhouse clickhouse-client --query "SELECT hostname, log_type, record_number, count() AS duplicates FROM dex.event_logs WHERE record_number > 0 GROUP BY hostname, log_type, record_number HAVING duplicates > 1 FORMAT PrettyCompact"
```

