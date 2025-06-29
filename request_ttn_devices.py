#!/usr/bin/python3
import sqlite3
import requests
import os
from dotenv import load_dotenv

load_dotenv()
bearer_token = os.getenv("TTN_TOKEN")
if not bearer_token:
    raise ValueError(
        "Bearer token not found. Please set TTN_TOKEN in the .env file."
    )

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {bearer_token}"})
API_URL = "https://eu1.cloud.thethings.network/api/v3"
DB_FILE = "ttn_device_sessions.db"


def initialize_database():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_sessions (
                dev_eui TEXT NOT NULL,
                application_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                dev_addr TEXT NOT NULL,
                app_s_key TEXT,
                nwk_s_key TEXT,
                up_formatter TEXT,
                PRIMARY KEY (dev_eui, started_at)
            )
        """
        )


def store_device_session_in_db(
    dev_eui,
    application_id,
    device_id,
    started_at,
    dev_addr,
    app_s_key,
    nwk_s_key,
    up_formatter,
):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT up_formatter FROM device_sessions
            WHERE dev_eui = ? AND started_at = ?
            """,
            (dev_eui, started_at),
        )
        result = cursor.fetchone()
        if result is not None and result[0] == up_formatter:
            return
        cursor.execute(
            """
            INSERT OR REPLACE INTO device_sessions (dev_eui, application_id,
                device_id, started_at, dev_addr, app_s_key, nwk_s_key,
                up_formatter)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                dev_eui,
                application_id,
                device_id,
                started_at,
                dev_addr,
                app_s_key,
                nwk_s_key,
                up_formatter,
            ),
        )


def list_applications(session):
    url = f"{API_URL}/applications?field_mask=name"
    response = session.get(url)
    response.raise_for_status()
    return response.json()["applications"]


def list_application_devices(session, application_id: str):
    url = f"{API_URL}/applications/{application_id}/devices"
    response = session.get(url)
    response.raise_for_status()
    return response.json()["end_devices"]


def request_application_formatters(session, application_id: str):
    url = f"{API_URL}/as/applications/{application_id}/link"
    response = session.get(url, params={"field_mask": "default_formatters"})
    response.raise_for_status()
    return response.json().get("default_formatters")


def request_app_device_data(session, application_id, device_id):
    url = f"{API_URL}/as/applications/{application_id}/devices/{device_id}"
    response = session.get(url, params={"field_mask": "session,formatters"})
    response.raise_for_status()
    return response.json()


def request_device_keys(session, application_id, device_id):
    url = f"{API_URL}/ns/applications/{application_id}/devices/{device_id}"
    response = session.get(url, params={"field_mask": "session"})
    response.raise_for_status()
    return response.json()


initialize_database()

applications = list_applications(session)
application_ids = [
    _application["ids"]["application_id"] for _application in applications
]
for _application_id in application_ids:
    devices = list_application_devices(session, _application_id)
    _device_ids = [
        {
            "device_id": _device["ids"]["device_id"],
            "application_id": _device["ids"]["application_ids"][
                "application_id"
            ],
        }
        for _device in devices
    ]
    _app_formatters = request_application_formatters(session, _application_id)
    for _device in _device_ids:
        _net_device_data = request_device_keys(session, **_device)
        if "session" not in _net_device_data:
            continue
        _app_device_data = request_app_device_data(session, **_device)
        _device_formatters = _app_device_data.get("formatters")
        up_formatter = None
        if (
            _device_formatters is not None
            and _device_formatters.get("up_formatter") == "FORMATTER_JAVASCRIPT"
        ):
            up_formatter = _device_formatters["up_formatter_parameter"]
        elif (
            _app_formatters is not None
            and _app_formatters.get("up_formatter") == "FORMATTER_JAVASCRIPT"
        ):
            up_formatter = _app_formatters["up_formatter_parameter"]
        dev_eui = _net_device_data["ids"]["dev_eui"]
        started_at = _net_device_data["session"]["started_at"]
        dev_addr = _net_device_data["session"]["dev_addr"]
        app_s_key = _app_device_data["session"]["keys"]["app_s_key"]["key"]
        nwk_s_key = _net_device_data["session"]["keys"]["f_nwk_s_int_key"][
            "key"
        ]
        store_device_session_in_db(
            dev_eui,
            _device["application_id"],
            _device["device_id"],
            started_at,
            dev_addr,
            app_s_key,
            nwk_s_key,
            up_formatter,
        )
