import requests
import psutil
import socket
import platform
import time
import getpass
import win32evtlog
import json
import logging
from pathlib import Path

API_URL = "http://localhost:8000"
BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
EVENT_CHECKPOINT_FILE = STATE_DIR / "eventlog_checkpoints.json"
EVENT_LOG_TYPES = ["System", "Application"]
INITIAL_EVENT_BACKFILL = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

EVENT_LEVELS = {
    0: "Critical",
    1: "Error",
    2: "Warning",
    4: "Information",
    8: "Audit Success",
    16: "Audit Failure",
}


# ---------------------------------------------------
# DEVICE INFORMATION
# ---------------------------------------------------

hostname = socket.gethostname()

os_name = platform.system() + " " + platform.release()

ip = socket.gethostbyname(hostname)

username = getpass.getuser()

cpu_model = platform.processor()

total_ram_gb = round(
    psutil.virtual_memory().total / (1024**3),
    2
)

total_disk_gb = round(
    psutil.disk_usage('/').total / (1024**3),
    2
)


# ---------------------------------------------------
# DEVICE REGISTRATION
# ---------------------------------------------------

device_payload = {

    "hostname": hostname,
    "os": os_name,
    "ip": ip,
    "username": username,
    "cpu_model": cpu_model,
    "total_ram_gb": total_ram_gb,
    "total_disk_gb": total_disk_gb
}

try:

    response = requests.post(
        f"{API_URL}/register",
        json=device_payload,
        timeout=10
    )

    response.raise_for_status()

    logging.info("Device registered: %s", response.json())

except Exception as e:

    logging.error("Registration error: %s", e)


# ---------------------------------------------------
# PROCESS COLLECTION
# ---------------------------------------------------

def collect_processes():

    process_list = []

    for proc in psutil.process_iter([
        'pid',
        'name',
        'cpu_percent',
        'memory_info',
        'status'
    ]):

        try:

            process_list.append({

                "hostname": hostname,

                "pid": proc.info['pid'],

                "process_name": proc.info['name'],

                "cpu": proc.info['cpu_percent'],

                "memory_mb": round(
                    proc.info['memory_info'].rss / (1024 * 1024),
                    2
                ),

                "status": proc.info['status']
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logging.debug("Skipped process during collection: %s", e)

    return process_list


def load_event_checkpoints():

    if not EVENT_CHECKPOINT_FILE.exists():
        return {}

    try:
        with EVENT_CHECKPOINT_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.error("Could not read event checkpoint file: %s", e)
        return {}


def save_event_checkpoints(checkpoints):

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = EVENT_CHECKPOINT_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(checkpoints, f, indent=2, sort_keys=True)

    temp_file.replace(EVENT_CHECKPOINT_FILE)


def event_time_to_text(event_time):

    if hasattr(event_time, "Format"):
        return event_time.Format("%Y-%m-%dT%H:%M:%S")

    return str(event_time)


def event_level_name(event_type):

    return EVENT_LEVELS.get(int(event_type), f"Unknown({event_type})")


def event_to_payload(event, log_type):

    message = ""

    if event.StringInserts:
        message = " ".join([str(x) for x in event.StringInserts])

    return {
        "timestamp": event_time_to_text(event.TimeGenerated),
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

    server = 'localhost'

    for log_type in EVENT_LOG_TYPES:

        try:

            hand = win32evtlog.OpenEventLog(server, log_type)
            oldest_record = win32evtlog.GetOldestEventLogRecord(hand)
            record_count = win32evtlog.GetNumberOfEventLogRecords(hand)
            newest_record = oldest_record + record_count - 1

            last_record = int(checkpoints.get(log_type, 0))

            if record_count == 0:
                next_checkpoints[log_type] = last_record
                win32evtlog.CloseEventLog(hand)
                continue

            if last_record < oldest_record - 1 or last_record > newest_record:
                logging.warning(
                    "%s event log checkpoint reset because of rollover or clear. checkpoint=%s oldest=%s newest=%s",
                    log_type,
                    last_record,
                    oldest_record,
                    newest_record
                )
                last_record = max(oldest_record - 1, newest_record - INITIAL_EVENT_BACKFILL)

            if last_record == 0:
                last_record = max(oldest_record - 1, newest_record - INITIAL_EVENT_BACKFILL)

            flags = (
                win32evtlog.EVENTLOG_FORWARDS_READ |
                win32evtlog.EVENTLOG_SEEK_READ
            )

            offset = last_record + 1
            max_record_seen = last_record

            while offset <= newest_record:

                records = win32evtlog.ReadEventLog(
                    hand,
                    flags,
                    offset
                )

                if not records:
                    break

                for event in records:

                    if int(event.RecordNumber) <= last_record:
                        continue

                    events.append(event_to_payload(event, log_type))
                    max_record_seen = max(max_record_seen, int(event.RecordNumber))
                    offset = int(event.RecordNumber) + 1

            next_checkpoints[log_type] = max_record_seen
            win32evtlog.CloseEventLog(hand)

        except Exception as e:
            logging.error("Event log collection error for %s: %s", log_type, e)

    return events, next_checkpoints


# ---------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------

event_checkpoints = load_event_checkpoints()

while True:

    telemetry_payload = {

        "hostname": hostname,
        "os": os_name,
        "ip": ip,

        "cpu": psutil.cpu_percent(interval=1),

        "memory": psutil.virtual_memory().percent,

        "disk": psutil.disk_usage('/').percent
    }

    # ---------------------------------------------------
    # TELEMETRY
    # ---------------------------------------------------

    try:

        response = requests.post(
            f"{API_URL}/telemetry",
            json=telemetry_payload,
            timeout=10
        )

        response.raise_for_status()

        logging.info("Telemetry sent: %s", response.json())

    except Exception as e:

        logging.error("Telemetry error: %s", e)

    # ---------------------------------------------------
    # PROCESS METRICS
    # ---------------------------------------------------

    try:

        process_data = collect_processes()

        response = requests.post(
            f"{API_URL}/processes",
            json=process_data,
            timeout=30
        )

        response.raise_for_status()

        logging.info("Processes sent: %s", response.json())

    except Exception as e:

        logging.error("Process error: %s", e)

    # ---------------------------------------------------
    # EVENT LOGS
    # ---------------------------------------------------

    try:

        event_logs, next_event_checkpoints = collect_event_logs(event_checkpoints)

        if event_logs:

            response = requests.post(
                f"{API_URL}/eventlogs",
                json=event_logs,
                timeout=30
            )

            response.raise_for_status()
            save_event_checkpoints(next_event_checkpoints)
            event_checkpoints = next_event_checkpoints

            logging.info("Event logs sent: %s", response.json())

        else:

            save_event_checkpoints(next_event_checkpoints)
            event_checkpoints = next_event_checkpoints
            logging.info("No new event logs to send")

    except Exception as e:

        logging.error("Event log error: %s", e)

    time.sleep(30)
