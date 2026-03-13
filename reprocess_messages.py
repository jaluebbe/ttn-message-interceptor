#!venv/bin/python3
"""Reprocesses lorawan_messages that were not decoded at time of reception."""

import json
import logging
import sqlite3
from requests import HTTPError
import message_processor

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

DB_NAME = "messages.db"

SELECT_SQL = """
    SELECT timestamp, gateway_eui, payload
    FROM lorawan_messages
    WHERE json_extract(payload, '$.deviceId') IS NULL
"""

UPDATE_SQL = """
    UPDATE lorawan_messages
    SET payload = ?
    WHERE timestamp = ? AND gateway_eui = ?
"""


def reprocess():
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(SELECT_SQL).fetchall()

        updated = 0
        skipped = 0
        for timestamp, gateway_eui, payload_str in rows:
            message_info = json.loads(payload_str)
            try:
                enriched = message_processor.process_message(message_info)
            except HTTPError as e:
                log.warning("HTTP error for timestamp=%s: %s", timestamp, e)
                skipped += 1
                continue

            if enriched.get("deviceId") is None:
                skipped += 1
                continue

            conn.execute(
                UPDATE_SQL, (json.dumps(enriched), timestamp, gateway_eui)
            )
            updated += 1

        conn.commit()
        if updated > 0:
            log.info("Done: %d updated, %d skipped", updated, skipped)


if __name__ == "__main__":
    reprocess()
