from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import clickhouse_connect

app = FastAPI()


# ---------------------------------------------------
# CLICKHOUSE CONNECTION
# ---------------------------------------------------

def get_client():

    return clickhouse_connect.get_client(
        host="clickhouse",
        port=8123
    )


# ---------------------------------------------------
# DEVICE INVENTORY MODEL
# ---------------------------------------------------

class Device(BaseModel):

    hostname: str
    os: str
    ip: str
    username: str
    cpu_model: str
    total_ram_gb: float
    total_disk_gb: float


# ---------------------------------------------------
# TELEMETRY MODEL
# ---------------------------------------------------

class Telemetry(BaseModel):

    hostname: str
    os: str
    ip: str
    cpu: float
    memory: float
    disk: float


# ---------------------------------------------------
# PROCESS METRICS MODEL
# ---------------------------------------------------

class ProcessMetric(BaseModel):

    hostname: str
    pid: int
    process_name: str
    cpu: float
    memory_mb: float
    status: str


# ---------------------------------------------------
# EVENT LOG MODEL
# ---------------------------------------------------

class EventLog(BaseModel):

    timestamp: datetime | None = None
    hostname: str
    log_type: str
    record_number: int | None = None
    source: str
    event_id: int
    level: str
    message: str


# ---------------------------------------------------
# ROOT ENDPOINT
# ---------------------------------------------------

@app.get("/")
def root():

    return {
        "status": "running"
    }


# ---------------------------------------------------
# DEVICE REGISTRATION
# ---------------------------------------------------

@app.post("/register")
def register(device: Device):

    client = get_client()

    client.insert(
        "dex.devices",
        [[
            device.hostname,
            device.os,
            device.ip,
            device.username,
            device.cpu_model,
            device.total_ram_gb,
            device.total_disk_gb,
            datetime.now()
        ]],
        column_names=[
            "hostname",
            "os",
            "ip",
            "username",
            "cpu_model",
            "total_ram_gb",
            "total_disk_gb",
            "last_seen"
        ]
    )

    return {
        "status": "registered",
        "device": device.hostname
    }


# ---------------------------------------------------
# TELEMETRY INGESTION
# ---------------------------------------------------

@app.post("/telemetry")
def telemetry(data: Telemetry):

    client = get_client()

    client.insert(
        "dex.telemetry",
        [[
            datetime.now(),
            data.hostname,
            data.os,
            data.ip,
            data.cpu,
            data.memory,
            data.disk
        ]],
        column_names=[
            "timestamp",
            "hostname",
            "os",
            "ip",
            "cpu",
            "memory",
            "disk"
        ]
    )

    return {
        "status": "saved",
        "device": data.hostname
    }


# ---------------------------------------------------
# PROCESS MONITORING
# ---------------------------------------------------

@app.post("/processes")
def processes(processes: list[ProcessMetric]):

    client = get_client()

    rows = []

    for p in processes:

        rows.append([
            datetime.now(),
            p.hostname,
            p.pid,
            p.process_name,
            p.cpu,
            p.memory_mb,
            p.status
        ])

    client.insert(
        "dex.process_metrics",
        rows,
        column_names=[
            "timestamp",
            "hostname",
            "pid",
            "process_name",
            "cpu",
            "memory_mb",
            "status"
        ]
    )

    return {
        "status": "saved",
        "count": len(rows)
    }


# ---------------------------------------------------
# EVENT LOG COLLECTION
# ---------------------------------------------------

@app.post("/eventlogs")
def eventlogs(events: list[EventLog]):

    client = get_client()

    rows = []

    for e in events:

        rows.append([
            e.timestamp or datetime.now(),
            datetime.now(),
            e.hostname,
            e.log_type,
            e.record_number or 0,
            e.source,
            e.event_id,
            e.level,
            e.message
        ])

    client.insert(
        "dex.event_logs",
        rows,
        column_names=[
            "timestamp",
            "collected_at",
            "hostname",
            "log_type",
            "record_number",
            "source",
            "event_id",
            "level",
            "message"
        ]
    )

    return {
        "status": "saved",
        "count": len(rows)
    }
