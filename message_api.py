#!venv/bin/python3
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Response
from redis import asyncio as aioredis

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
DB_NAME = "messages.db"

app = FastAPI()

# Persistent read-only connection; WAL mode allows concurrent reads alongside writes
_db = sqlite3.connect(
    f"file:{DB_NAME}?mode=ro", uri=True, check_same_thread=False
)
_db.row_factory = sqlite3.Row
_db.execute("PRAGMA journal_mode=WAL")


def _gps_feature(row) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [row["longitude"], row["latitude"]],
        },
        "properties": {
            "device_id": row["device_id"],
            "time": row["time"],
            "time_utc": row["time_utc"],
            "source": row["source"],
        },
    }


def _feature_collection(rows) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [_gps_feature(row) for row in rows],
    }


# all_messages: fast UNION ALL, filter pushdown via indexes – used for latest queries
# messages: deduplicated via ROW_NUMBER() – used for history queries
_GPS_SUBQUERY_LATEST = """
    SELECT time, time_utc, device_id, source,
           json_extract(decoded_payload, '$.Latitude')  AS latitude,
           json_extract(decoded_payload, '$.Longitude') AS longitude
    FROM all_messages
    WHERE application_id = ?
"""

_GPS_SUBQUERY_HISTORY = """
    SELECT time, time_utc, device_id, source,
           json_extract(decoded_payload, '$.Latitude')  AS latitude,
           json_extract(decoded_payload, '$.Longitude') AS longitude
    FROM messages
    WHERE application_id = ? AND device_id = ?
"""


@app.get("/api/gps/latest")
def gps_latest(application_id: str = Query(...)):
    """Latest position per device as GeoJSON FeatureCollection."""
    sql = (
        f"SELECT * FROM ({_GPS_SUBQUERY_LATEST}) WHERE latitude IS NOT NULL"
        " GROUP BY device_id HAVING MAX(time)"
    )
    rows = _db.execute(sql, (application_id,)).fetchall()
    return _feature_collection(rows)


@app.get("/api/gps/track/{device_id}")
def gps_track(device_id: str, application_id: str = Query(...)):
    """Full position history for one device as GeoJSON FeatureCollection."""
    sql = (
        f"SELECT * FROM ({_GPS_SUBQUERY_HISTORY}) WHERE latitude IS NOT NULL"
        " ORDER BY time"
    )
    rows = _db.execute(sql, (application_id, device_id)).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No GPS data found")
    return _feature_collection(rows)


# json_extract evaluated once in subquery; outer WHERE filters NULL cleanly.
_SENSOR_SUBQUERY_LATEST = """
    SELECT time, time_utc, device_id,
           json_extract(decoded_payload, ?) AS value
    FROM all_messages
    WHERE application_id = ?
"""

_SENSOR_SUBQUERY_HISTORY = """
    SELECT time, time_utc, device_id,
           json_extract(decoded_payload, ?) AS value
    FROM messages
    WHERE application_id = ?
"""


@app.get("/api/sensors/timeseries")
def sensors_timeseries(
    application_id: str = Query(...), field: str = Query(...)
):
    """Time series per device: {device_id: [{time, time_utc, value}, ...]}"""
    sql = (
        f"SELECT * FROM ({_SENSOR_SUBQUERY_HISTORY}) WHERE value IS NOT NULL"
        " ORDER BY device_id, time"
    )
    rows = _db.execute(sql, (f"$.{field}", application_id)).fetchall()
    result: dict = {}
    for row in rows:
        result.setdefault(row["device_id"], []).append(
            {
                "time": row["time"],
                "time_utc": row["time_utc"],
                "value": row["value"],
            }
        )
    return result


@app.get("/api/sensors/latest")
def sensors_latest(application_id: str = Query(...), field: str = Query(...)):
    """Latest value with timestamp per device: {device_id: {time, time_utc, value}}"""
    sql = (
        f"SELECT * FROM ({_SENSOR_SUBQUERY_LATEST}) WHERE value IS NOT NULL"
        " GROUP BY device_id HAVING MAX(time)"
    )
    rows = _db.execute(sql, (f"$.{field}", application_id)).fetchall()
    return {
        row["device_id"]: {
            "time": row["time"],
            "time_utc": row["time_utc"],
            "value": row["value"],
        }
        for row in rows
    }


@app.get("/api/location")
async def get_location():
    async with aioredis.Redis(
        host=REDIS_HOST, decode_responses=True
    ) as redis_connection:
        _data = await redis_connection.get("gps_latest")
        if not _data:
            raise HTTPException(status_code=404, detail="no data available")
        return Response(content=_data, media_type="application/json")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
