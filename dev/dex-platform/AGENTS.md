# DEX Platform Project Context

## Project Goal

Build a fully on-premises, open-source Digital Experience Monitoring platform similar to Nexthink.

Long-term target:
- 50,000 endpoints
- Windows, macOS, and Linux
- No paid external infrastructure
- Device monitoring
- Process monitoring
- Event and application log analysis
- Insights and root-cause analysis
- Alerting
- Automated remediation
- ServiceNow ticket creation
- Excel/report exports
- Grafana dashboards

## User Experience Requirement

The project owner is learning development from the beginning.

Work in small, sequential steps:
1. Explain what is being changed.
2. Change only what is necessary.
3. Give exact commands.
4. Verify each stage before moving forward.
5. Do not redesign working components without explaining why.
6. Preserve the existing C:\dex-platform folder.

## Current Local Environment

- Windows 11 25H2
- Docker Desktop 4.77.0
- Docker 29.5.3
- Docker Compose 5.1.4
- Python 3.14.5

## Current Architecture

Windows Endpoint
    |
    v
Python Agent
    |
    v
FastAPI
    |
    v
ClickHouse
    |
    v
Grafana

Everything is currently running locally with Docker Compose except the Python agent, which runs directly on Windows.

## Current Technologies

- Python
- FastAPI
- Pydantic
- requests
- psutil
- pywin32 / win32evtlog
- ClickHouse
- Grafana
- Docker
- Docker Compose
- REST/JSON

## Current Containers

Expected containers:
- clickhouse
- grafana
- dex-api

Expected ports:
- FastAPI: 8000
- Grafana: 3000
- ClickHouse HTTP: 8123
- ClickHouse native: 9000

## Current ClickHouse Database

Database:
- dex

Tables:

### dex.devices

Stores:
- hostname
- os
- ip
- username
- cpu_model
- total_ram_gb
- total_disk_gb
- last_seen

### dex.telemetry

Stores:
- timestamp
- hostname
- os
- ip
- cpu
- memory
- disk

### dex.process_metrics

Stores:
- timestamp
- hostname
- pid
- process_name
- cpu
- memory_mb
- status

### dex.event_logs

Stores:
- timestamp
- hostname
- log_type
- source
- event_id
- level
- message

## Current FastAPI Endpoints

Expected:
- GET /
- POST /register
- POST /telemetry
- POST /processes
- POST /eventlogs

## Current Working Features

Confirmed working:
- Docker Compose
- ClickHouse
- Grafana
- FastAPI
- Device registration
- CPU telemetry
- Memory telemetry
- Disk telemetry
- Process collection
- Process storage in ClickHouse
- Grafana ClickHouse data source
- Initial dashboard

Example process data successfully collected:
- Code.exe
- chrome.exe
- msedge.exe
- svchost.exe
- com.docker.build.exe

## Current Problem

We restarted the lab and are currently trying to complete Windows Event Log ingestion.

The last observed issue was:
- http://localhost:8000/docs could not be reached

Before continuing development:

1. Inspect all files in the repository.
2. Run docker compose ps.
3. Inspect dex-api logs.
4. Determine why FastAPI is unavailable.
5. Restore the existing API without destroying ClickHouse data.
6. Verify GET / works.
7. Verify /docs works.
8. Verify POST /eventlogs exists.
9. Test one manual event log insert.
10. Verify the row in dex.event_logs.
11. Only then debug the Windows agent collector.

## Important Known Bug

The API route is:

POST /eventlogs

An earlier agent version incorrectly called:

POST /event-logs

Ensure both sides use exactly:

/eventlogs

## Development Rules

- Never delete Docker volumes without explicit approval.
- Never delete C:\dex-platform.
- Do not reset the database unless explicitly approved.
- Inspect existing code before replacing files.
- Prefer fixing the current implementation over starting again.
- Back up a file before major rewrites.
- Validate API routes through /docs or /openapi.json.
- Validate every ingestion feature directly in ClickHouse.
- Use open-source and on-premises components only.
- Keep the local implementation simple while preserving a path to 50,000 endpoints.

## Long-Term Enterprise Architecture Direction

The local lab is intentionally simple.

Current:
Endpoint Agent -> FastAPI -> ClickHouse -> Grafana

Future large-scale direction:
Endpoints
-> Load Balancers / API Gateway
-> Durable ingestion queue such as Kafka
-> Ingestion workers
-> ClickHouse cluster
-> Grafana
-> Alert engine
-> Health scoring
-> Remediation engine
-> ServiceNow integration

Do not introduce enterprise-scale components into the local lab until the basic functionality is stable.

## Immediate Task

Continue from the current repository state.

First diagnose why http://localhost:8000/docs is unavailable.

Do not assume the cause. Inspect:
- docker compose configuration
- container status
- API logs
- app.py
- Dockerfile
- requirements.txt

Fix the smallest root cause and verify event log ingestion end-to-end.