import uuid
from datetime import datetime

import clickhouse_connect
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(
    title="DEX Platform API",
    version="3.0.0",
    description="Digital Experience Monitoring showcase API"
)


# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------

ONLINE_THRESHOLD_SECONDS = 120


# ---------------------------------------------------
# CLICKHOUSE CONNECTION
# ---------------------------------------------------

def get_client():

    return clickhouse_connect.get_client(
        host="clickhouse",
        port=8123
    )


# ---------------------------------------------------
# MODELS
# ---------------------------------------------------

class Device(BaseModel):

    hostname: str
    os: str
    ip: str
    username: str
    cpu_model: str
    total_ram_gb: float
    total_disk_gb: float


class Telemetry(BaseModel):

    hostname: str
    os: str
    ip: str
    cpu: float
    memory: float
    disk: float


class ProcessMetric(BaseModel):

    hostname: str
    pid: int
    process_name: str
    cpu: float
    memory_mb: float
    status: str


class EventLog(BaseModel):

    timestamp: datetime | None = None
    hostname: str
    log_type: str
    record_number: int | None = None
    source: str
    event_id: int
    level: str
    message: str

class RemediationRequest(BaseModel):

    hostname: str
    action: str
    reason: str

# ---------------------------------------------------
# HEALTH SCORE
# ---------------------------------------------------

def calculate_health(cpu, memory, disk):

    score = 100
    reasons = []

    if cpu >= 90:

        score -= 30
        reasons.append("Critical CPU usage")

    elif cpu >= 75:

        score -= 15
        reasons.append("High CPU usage")

    if memory >= 90:

        score -= 30
        reasons.append("Critical memory usage")

    elif memory >= 80:

        score -= 15
        reasons.append("High memory usage")

    if disk >= 90:

        score -= 30
        reasons.append("Critical disk usage")

    elif disk >= 80:

        score -= 15
        reasons.append("High disk usage")

    score = max(score, 0)

    if score >= 80:

        status = "HEALTHY"

    elif score >= 50:

        status = "WARNING"

    else:

        status = "CRITICAL"

    if not reasons:

        reasons.append("Device operating normally")

    return {
        "score": score,
        "status": status,
        "reasons": reasons
    }


# ---------------------------------------------------
# ROOT
# ---------------------------------------------------

@app.get("/")
def root():

    return {
        "status": "running",
        "platform": "DEX Platform",
        "phase": 3,
        "version": "3.0.0"
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
# PROCESS INGESTION
# ---------------------------------------------------

@app.post("/processes")
def processes(processes: list[ProcessMetric]):

    if not processes:

        return {
            "status": "saved",
            "count": 0
        }

    client = get_client()

    collected_at = datetime.now()

    rows = []

    for process in processes:

        rows.append([
            collected_at,
            process.hostname,
            process.pid,
            process.process_name,
            process.cpu,
            process.memory_mb,
            process.status
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
# EVENT LOG INGESTION
# ---------------------------------------------------

@app.post("/eventlogs")
def eventlogs(events: list[EventLog]):

    if not events:

        return {
            "status": "saved",
            "count": 0
        }

    client = get_client()

    collected_at = datetime.now()

    rows = []

    for event in events:

        rows.append([
            event.timestamp or collected_at,
            collected_at,
            event.hostname,
            event.log_type,
            event.record_number or 0,
            event.source,
            event.event_id,
            event.level,
            event.message
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


# ---------------------------------------------------
# DEVICES WITH LATEST TELEMETRY
# ---------------------------------------------------

@app.get("/devices")
def get_devices():

    client = get_client()

    result = client.query(
        """
        SELECT
            hostname,
            argMax(os, timestamp) AS os,
            argMax(ip, timestamp) AS ip,
            argMax(cpu, timestamp) AS cpu,
            argMax(memory, timestamp) AS memory,
            argMax(disk, timestamp) AS disk,
            max(timestamp) AS last_seen,
            dateDiff(
                'second',
                max(timestamp),
                now()
            ) AS age_seconds
        FROM dex.telemetry
        GROUP BY hostname
        ORDER BY hostname
        """
    )

    devices = []

    for row in result.result_rows:

        health = calculate_health(
            float(row[3]),
            float(row[4]),
            float(row[5])
        )

        online = row[7] <= ONLINE_THRESHOLD_SECONDS

        devices.append({
            "hostname": row[0],
            "os": row[1],
            "ip": row[2],
            "cpu": row[3],
            "memory": row[4],
            "disk": row[5],
            "last_seen": row[6],
            "online": online,
            "health_score": health["score"],
            "health_status": (
                health["status"]
                if online
                else "OFFLINE"
            )
        })

    return {
        "count": len(devices),
        "devices": devices
    }


# ---------------------------------------------------
# FLEET SUMMARY
# ---------------------------------------------------

@app.get("/fleet/summary")
def fleet_summary():

    client = get_client()

    result = client.query(
        """
        SELECT
            hostname,
            argMax(cpu, timestamp) AS cpu,
            argMax(memory, timestamp) AS memory,
            argMax(disk, timestamp) AS disk,
            dateDiff(
                'second',
                max(timestamp),
                now()
            ) AS age_seconds
        FROM dex.telemetry
        GROUP BY hostname
        """
    )

    summary = {
        "total_devices": 0,
        "online": 0,
        "offline": 0,
        "healthy": 0,
        "warning": 0,
        "critical": 0
    }

    total_score = 0

    for row in result.result_rows:

        summary["total_devices"] += 1

        online = row[4] <= ONLINE_THRESHOLD_SECONDS

        if not online:

            summary["offline"] += 1
            continue

        summary["online"] += 1

        health = calculate_health(
            float(row[1]),
            float(row[2]),
            float(row[3])
        )

        total_score += health["score"]

        status = health["status"].lower()

        summary[status] += 1

    if summary["online"] > 0:

        average_score = round(
            total_score / summary["online"],
            1
        )

    else:

        average_score = 0

    summary["average_health_score"] = average_score

    return summary


# ---------------------------------------------------
# DEVICE HEALTH
# ---------------------------------------------------

@app.get("/devices/{hostname}/health")
def device_health(hostname: str):

    client = get_client()

    result = client.query(
        """
        SELECT
            hostname,
            argMax(os, timestamp) AS os,
            argMax(ip, timestamp) AS ip,
            argMax(cpu, timestamp) AS cpu,
            argMax(memory, timestamp) AS memory,
            argMax(disk, timestamp) AS disk,
            max(timestamp) AS last_seen,
            dateDiff(
                'second',
                max(timestamp),
                now()
            ) AS age_seconds
        FROM dex.telemetry
        WHERE hostname = %(hostname)s
        GROUP BY hostname
        """,
        parameters={
            "hostname": hostname
        }
    )

    if not result.result_rows:

        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    row = result.result_rows[0]

    health = calculate_health(
        float(row[3]),
        float(row[4]),
        float(row[5])
    )

    online = row[7] <= ONLINE_THRESHOLD_SECONDS

    return {
        "hostname": row[0],
        "os": row[1],
        "ip": row[2],
        "online": online,
        "last_seen": row[6],
        "metrics": {
            "cpu": row[3],
            "memory": row[4],
            "disk": row[5]
        },
        "health_score": (
            health["score"]
            if online
            else 0
        ),
        "health_status": (
            health["status"]
            if online
            else "OFFLINE"
        ),
        "reasons": (
            health["reasons"]
            if online
            else ["Device has not reported recently"]
        )
    }


# ---------------------------------------------------
# TOP PROCESSES
# ---------------------------------------------------

@app.get("/devices/{hostname}/top-processes")
def top_processes(
    hostname: str,
    limit: int = 10
):

    limit = max(1, min(limit, 50))

    client = get_client()

    result = client.query(
        f"""
        SELECT
            timestamp,
            pid,
            process_name,
            cpu,
            memory_mb,
            status
        FROM dex.process_metrics
        WHERE
            hostname = %(hostname)s
            AND process_name != 'System Idle Process'
            AND timestamp = (
                SELECT max(timestamp)
                FROM dex.process_metrics
                WHERE hostname = %(hostname)s
            )
        ORDER BY cpu DESC, memory_mb DESC
        LIMIT {limit}
        """,
        parameters={
            "hostname": hostname
        }
    )

    processes = []

    for row in result.result_rows:

        processes.append({
            "timestamp": row[0],
            "pid": row[1],
            "process_name": row[2],
            "cpu": row[3],
            "memory_mb": row[4],
            "status": row[5]
        })

    return {
        "hostname": hostname,
        "count": len(processes),
        "processes": processes
    }
# ---------------------------------------------------
# DEVICE INSIGHTS
# ---------------------------------------------------

@app.get("/devices/{hostname}/insights")
def device_insights(hostname: str):

    client = get_client()

    telemetry_result = client.query(
        """
        SELECT
            argMax(cpu, timestamp) AS cpu,
            argMax(memory, timestamp) AS memory,
            argMax(disk, timestamp) AS disk,
            max(timestamp) AS last_seen,
            dateDiff(
                'second',
                max(timestamp),
                now()
            ) AS age_seconds
        FROM dex.telemetry
        WHERE hostname = %(hostname)s
        GROUP BY hostname
        """,
        parameters={
            "hostname": hostname
        }
    )

    if not telemetry_result.result_rows:

        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    row = telemetry_result.result_rows[0]

    cpu = float(row[0])
    memory = float(row[1])
    disk = float(row[2])
    last_seen = row[3]
    age_seconds = int(row[4])

    insights = []

    if age_seconds > ONLINE_THRESHOLD_SECONDS:

        insights.append({
            "severity": "CRITICAL",
            "category": "AVAILABILITY",
            "title": "Device offline",
            "description": (
                "Device has not reported telemetry "
                f"for {age_seconds} seconds"
            ),
            "recommended_action": (
                "Check agent service and network connectivity"
            )
        })

    if cpu >= 90:

        insights.append({
            "severity": "CRITICAL",
            "category": "CPU",
            "title": "Critical CPU utilization",
            "description": f"CPU utilization is {cpu:.1f}%",
            "recommended_action": (
                "Review top CPU-consuming processes"
            )
        })

    elif cpu >= 75:

        insights.append({
            "severity": "WARNING",
            "category": "CPU",
            "title": "High CPU utilization",
            "description": f"CPU utilization is {cpu:.1f}%",
            "recommended_action": (
                "Review top CPU-consuming processes"
            )
        })

    if memory >= 90:

        insights.append({
            "severity": "CRITICAL",
            "category": "MEMORY",
            "title": "Critical memory utilization",
            "description": f"Memory utilization is {memory:.1f}%",
            "recommended_action": (
                "Review high-memory processes"
            )
        })

    elif memory >= 80:

        insights.append({
            "severity": "WARNING",
            "category": "MEMORY",
            "title": "High memory utilization",
            "description": f"Memory utilization is {memory:.1f}%",
            "recommended_action": (
                "Review high-memory processes"
            )
        })

    if disk >= 90:

        insights.append({
            "severity": "CRITICAL",
            "category": "DISK",
            "title": "Critical disk utilization",
            "description": f"Disk utilization is {disk:.1f}%",
            "recommended_action": (
                "Clean temporary files and investigate disk growth"
            )
        })

    elif disk >= 80:

        insights.append({
            "severity": "WARNING",
            "category": "DISK",
            "title": "High disk utilization",
            "description": f"Disk utilization is {disk:.1f}%",
            "recommended_action": (
                "Review disk consumption"
            )
        })

    process_result = client.query(
        """
        SELECT
            process_name,
            cpu,
            memory_mb
        FROM dex.process_metrics
        WHERE
            hostname = %(hostname)s
            AND process_name != 'System Idle Process'
            AND timestamp = (
                SELECT max(timestamp)
                FROM dex.process_metrics
                WHERE hostname = %(hostname)s
            )
        ORDER BY cpu DESC
        LIMIT 1
        """,
        parameters={
            "hostname": hostname
        }
    )

    if process_result.result_rows:

        process = process_result.result_rows[0]

        if float(process[1]) >= 50:

            insights.append({
                "severity": "WARNING",
                "category": "PROCESS",
                "title": "High CPU process detected",
                "description": (
                    f"{process[0]} is using "
                    f"{float(process[1]):.1f}% CPU"
                ),
                "recommended_action": (
                    f"Investigate process {process[0]}"
                )
            })

    health = calculate_health(
        cpu,
        memory,
        disk
    )

    return {
        "hostname": hostname,
        "generated_at": datetime.now(),
        "last_seen": last_seen,
        "health_score": (
            health["score"]
            if age_seconds <= ONLINE_THRESHOLD_SECONDS
            else 0
        ),
        "health_status": (
            health["status"]
            if age_seconds <= ONLINE_THRESHOLD_SECONDS
            else "OFFLINE"
        ),
        "insight_count": len(insights),
        "insights": insights
    }


# ---------------------------------------------------
# FLEET INSIGHTS
# ---------------------------------------------------

@app.get("/insights")
def fleet_insights():

    client = get_client()

    result = client.query(
        """
        SELECT
            hostname,
            argMax(cpu, timestamp) AS cpu,
            argMax(memory, timestamp) AS memory,
            argMax(disk, timestamp) AS disk,
            dateDiff(
                'second',
                max(timestamp),
                now()
            ) AS age_seconds
        FROM dex.telemetry
        GROUP BY hostname
        ORDER BY hostname
        """
    )

    insights = []

    for row in result.result_rows:

        hostname = row[0]
        cpu = float(row[1])
        memory = float(row[2])
        disk = float(row[3])
        age_seconds = int(row[4])

        if age_seconds > ONLINE_THRESHOLD_SECONDS:

            insights.append({
                "hostname": hostname,
                "severity": "CRITICAL",
                "category": "AVAILABILITY",
                "title": "Device offline"
            })

        elif cpu >= 75:

            insights.append({
                "hostname": hostname,
                "severity": (
                    "CRITICAL"
                    if cpu >= 90
                    else "WARNING"
                ),
                "category": "CPU",
                "title": f"High CPU: {cpu:.1f}%"
            })

        elif memory >= 80:

            insights.append({
                "hostname": hostname,
                "severity": (
                    "CRITICAL"
                    if memory >= 90
                    else "WARNING"
                ),
                "category": "MEMORY",
                "title": f"High memory: {memory:.1f}%"
            })

        elif disk >= 80:

            insights.append({
                "hostname": hostname,
                "severity": (
                    "CRITICAL"
                    if disk >= 90
                    else "WARNING"
                ),
                "category": "DISK",
                "title": f"High disk: {disk:.1f}%"
            })

    return {
        "count": len(insights),
        "insights": insights
    }
# ---------------------------------------------------
# PHASE 5 - REMEDIATION
# ---------------------------------------------------

ALLOWED_REMEDIATIONS = {
    "CLEAR_TEMP_FILES": (
        "Remove temporary files to recover disk space"
    ),
    "RESTART_AGENT": (
        "Restart the endpoint monitoring agent"
    ),
    "COLLECT_DIAGNOSTICS": (
        "Collect diagnostic information from the endpoint"
    ),
    "NOTIFY_USER": (
        "Notify the user about a detected experience issue"
    )
}


@app.get("/remediations/actions")
def remediation_actions():

    return {
        "count": len(ALLOWED_REMEDIATIONS),
        "actions": [
            {
                "action": action,
                "description": description
            }
            for action, description
            in ALLOWED_REMEDIATIONS.items()
        ]
    }


@app.post("/remediations")
def create_remediation(
    request: RemediationRequest
):

    if request.action not in ALLOWED_REMEDIATIONS:

        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported remediation action",
                "allowed_actions": list(
                    ALLOWED_REMEDIATIONS.keys()
                )
            }
        )

    client = get_client()

    device_result = client.query(
        """
        SELECT count()
        FROM dex.telemetry
        WHERE hostname = %(hostname)s
        """,
        parameters={
            "hostname": request.hostname
        }
    )

    if device_result.result_rows[0][0] == 0:

        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    remediation_id = str(uuid.uuid4())

    now = datetime.now()

    client.insert(
        "dex.remediations",
        [[
            remediation_id,
            now,
            now,
            request.hostname,
            request.action,
            request.reason,
            "PENDING",
            "Waiting for execution"
        ]],
        column_names=[
            "remediation_id",
            "created_at",
            "updated_at",
            "hostname",
            "action",
            "reason",
            "status",
            "result"
        ]
    )

    return {
        "remediation_id": remediation_id,
        "hostname": request.hostname,
        "action": request.action,
        "status": "PENDING",
        "message": "Remediation request created"
    }


@app.post(
    "/remediations/{remediation_id}/execute"
)
def execute_remediation(
    remediation_id: str
):

    client = get_client()

    result = client.query(
        """
        SELECT
            hostname,
            action,
            reason,
            status
        FROM dex.remediations
        WHERE remediation_id = %(remediation_id)s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        parameters={
            "remediation_id": remediation_id
        }
    )

    if not result.result_rows:

        raise HTTPException(
            status_code=404,
            detail="Remediation not found"
        )

    row = result.result_rows[0]

    hostname = row[0]
    action = row[1]
    reason = row[2]
    current_status = row[3]

    if current_status == "COMPLETED":

        return {
            "remediation_id": remediation_id,
            "hostname": hostname,
            "action": action,
            "status": "COMPLETED",
            "message": (
                "Remediation was already completed"
            )
        }

    result_messages = {
        "CLEAR_TEMP_FILES": (
            "Simulation complete: temporary file "
            "cleanup workflow executed"
        ),
        "RESTART_AGENT": (
            "Simulation complete: agent restart "
            "workflow executed"
        ),
        "COLLECT_DIAGNOSTICS": (
            "Simulation complete: diagnostic "
            "collection workflow executed"
        ),
        "NOTIFY_USER": (
            "Simulation complete: user notification "
            "workflow executed"
        )
    }

    execution_result = result_messages[action]

    now = datetime.now()

    client.insert(
        "dex.remediations",
        [[
            remediation_id,
            now,
            now,
            hostname,
            action,
            reason,
            "COMPLETED",
            execution_result
        ]],
        column_names=[
            "remediation_id",
            "created_at",
            "updated_at",
            "hostname",
            "action",
            "reason",
            "status",
            "result"
        ]
    )

    return {
        "remediation_id": remediation_id,
        "hostname": hostname,
        "action": action,
        "status": "COMPLETED",
        "result": execution_result
    }


@app.get("/remediations")
def list_remediations():

    client = get_client()

    result = client.query(
        """
        SELECT
            remediation_id,
            argMax(hostname, updated_at),
            argMax(action, updated_at),
            argMax(reason, updated_at),
            argMax(status, updated_at),
            argMax(result, updated_at),
            max(updated_at)
        FROM dex.remediations
        GROUP BY remediation_id
        ORDER BY max(updated_at) DESC
        LIMIT 100
        """
    )

    remediations = []

    for row in result.result_rows:

        remediations.append({
            "remediation_id": row[0],
            "hostname": row[1],
            "action": row[2],
            "reason": row[3],
            "status": row[4],
            "result": row[5],
            "updated_at": row[6]
        })

    return {
        "count": len(remediations),
        "remediations": remediations
    }


@app.get(
    "/remediations/{remediation_id}"
)
def get_remediation(
    remediation_id: str
):

    client = get_client()

    result = client.query(
        """
        SELECT
            remediation_id,
            hostname,
            action,
            reason,
            status,
            result,
            updated_at
        FROM dex.remediations
        WHERE remediation_id = %(remediation_id)s
        ORDER BY updated_at ASC
        """,
        parameters={
            "remediation_id": remediation_id
        }
    )

    if not result.result_rows:

        raise HTTPException(
            status_code=404,
            detail="Remediation not found"
        )

    history = []

    for row in result.result_rows:

        history.append({
            "status": row[4],
            "result": row[5],
            "timestamp": row[6]
        })

    latest = result.result_rows[-1]

    return {
        "remediation_id": latest[0],
        "hostname": latest[1],
        "action": latest[2],
        "reason": latest[3],
        "status": latest[4],
        "result": latest[5],
        "history": history
    }