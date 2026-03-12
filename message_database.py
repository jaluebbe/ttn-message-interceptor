#!venv/bin/python3
import sqlite3

DB_NAME = "messages.db"


def create_database():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lorawan_messages (
                timestamp FLOAT,
                gateway_eui TEXT,
                payload JSON,
                PRIMARY KEY (timestamp, gateway_eui)
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ttn_storage_messages (
                time FLOAT PRIMARY KEY,
                application_id TEXT NOT NULL,
                device_id TEXT,
                data JSON
            )
            """
        )
        conn.execute("DROP VIEW IF EXISTS messages")
        conn.execute(
            """
            CREATE VIEW messages AS
            WITH combined AS (
                SELECT
                    timestamp AS time,
                    json_extract(payload, '$.applicationId') AS application_id,
                    json_extract(payload, '$.deviceId') AS device_id,
                    CAST(json_extract(payload, '$.fCnt') AS INTEGER) AS f_cnt,
                    CAST(json_extract(payload, '$.fPort') AS INTEGER) AS f_port,
                    gateway_eui,
                    json_extract(payload, '$.decodedPayload') AS decoded_payload,
                    'gateway' AS source
                FROM lorawan_messages
                UNION ALL
                SELECT
                    time,
                    application_id,
                    device_id,
                    CAST(json_extract(data, '$.uplink_message.f_cnt') AS INTEGER) AS f_cnt,
                    CAST(json_extract(data, '$.uplink_message.f_port') AS INTEGER) AS f_port,
                    lower(json_extract(data, '$.uplink_message.rx_metadata[0].gateway_ids.eui')) AS gateway_eui,
                    json_extract(data, '$.uplink_message.decoded_payload') AS decoded_payload,
                    'storage' AS source
                FROM ttn_storage_messages
            ),
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_id, f_cnt
                        ORDER BY
                            -- decoded records win over undecoded ones
                            CASE WHEN decoded_payload IS NULL THEN 1 ELSE 0 END,
                            -- among equally decoded, gateway wins over storage
                            source
                    ) AS rn
                FROM combined
            )
            SELECT time,
                   strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch') AS time_utc,
                   application_id, device_id, f_cnt, f_port,
                   gateway_eui, decoded_payload, source
            FROM ranked
            WHERE rn = 1
              AND decoded_payload IS NOT NULL
              AND device_id IS NOT NULL
              AND application_id IS NOT NULL
            """
        )


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
