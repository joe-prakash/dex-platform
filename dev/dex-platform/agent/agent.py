import getpass
import json
import logging
import os
import platform
import signal
import socket
import time
from pathlib import Path

import psutil
import requests
import win32evtlog


# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------

API_URL = os.getenv("DEX_API_URL", "http://localhost:8000").rstrip("/")

TELEMETRY_INTERVAL_SECONDS = 30
PROCESS_INTERVAL_SECONDS = 60
EVENT_LOG_INTERVAL_SECONDS = 30
INVENTORY_INTERVAL_SECONDS = 3600

HTTP_CONNECT_TIMEOUT_SECONDS = 5
HTTP_READ_TIMEOUT_SECONDS = 30

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2

PROCESS_CPU_SAMPLE_SECONDS = 1

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
EVENT_CHECKPOINT_FILE = STATE_DIR / "eventlog_checkpoints.json"

EVENT_LOG_TYPES = ["System", "Application"]
INITIAL_EVENT_BACKFILL = 20

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


# ---------------------------------------------------
# LOGGING
# ---------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("dex-agent")


# ---------------------------------------------------
# SHUTDOWN CONTROL
# ---------------------------------------------------

shutdown_requested = False


def request_shutdown(signum=None, frame=None):

    global shutdown_requested

    if not shutdown_requested:
        logger.info(
            "shutdown requested hostname=%s signal=%s",
            hostname,
            signum
        )

    shutdown_requested = True


def register_signal_handlers():

    signal.signal(
        signal.SIGINT,
        request_shutdown
    )

    if hasattr(signal, "SIGTERM"):

        signal.signal(
            signal.SIGTERM,
            request_shutdown
        )


# ---------------------------------------------------
# DEVICE INFORMATION
# ---------------------------------------------------

hostname = socket.gethostname()

os_name = f"{platform.system()} {platform.release()}"

username = getpass.getuser()

cpu_model = platform.processor()

total_ram_gb = round(
    psutil.virtual_memory().total / (1024 ** 3),
    2
)

total_disk_gb = round(
    psutil.disk_usage("/").total / (1024 ** 3),
    2
)


def get_local_ip():

    try:

        hostname_ip = socket.gethostbyname(hostname)

        if hostname_ip and not hostname_ip.startswith("127."):
            return hostname_ip

    except OSError as exc:
        logger.warning(
            "hostname IP lookup failed hostname=%s reason=%s",
            hostname,
            exc
        )

    try:

        for address in socket.getaddrinfo(
            hostname,
            None,
            family=socket.AF_INET
        ):

            candidate = address[4][0]

            if candidate and not candidate.startswith("127."):
                return candidate

    except OSError as exc:
        logger.warning(
            "fallback IP lookup failed hostname=%s reason=%s",
            hostname,
            exc
        )

    return "127.0.0.1"


ip = get_local_ip()


# ---------------------------------------------------
# HTTP SESSION
# ---------------------------------------------------

session = requests.Session()


def post_json(endpoint, payload, action):

    url = f"{API_URL}{endpoint}"

    for attempt in range(1, MAX_RETRIES + 1):

        if shutdown_requested:
            return None

        try:

            response = session.post(
                url,
                json=payload,
                timeout=(
                    HTTP_CONNECT_TIMEOUT_SECONDS,
                    HTTP_READ_TIMEOUT_SECONDS
                )
            )

            if response.status_code in RETRYABLE_STATUS_CODES:

                logger.warning(
                    "temporary API failure action=%s status=%s "
                    "attempt=%s/%s",
                    action,
                    response.status_code,
                    attempt,
                    MAX_RETRIES
                )

                if attempt < MAX_RETRIES:
                    wait_with_shutdown(
                        BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    )
                    continue

                response.raise_for_status()

            response.raise_for_status()

            try:
                return response.json()

            except ValueError:
                return {
                    "status": "success",
                    "http_status": response.status_code
                }

        except (
            requests.ConnectionError,
            requests.Timeout
        ) as exc:

            logger.warning(
                "API unavailable action=%s attempt=%s/%s reason=%s",
                action,
                attempt,
                MAX_RETRIES,
                exc
            )

            if attempt < MAX_RETRIES:
                wait_with_shutdown(
                    BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                )
                continue

            logger.error(
                "API request failed action=%s after=%s attempts",
                action,
                MAX_RETRIES
            )

            return None

        except requests.HTTPError as exc:

            status_code = None

            if exc.response is not None:
                status_code = exc.response.status_code

            logger.error(
                "API rejected request action=%s status=%s reason=%s",
                action,
                status_code,
                exc
            )

            return None

        except requests.RequestException as exc:

            logger.error(
                "API request error action=%s reason=%s",
                action,
                exc
            )

            return None

    return None


# ---------------------------------------------------
# WAIT HELPER
# ---------------------------------------------------

def wait_with_shutdown(seconds):

    end_time = time.monotonic() + seconds

    while not shutdown_requested:

        remaining = end_time - time.monotonic()

        if remaining <= 0:
            break

        time.sleep(min(0.5, remaining))


# ---------------------------------------------------
# DEVICE INVENTORY
# ---------------------------------------------------

def build_device_payload():

    return {
        "hostname": hostname,
        "os": os_name,
        "ip": ip,
        "username": username,
        "cpu_model": cpu_model,
        "total_ram_gb": total_ram_gb,
        "total_disk_gb": total_disk_gb
    }


def send_inventory():

    result = post_json(
        "/register",
        build_device_payload(),
        "inventory"
    )

    if result is not None:

        logger.info(
            "inventory sent hostname=%s",
            hostname
        )

        return True

    logger.error(
        "inventory failed hostname=%s",
        hostname
    )

    return False


# ---------------------------------------------------
# TELEMETRY
# ---------------------------------------------------

def collect_telemetry():

    return {
        "hostname": hostname,
        "os": os_name,
        "ip": ip,
        "cpu": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent
    }


def send_telemetry():

    try:

        payload = collect_telemetry()

        result = post_json(
            "/telemetry",
            payload,
            "telemetry"
        )

        if result is not None:

            logger.info(
                "telemetry sent hostname=%s cpu=%s memory=%s disk=%s",
                hostname,
                payload["cpu"],
                payload["memory"],
                payload["disk"]
            )

            return True

        logger.error(
            "telemetry failed hostname=%s",
            hostname
        )

    except Exception as exc:

        logger.exception(
            "telemetry collector error hostname=%s reason=%s",
            hostname,
            exc
        )

    return False


# ---------------------------------------------------
# PROCESS COLLECTION
# ---------------------------------------------------

def collect_processes():

    primed_processes = []

    for proc in psutil.process_iter(["pid", "name"]):

        try:

            proc.cpu_percent(interval=None)
            primed_processes.append(proc)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess
        ):
            continue

    wait_with_shutdown(PROCESS_CPU_SAMPLE_SECONDS)

    process_list = []

    for proc in primed_processes:

        if shutdown_requested:
            break

        try:

            memory_info = proc.memory_info()

            process_list.append({
                "hostname": hostname,
                "pid": proc.pid,
                "process_name": proc.name(),
                "cpu": proc.cpu_percent(interval=None),
                "memory_mb": round(
                    memory_info.rss / (1024 * 1024),
                    2
                ),
                "status": proc.status()
            })

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess
        ):
            continue

    return process_list


def send_processes():

    try:

        process_data = collect_processes()

        if not process_data:

            logger.info(
                "no processes collected hostname=%s",
                hostname
            )

            return True

        result = post_json(
            "/processes",
            process_data,
            "processes"
        )

        if result is not None:

            non_zero_cpu = sum(
                1
                for process in process_data
                if process["cpu"] > 0
            )

            logger.info(
                "processes sent hostname=%s count=%s non_zero_cpu=%s",
                hostname,
                len(process_data),
                non_zero_cpu
            )

            return True

        logger.error(
            "processes failed hostname=%s count=%s",
            hostname,
            len(process_data)
        )

    except Exception as exc:

        logger.exception(
            "process collector error hostname=%s reason=%s",
            hostname,
            exc
        )

    return False


# ---------------------------------------------------
# EVENT LOG CHECKPOINTS
# ---------------------------------------------------

EVENT_LEVELS = {
    0: "Critical",
    1: "Error",
    2: "Warning",
    4: "Information",
    8: "Audit Success",
    16: "Audit Failure",
}


def load_event_checkpoints():

    if not EVENT_CHECKPOINT_FILE.exists():
        return {}

    try:

        with EVENT_CHECKPOINT_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except (OSError, json.JSONDecodeError) as exc:

        logger.error(
            "could not read event checkpoint file path=%s reason=%s",
            EVENT_CHECKPOINT_FILE,
            exc
        )

        return {}


def save_event_checkpoints(checkpoints):

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = EVENT_CHECKPOINT_FILE.with_suffix(".tmp")

    with temp_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            checkpoints,
            file,
            indent=2,
            sort_keys=True
        )

    temp_file.replace(EVENT_CHECKPOINT_FILE)


def event_time_to_text(event_time):

    if hasattr(event_time, "Format"):

        return event_time.Format(
            "%Y-%m-%dT%H:%M:%S"
        )

    return str(event_time)


def event_level_name(event_type):

    return EVENT_LEVELS.get(
        int(event_type),
        f"Unknown({event_type})"
    )


def event_to_payload(event, log_type):

    message = ""

    if event.StringInserts:

        message = " ".join(
            str(value)
            for value in event.StringInserts
        )

    return {
        "timestamp": event_time_to_text(
            event.TimeGenerated
        ),
        "hostname": hostname,
        "log_type": log_type,
        "record_number": int(event.RecordNumber),
        "source": str(event.SourceName),
        "event_id": int(event.EventID & 0xFFFF),
        "level": event_level_name(event.EventType),
        "message": message[:1000]
    }


# ---------------------------------------------------
# EVENT LOG COLLECTION
# ---------------------------------------------------

def collect_event_logs(checkpoints):

    events = []
    next_checkpoints = checkpoints.copy()

    server = "localhost"

    for log_type in EVENT_LOG_TYPES:

        hand = None

        try:

            hand = win32evtlog.OpenEventLog(
                server,
                log_type
            )

            oldest_record = (
                win32evtlog.GetOldestEventLogRecord(hand)
            )

            record_count = (
                win32evtlog.GetNumberOfEventLogRecords(hand)
            )

            if record_count == 0:

                next_checkpoints[log_type] = int(
                    checkpoints.get(log_type, 0)
                )

                continue

            newest_record = (
                oldest_record + record_count - 1
            )

            last_record = int(
                checkpoints.get(log_type, 0)
            )

            if (
                last_record < oldest_record - 1
                or last_record > newest_record
            ):

                logger.warning(
                    "event checkpoint reset log_type=%s "
                    "checkpoint=%s oldest=%s newest=%s",
                    log_type,
                    last_record,
                    oldest_record,
                    newest_record
                )

                last_record = max(
                    oldest_record - 1,
                    newest_record - INITIAL_EVENT_BACKFILL
                )

            if last_record == 0:

                last_record = max(
                    oldest_record - 1,
                    newest_record - INITIAL_EVENT_BACKFILL
                )

            flags = (
                win32evtlog.EVENTLOG_FORWARDS_READ
                | win32evtlog.EVENTLOG_SEEK_READ
            )

            offset = last_record + 1
            max_record_seen = last_record

            while (
                offset <= newest_record
                and not shutdown_requested
            ):

                records = win32evtlog.ReadEventLog(
                    hand,
                    flags,
                    offset
                )

                if not records:
                    break

                for event in records:

                    record_number = int(
                        event.RecordNumber
                    )

                    if record_number <= last_record:
                        continue

                    events.append(
                        event_to_payload(
                            event,
                            log_type
                        )
                    )

                    max_record_seen = max(
                        max_record_seen,
                        record_number
                    )

                    offset = record_number + 1

            next_checkpoints[log_type] = max_record_seen

        except Exception as exc:

            logger.error(
                "event log collection error "
                "hostname=%s log_type=%s reason=%s",
                hostname,
                log_type,
                exc
            )

        finally:

            if hand is not None:

                try:
                    win32evtlog.CloseEventLog(hand)
                except Exception:
                    logger.debug(
                        "event log handle close failed "
                        "log_type=%s",
                        log_type
                    )

    return events, next_checkpoints


def send_event_logs():

    global event_checkpoints

    try:

        event_logs, next_event_checkpoints = (
            collect_event_logs(event_checkpoints)
        )

        if not event_logs:

            save_event_checkpoints(
                next_event_checkpoints
            )

            event_checkpoints = (
                next_event_checkpoints
            )

            logger.debug(
                "no new event logs hostname=%s",
                hostname
            )

            return True

        result = post_json(
            "/eventlogs",
            event_logs,
            "event_logs"
        )

        if result is None:

            logger.error(
                "event logs failed hostname=%s count=%s "
                "checkpoint_not_advanced=true",
                hostname,
                len(event_logs)
            )

            return False

        save_event_checkpoints(
            next_event_checkpoints
        )

        event_checkpoints = (
            next_event_checkpoints
        )

        logger.info(
            "event logs sent hostname=%s count=%s",
            hostname,
            len(event_logs)
        )

        return True

    except Exception as exc:

        logger.exception(
            "event log collector error hostname=%s reason=%s",
            hostname,
            exc
        )

        return False


# ---------------------------------------------------
# SCHEDULER
# ---------------------------------------------------

def run_agent():

    logger.info(
        "agent started hostname=%s api_url=%s",
        hostname,
        API_URL
    )

    send_inventory()

    now = time.monotonic()

    next_inventory_run = (
        now + INVENTORY_INTERVAL_SECONDS
    )

    next_telemetry_run = now

    next_process_run = now

    next_event_log_run = now

    while not shutdown_requested:

        now = time.monotonic()

        if now >= next_telemetry_run:

            send_telemetry()

            next_telemetry_run = (
                time.monotonic()
                + TELEMETRY_INTERVAL_SECONDS
            )

        if (
            not shutdown_requested
            and now >= next_process_run
        ):

            send_processes()

            next_process_run = (
                time.monotonic()
                + PROCESS_INTERVAL_SECONDS
            )

        if (
            not shutdown_requested
            and now >= next_event_log_run
        ):

            send_event_logs()

            next_event_log_run = (
                time.monotonic()
                + EVENT_LOG_INTERVAL_SECONDS
            )

        if (
            not shutdown_requested
            and now >= next_inventory_run
        ):

            send_inventory()

            next_inventory_run = (
                time.monotonic()
                + INVENTORY_INTERVAL_SECONDS
            )

        wait_with_shutdown(0.5)


# ---------------------------------------------------
# STARTUP
# ---------------------------------------------------

event_checkpoints = load_event_checkpoints()


if __name__ == "__main__":

    register_signal_handlers()

    try:

        run_agent()

    finally:

        session.close()

        logger.info(
            "agent stopped hostname=%s",
            hostname
        )