import sqlite3

DB_NAME = "lorawan_gateway_messages.db"


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
