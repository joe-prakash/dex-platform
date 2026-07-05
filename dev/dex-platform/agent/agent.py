import requests
import psutil
import socket
import platform
import time
import getpass
import win32evtlog

API_URL = "http://localhost:8000"


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

    print("Device Registered:", response.json())

except Exception as e:

    print("Registration Error:", e)


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

        except:
            pass

    return process_list


# ---------------------------------------------------
# EVENT LOG COLLECTION
# ---------------------------------------------------

def collect_event_logs():

    events = []

    server = 'localhost'

    log_types = ['System', 'Application']

    for log_type in log_types:

        try:

            hand = win32evtlog.OpenEventLog(server, log_type)

            flags = (
                win32evtlog.EVENTLOG_BACKWARDS_READ |
                win32evtlog.EVENTLOG_SEQUENTIAL_READ
            )

            records = win32evtlog.ReadEventLog(
                hand,
                flags,
                0
            )

            for event in records[:20]:

                try:

                    level = str(event.EventType)

                    source = str(event.SourceName)

                    event_id = int(event.EventID & 0xFFFF)

                    message = ""

                    if event.StringInserts:

                        message = " ".join(
                            [str(x) for x in event.StringInserts]
                        )

                    events.append({

                        "hostname": hostname,

                        "log_type": log_type,

                        "source": source,

                        "event_id": event_id,

                        "level": level,

                        "message": message[:1000]
                    })

                except:
                    pass

        except:
            pass

    return events


# ---------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------

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

        print("Telemetry Sent:", response.json())

    except Exception as e:

        print("Telemetry Error:", e)

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

        print("Processes Sent:", response.json())

    except Exception as e:

        print("Process Error:", e)

    # ---------------------------------------------------
    # EVENT LOGS
    # ---------------------------------------------------

    try:

        event_logs = collect_event_logs()

        response = requests.post(
            f"{API_URL}/eventlogs",
            json=event_logs,
            timeout=30
        )

        print("Event Logs Sent:", response.json())

    except Exception as e:

        print("Event Log Error:", e)

    time.sleep(30)