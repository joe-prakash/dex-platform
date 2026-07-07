\# Phase 2 - Endpoint Agent Stabilization



\## Status



Phase 2 implementation and acceptance testing completed on 2026-07-07.



\## Objective



Stabilize the Windows endpoint agent so it can run continuously in the local 10-endpoint DEX lab without crashing during temporary API failures or losing Windows event-log checkpoints.



\## Architecture



The Phase 2 agent remains a single Python process.



It uses:



\- Python

\- psutil

\- requests

\- pywin32 / win32evtlog

\- FastAPI ingestion API

\- ClickHouse

\- Docker Compose

\- Grafana



No new infrastructure was introduced.



\## Configuration



Default configuration:



\- API URL: `http://localhost:8000`

\- Telemetry interval: 30 seconds

\- Process interval: 60 seconds

\- Event-log interval: 30 seconds

\- Inventory interval: 3600 seconds

\- HTTP connect timeout: 5 seconds

\- HTTP read timeout: 30 seconds

\- Maximum retries: 3

\- Backoff base: 2 seconds

\- Process CPU sample interval: 1 second



The API URL can be overridden with the `DEX\_API\_URL` environment variable.



\## Separate Collection Schedules



The Phase 1 global collection loop was replaced with independent monotonic schedules.



Collectors now run at different intervals:



\- Inventory: startup and every 1 hour

\- Telemetry: every 30 seconds

\- Processes: every 60 seconds

\- Event logs: every 30 seconds



A failure in one collector does not terminate the entire agent.



\## HTTP Reliability



The agent uses one reusable `requests.Session`.



All POST operations use a shared HTTP helper with:



\- connect timeout

\- read timeout

\- `raise\_for\_status()`

\- bounded retries

\- exponential backoff

\- structured error logging



Retryable conditions include:



\- connection errors

\- timeouts

\- HTTP 429

\- HTTP 500

\- HTTP 502

\- HTTP 503

\- HTTP 504



Permanent client errors such as HTTP 400 are not blindly retried.



Retry delays are:



\- first retry: 2 seconds

\- second retry: 4 seconds



After three failed attempts, the collector records the failure and the agent continues running.



\## Structured Logging



Phase 1 print statements were replaced with Python logging.



Logs include:



\- timestamp

\- level

\- action

\- hostname

\- result

\- failure reason where appropriate



Normal collector failures do not produce uncontrolled Python tracebacks.



\## Graceful Shutdown



The agent handles Ctrl+C and termination signals.



Verified shutdown behavior:



\- shutdown request is logged

\- the scheduler exits

\- the HTTP session closes

\- the agent-stopped message is logged

\- normal Ctrl+C does not produce a `KeyboardInterrupt` traceback



\## Process CPU Sampling



Phase 1 process CPU values were often zero because psutil CPU counters require two samples.



Phase 2 uses:



1\. prime CPU counters for all accessible processes

2\. wait once for the configured sample interval

3\. read CPU values for all surviving processes



The agent does not sleep separately for every process.



Runtime verification showed multiple processes with non-zero CPU values.



Examples observed in ClickHouse included:



\- vmmemWSL: 38.4

\- MoUsoCoreWorker.exe: 23.9

\- chrome.exe: 14.6



\## Event Log Checkpoint Safety



Phase 1 checkpoint behavior was preserved.



Checkpoints are stored in:



`agent/state/eventlog\_checkpoints.json`



The checkpoint advances only after the API successfully accepts the event batch.



If event submission fails:



\- the checkpoint is not saved

\- the in-memory checkpoint is not advanced

\- events remain eligible for later submission



Runtime outage testing confirmed:



`checkpoint\_not\_advanced=true`



After API recovery, pending events were successfully submitted.



Restart persistence was also verified. The agent resumed from stored record numbers and did not resend the historical event backlog.



\## Empty Event Batches



The agent does not POST an empty event-log batch.



An empty event scan is treated as a normal condition.



\## API Outage Recovery Test



The following test was performed:



1\. Start the agent.

2\. Verify normal inventory, telemetry, process, and event-log submission.

3\. Stop only the `dex-api` container.

4\. Keep ClickHouse and Grafana running.

5\. Observe retries and bounded backoff.

6\. Verify the agent remains running.

7\. Restart `dex-api`.

8\. Verify automatic collection recovery.



Result: PASSED.



The same agent process recovered without restart.



\## Runtime Results



Verified:



\- inventory sent at startup

\- telemetry approximately every 30 seconds

\- processes approximately every 60 seconds

\- event logs independently scheduled

\- inventory not sent every collection cycle

\- process CPU values include meaningful non-zero values

\- temporary API outage does not crash the agent

\- collection resumes after API recovery

\- failed event submission does not advance checkpoints

\- successful event submission advances checkpoints

\- event checkpoints survive agent restart

\- Ctrl+C shuts down cleanly



\## ClickHouse Evidence



Verified tables:



\- `dex.devices`

\- `dex.telemetry`

\- `dex.process\_metrics`

\- `dex.event\_logs`



Process monitoring contained meaningful non-zero CPU values.



Event-log record numbers after restart were consistent with new events only and did not show a historical replay.



\## Automated Tests



Nine automated tests were added using Python `unittest`.



Covered behavior:



1\. Retryable HTTP status is retried.

2\. Permanent HTTP 400 is not retried.

3\. Connection failure does not crash the request path.

4\. Exponential backoff is bounded.

5\. Failed event POST does not advance checkpoint.

6\. Successful event POST advances checkpoint.

7\. Empty event batch is not posted.

8\. Collector intervals are separate.

9\. Retry configuration is bounded.



Test result:



`Ran 9 tests - OK`



\## Known Limitations



\- The scheduler is single-threaded.

\- A longer collector can slightly delay another scheduled collector.

\- Inventory registration still uses the existing Phase 1 database semantics.

\- Device deduplication is deferred to Phase 3.

\- The current agent implementation is Windows-focused because event-log collection uses `win32evtlog`.

\- macOS and Linux collectors are future work.

\- The agent currently runs manually rather than as an operating-system service.

\- Local event buffering beyond Windows event-log checkpoint replay is not yet implemented.



\## Phase 2 Acceptance Verdict



Phase 2 is complete when the final API and ClickHouse regression checks pass and the implementation is committed to Git.

