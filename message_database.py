#!venv/bin/python3
import sqlite3

DB_NAME = "messages.db"

_SQL_CREATE_LORAWAN_MESSAGES = """
    CREATE TABLE IF NOT EXISTS lorawan_messages (
        timestamp FLOAT,
        gateway_eui TEXT,
        payload JSON,
        application_id TEXT GENERATED ALWAYS AS (
            json_extract(payload, '$.applicationId')
        ) STORED,
        device_id TEXT GENERATED ALWAYS AS (
            json_extract(payload, '$.deviceId')
        ) STORED,
        PRIMARY KEY (timestamp, gateway_eui)
    )
"""

_SQL_CREATE_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_ttn_storage_app_time
        ON ttn_storage_messages (application_id, time);
    CREATE INDEX IF NOT EXISTS idx_ttn_storage_app_device_time
        ON ttn_storage_messages (application_id, device_id, time);
    CREATE INDEX IF NOT EXISTS idx_lorawan_app_time
        ON lorawan_messages (application_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_lorawan_app_device_time
        ON lorawan_messages (application_id, device_id, timestamp);
"""

_SQL_CREATE_TTN_STORAGE_MESSAGES = """
    CREATE TABLE IF NOT EXISTS ttn_storage_messages (
        time FLOAT PRIMARY KEY,
        application_id TEXT NOT NULL,
        device_id TEXT,
        data JSON
    )
"""

_SQL_CREATE_TTN_MESSAGES = """
    CREATE VIEW ttn_messages AS
    SELECT * FROM (
        SELECT
            time,
            application_id,
            device_id,
            LOWER(json_extract(
                data, '$.end_device_ids.dev_addr'
            )) AS dev_addr,
            CAST(json_extract(
                data, '$.uplink_message.f_cnt'
            ) AS INTEGER) AS f_cnt,
            json_extract(
                data, '$.uplink_message.decoded_payload'
            ) AS decoded_payload
        FROM ttn_storage_messages
    )
    WHERE decoded_payload IS NOT NULL
"""

_SQL_CREATE_GATEWAY_MESSAGES = """
    CREATE VIEW gateway_messages AS
    SELECT * FROM (
        SELECT
            timestamp AS time,
            json_extract(payload, '$.applicationId') AS application_id,
            json_extract(payload, '$.deviceId') AS device_id,
            json_extract(payload, '$.devAddr') AS dev_addr,
            CAST(json_extract(
                payload, '$.fCnt'
            ) AS INTEGER) AS f_cnt,
            json_extract(payload, '$.decodedPayload') AS decoded_payload
        FROM lorawan_messages
    )
    WHERE decoded_payload IS NOT NULL
"""

_SQL_CREATE_MESSAGES = """
    CREATE VIEW messages AS
    WITH combined AS (
        SELECT
            time, application_id, device_id,
            dev_addr, f_cnt, decoded_payload,
            'storage' AS source
        FROM ttn_messages
        UNION ALL
        SELECT
            time, application_id, device_id,
            dev_addr, f_cnt, decoded_payload,
            'gateway' AS source
        FROM gateway_messages
    ),
    ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY dev_addr, f_cnt
                ORDER BY source DESC  -- 'storage' > 'gateway'
            ) AS rn
        FROM combined
    )
    SELECT
        time,
        strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
        application_id,
        device_id,
        dev_addr,
        f_cnt,
        decoded_payload,
        source
    FROM ranked
    WHERE rn = 1
    ORDER BY time
"""


def create_database():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(_SQL_CREATE_LORAWAN_MESSAGES)
        conn.execute(_SQL_CREATE_TTN_STORAGE_MESSAGES)
        for view in (
            "messages",
            "ttn_messages",
            "gateway_messages",
            "ttn_messages_debug",
            "gateway_messages_debug",
        ):
            conn.execute(f"DROP VIEW IF EXISTS {view}")
        conn.execute(_SQL_CREATE_TTN_MESSAGES)
        conn.execute(_SQL_CREATE_GATEWAY_MESSAGES)
        conn.execute(_SQL_CREATE_MESSAGES)
        for statement in _SQL_CREATE_INDEXES.strip().split(";"):
            if statement.strip():
                conn.execute(statement)


def insert_message(timestamp, gateway_eui, payload):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO lorawan_messages (
                timestamp, gateway_eui, payload)
            VALUES (?, ?, ?)
            """,
            (timestamp, gateway_eui, payload),
        )


if __name__ == "__main__":
    create_database()
