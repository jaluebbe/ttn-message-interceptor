import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query

DB_NAME = os.getenv("TTN_DB", "messages.db")

router = APIRouter()

# Persistent read-only connection
_db = sqlite3.connect(
    f"file:{DB_NAME}?mode=ro", uri=True, check_same_thread=False
)
_db.row_factory = sqlite3.Row


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


# GPS latest: fetch best row per device from each source, then pick the newer one.
_GPS_LATEST_SQL = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id, 'storage' AS source,
           latitude_val  AS latitude,
           longitude_val AS longitude
    FROM ttn_storage_messages
    WHERE application_id = ?
      AND latitude_val IS NOT NULL
    GROUP BY device_id
    HAVING MAX(time)
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id, 'gateway' AS source,
           json_extract(payload, '$.decodedPayload.Latitude')  AS latitude,
           json_extract(payload, '$.decodedPayload.Longitude') AS longitude
    FROM lorawan_messages
    WHERE application_id = ?
      AND json_extract(payload, '$.decodedPayload.Latitude') IS NOT NULL
    GROUP BY device_id
    HAVING MAX(timestamp)
"""

_GPS_LATEST_SQL_SINCE = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id, 'storage' AS source,
           latitude_val  AS latitude,
           longitude_val AS longitude
    FROM ttn_storage_messages
    WHERE application_id = ? AND time > ?
      AND latitude_val IS NOT NULL
    GROUP BY device_id
    HAVING MAX(time)
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id, 'gateway' AS source,
           json_extract(payload, '$.decodedPayload.Latitude')  AS latitude,
           json_extract(payload, '$.decodedPayload.Longitude') AS longitude
    FROM lorawan_messages
    WHERE application_id = ? AND timestamp > ?
      AND json_extract(payload, '$.decodedPayload.Latitude') IS NOT NULL
    GROUP BY device_id
    HAVING MAX(timestamp)
"""

_GPS_HISTORY_SQL = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id, 'storage' AS source,
           latitude_val  AS latitude,
           longitude_val AS longitude
    FROM ttn_storage_messages
    WHERE application_id = ? AND device_id = ?
      AND latitude_val IS NOT NULL
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id, 'gateway' AS source,
           json_extract(payload, '$.decodedPayload.Latitude')  AS latitude,
           json_extract(payload, '$.decodedPayload.Longitude') AS longitude
    FROM lorawan_messages
    WHERE application_id = ? AND device_id = ?
      AND json_extract(payload, '$.decodedPayload.Latitude') IS NOT NULL
    ORDER BY time
"""

_GPS_HISTORY_SQL_SINCE = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id, 'storage' AS source,
           latitude_val  AS latitude,
           longitude_val AS longitude
    FROM ttn_storage_messages
    WHERE application_id = ? AND device_id = ? AND time > ?
      AND latitude_val IS NOT NULL
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id, 'gateway' AS source,
           json_extract(payload, '$.decodedPayload.Latitude')  AS latitude,
           json_extract(payload, '$.decodedPayload.Longitude') AS longitude
    FROM lorawan_messages
    WHERE application_id = ? AND device_id = ? AND timestamp > ?
      AND json_extract(payload, '$.decodedPayload.Latitude') IS NOT NULL
    ORDER BY time
"""

# For latest queries: fetch the best row from each source independently,
# then take the newer one. Avoids scanning all rows of both tables.
_SENSOR_LATEST_SQL = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id,
           json_extract(data, '$.uplink_message.decoded_payload.' || ?) AS value
    FROM ttn_storage_messages
    WHERE application_id = ?
      AND json_extract(data, '$.uplink_message.decoded_payload.' || ?) IS NOT NULL
    GROUP BY device_id
    HAVING MAX(time)
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id,
           json_extract(payload, '$.decodedPayload.' || ?) AS value
    FROM lorawan_messages
    WHERE application_id = ?
      AND json_extract(payload, '$.decodedPayload.' || ?) IS NOT NULL
    GROUP BY device_id
    HAVING MAX(timestamp)
"""

_SENSOR_LATEST_SQL_SINCE = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id,
           json_extract(data, '$.uplink_message.decoded_payload.' || ?) AS value
    FROM ttn_storage_messages
    WHERE application_id = ?
      AND time > ?
      AND json_extract(data, '$.uplink_message.decoded_payload.' || ?) IS NOT NULL
    GROUP BY device_id
    HAVING MAX(time)
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id,
           json_extract(payload, '$.decodedPayload.' || ?) AS value
    FROM lorawan_messages
    WHERE application_id = ?
      AND timestamp > ?
      AND json_extract(payload, '$.decodedPayload.' || ?) IS NOT NULL
    GROUP BY device_id
    HAVING MAX(timestamp)
"""

_SENSOR_HISTORY_SQL = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id,
           json_extract(data, '$.uplink_message.decoded_payload.' || ?) AS value
    FROM ttn_storage_messages
    WHERE application_id = ?
      AND json_extract(data, '$.uplink_message.decoded_payload.' || ?) IS NOT NULL
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id,
           json_extract(payload, '$.decodedPayload.' || ?) AS value
    FROM lorawan_messages
    WHERE application_id = ?
      AND json_extract(payload, '$.decodedPayload.' || ?) IS NOT NULL
    ORDER BY device_id, time
"""

_SENSOR_HISTORY_SQL_SINCE = """
    SELECT time,
           strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
           device_id,
           json_extract(data, '$.uplink_message.decoded_payload.' || ?) AS value
    FROM ttn_storage_messages
    WHERE application_id = ?
      AND time > ?
      AND json_extract(data, '$.uplink_message.decoded_payload.' || ?) IS NOT NULL
    UNION ALL
    SELECT timestamp AS time,
           strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch') AS time_utc,
           device_id,
           json_extract(payload, '$.decodedPayload.' || ?) AS value
    FROM lorawan_messages
    WHERE application_id = ?
      AND timestamp > ?
      AND json_extract(payload, '$.decodedPayload.' || ?) IS NOT NULL
    ORDER BY device_id, time
"""


@router.get("/api/gps/latest")
def gps_latest(
    application_id: str = Query(...),
    since: float | None = Query(
        None,
        description="Unix timestamp; only include devices active after this time",
    ),
):
    """Latest position per device as GeoJSON FeatureCollection."""
    if since is not None:
        rows = _db.execute(
            _GPS_LATEST_SQL_SINCE,
            (application_id, since, application_id, since),
        ).fetchall()
    else:
        rows = _db.execute(
            _GPS_LATEST_SQL, (application_id, application_id)
        ).fetchall()
    # UNION ALL may return two rows per device; keep the newer one
    best: dict = {}
    for row in rows:
        dev = row["device_id"]
        if dev not in best or row["time"] > best[dev]["time"]:
            best[dev] = row
    return _feature_collection(best.values())


@router.get("/api/gps/track/{device_id}")
def gps_track(
    device_id: str,
    application_id: str = Query(...),
    since: float | None = Query(
        None, description="Unix timestamp; only return points after this time"
    ),
):
    """Full position history for one device as GeoJSON FeatureCollection."""
    if since is not None:
        rows = _db.execute(
            _GPS_HISTORY_SQL_SINCE,
            (application_id, device_id, since, application_id, device_id, since),
        ).fetchall()
    else:
        rows = _db.execute(
            _GPS_HISTORY_SQL,
            (application_id, device_id, application_id, device_id),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No GPS data found")
    return _feature_collection(rows)


@router.get("/api/sensors/latest")
def sensors_latest(
    application_id: str = Query(...),
    field: str = Query(...),
    since: float | None = Query(
        None,
        description="Unix timestamp; only include devices active after this time",
    ),
):
    """Latest value with timestamp per device: {device_id: {time, time_utc, value}}"""
    if since is not None:
        rows = _db.execute(
            _SENSOR_LATEST_SQL_SINCE,
            (field, application_id, since, field, field, application_id, since, field),
        ).fetchall()
    else:
        rows = _db.execute(
            _SENSOR_LATEST_SQL,
            (field, application_id, field, field, application_id, field),
        ).fetchall()
    # UNION ALL may return two rows per device (one per source); keep the newer one
    best: dict = {}
    for row in rows:
        dev = row["device_id"]
        if dev not in best or row["time"] > best[dev]["time"]:
            best[dev] = {
                "time": row["time"],
                "time_utc": row["time_utc"],
                "value": row["value"],
            }
    return best


@router.get("/api/sensors/timeseries")
def sensors_timeseries(
    application_id: str = Query(...),
    field: str = Query(...),
    since: float | None = Query(
        None, description="Unix timestamp; only return values after this time"
    ),
):
    """Time series per device: {device_id: [{time, time_utc, value}, ...]}"""
    if since is not None:
        sql = _SENSOR_HISTORY_SQL_SINCE
        params = (field, application_id, since, field, field, application_id, since, field)
    else:
        sql = _SENSOR_HISTORY_SQL
        params = (field, application_id, field, field, application_id, field)
    rows = _db.execute(sql, params).fetchall()
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
