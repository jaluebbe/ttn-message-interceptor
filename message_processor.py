import requests
from device_database import get_latest_session_by_dev_addr


def process_raw_message(raw_message: str, format: str = "hex"):
    return {"raw_message": raw_message}
