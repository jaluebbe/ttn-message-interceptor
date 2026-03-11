#!venv/bin/python3
"""
Fetch uplink messages from the TTN Storage Integration API for a list of
applications and store them in a local SQLite database.  This ensures that
messages received by remote gateways remain available locally even during an
internet outage.

Configuration via environment variables (or .env file):
  TTN_TOKEN                  – TTN API key with read access to applications,
                               devices and their stored uplinks.
  TTN_STORAGE_APPLICATIONS   – Comma-separated list of TTN application IDs.
  TTN_API_URL                – Base URL for the TTN API
                               (default: https://eu1.cloud.thethings.network/api/v3)
  TTN_STORAGE_LAST           – Time window to fetch on each run
                               (default: 44h, TTN Storage Integration maximum)
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

bearer_token = os.getenv("TTN_TOKEN")
if not bearer_token:
    raise ValueError(
        "Bearer token not found. Please set TTN_TOKEN in the .env file."
    )

_raw_apps = os.getenv("TTN_STORAGE_APPLICATIONS", "")
APPLICATION_IDS: list[str] = [a.strip() for a in _raw_apps.split(",") if a.strip()]
if not APPLICATION_IDS:
    raise ValueError(
        "No applications configured. "
        "Please set TTN_STORAGE_APPLICATIONS in the .env file."
    )

API_BASE = os.getenv(
    "TTN_API_URL", "https://eu1.cloud.thethings.network/api/v3"
).rstrip("/")
STORAGE_LAST = os.getenv("TTN_STORAGE_LAST", "44h")

DB_NAME = "ttn_storage_messages.db"


def create_database() -> None:
    with sqlite3.connect(DB_NAME) as conn:
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


def _parse_timestamp(received_at: str) -> float:
    return datetime.fromisoformat(
        received_at.rstrip("Z")
    ).replace(tzinfo=timezone.utc).timestamp()


def insert_messages(messages: list[dict[str, Any]], application_id: str) -> int:
    rows = []
    for msg in messages:
        try:
            ts = _parse_timestamp(msg["received_at"])
        except (KeyError, ValueError):
            log.warning("Skipping message with unparseable received_at: %s", msg)
            continue
        device_id = (
            msg.get("end_device_ids", {}).get("device_id")
        )
        rows.append((ts, application_id, device_id, json.dumps(msg)))

    if not rows:
        return 0

    with sqlite3.connect(DB_NAME) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO ttn_storage_messages
                (time, application_id, device_id, data)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def fetch_messages(application_id: str) -> list[dict[str, Any]]:
    url = f"{API_BASE}/as/applications/{application_id}/packages/storage/uplink_message"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "text/event-stream",
    }
    params = {"last": STORAGE_LAST, "order": "-received_at"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return [
            json.loads(line)["result"]
            for line in response.text.splitlines()
            if line.strip()
        ]
    except requests.RequestException:
        log.exception("Failed to fetch messages for application %s", application_id)
        return []


if __name__ == "__main__":
    create_database()
    for app_id in APPLICATION_IDS:
        log.info("Fetching messages for application: %s", app_id)
        messages = fetch_messages(app_id)
        if messages:
            count = insert_messages(messages, app_id)
            log.info("Stored %d messages for %s", count, app_id)
        else:
            log.info("No messages received for %s", app_id)
