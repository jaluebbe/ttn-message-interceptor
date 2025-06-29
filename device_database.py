#!/usr/bin/python3
import sqlite3
from pathlib import Path

DB_FILE = "ttn_device_sessions.db"
DECODERS_FOLDER = Path("decoders")


def get_latest_session_by_dev_addr(dev_addr):
    query = """
        SELECT dev_eui, application_id, device_id, started_at, dev_addr,
            app_s_key, nwk_s_key, up_formatter
        FROM device_sessions
        WHERE dev_addr = ?
        ORDER BY started_at DESC
        LIMIT 1
    """
    db_path = f"file:{DB_FILE}?mode=ro"
    with sqlite3.connect(db_path, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, (dev_addr,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_latest_sessions():
    query = """
        SELECT dev_eui, application_id, device_id, started_at, dev_addr,
            app_s_key, nwk_s_key, up_formatter
        FROM device_sessions
        WHERE started_at IN (
            SELECT MAX(started_at)
            FROM device_sessions
            GROUP BY dev_addr
        )
        ORDER BY dev_addr
    """
    db_path = f"file:{DB_FILE}?mode=ro"
    with sqlite3.connect(db_path, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def create_decoder_files():
    latest_sessions = get_latest_sessions()
    for _session in latest_sessions:
        application_id = _session["application_id"]
        device_id = _session["device_id"]
        up_formatter = _session["up_formatter"]
        if not up_formatter or "function decodeUplink" not in up_formatter:
            continue
        app_folder = DECODERS_FOLDER / application_id
        app_folder.mkdir(parents=True, exist_ok=True)
        file_path = app_folder / f"{device_id}.js"
        if "module.exports = { decodeUplink };" not in up_formatter:
            up_formatter += "\nmodule.exports = { decodeUplink };"
        with file_path.open("w") as file:
            file.write(up_formatter)


if __name__ == "__main__":
    create_decoder_files()
