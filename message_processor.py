from typing import Literal
import requests
from device_database import get_latest_session_by_dev_addr

BASE_URL = "http://localhost:3000"


def _fetch_message_info(
    raw_message: str, message_format: Literal["hex", "base64"]
) -> dict:
    info_url = f"{BASE_URL}/info/{message_format}"
    response = requests.post(info_url, json={"payload": raw_message})
    response.raise_for_status()
    return response.json()


def _fetch_session_info(dev_addr: str) -> dict | None:
    return get_latest_session_by_dev_addr(dev_addr.upper())


def _decrypt_message(raw_message: str, session_info: dict) -> dict | None:
    decrypt_url = f"{BASE_URL}/decrypt/hex"
    response = requests.post(
        decrypt_url,
        json={
            "payload": raw_message,
            "app_s_key": session_info["app_s_key"],
            "nwk_s_key": session_info["nwk_s_key"],
        },
    )
    if response.status_code == 200:
        return response.json()
    return None


def _decode_message(decrypted_payload: str, message_info: dict) -> dict | None:
    decode_url = f"{BASE_URL}/decode/hex"
    response = requests.post(
        decode_url,
        json={
            "payload": decrypted_payload,
            "application": message_info["applicationId"],
            "device": message_info["deviceId"],
            "fPort": message_info["fPort"],
        },
    )
    if response.status_code == 200:
        return response.json()
    return None


def process_raw_message(
    raw_message: str,
    message_format: Literal["hex", "base64"] = "hex",
    decrypt_message: bool = True,
    decode_message: bool = True,
) -> dict:
    message_info = _fetch_message_info(raw_message, message_format)
    dev_addr = message_info.get("devAddr")
    if not dev_addr:
        return message_info

    session_info = _fetch_session_info(dev_addr)
    if not session_info:
        return message_info

    message_info.update(
        {
            "devEui": session_info["dev_eui"],
            "applicationId": session_info["application_id"],
            "deviceId": session_info["device_id"],
        }
    )

    if decrypt_message:
        decrypted_payload = _decrypt_message(raw_message, session_info)
        if decrypted_payload:
            message_info["decryptedPayload"] = decrypted_payload

    if decode_message and "decryptedPayload" in message_info:
        decoded_payload = _decode_message(
            message_info["decryptedPayload"], message_info
        )
        if decoded_payload:
            message_info["decodedPayload"] = decoded_payload

    return message_info
