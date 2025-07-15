from typing import Literal
import os
import requests
from device_database import get_latest_session_by_dev_addr

decoder_host = os.environ.get("DECODER_HOST", "127.0.0.1")
decoder_port = int(os.environ.get("DECODER_PORT", 3000))
BASE_URL = f"http://{decoder_host}:{decoder_port}"


def extract_nwkid(dev_addr: str) -> int:
    dev_addr_int = int(dev_addr, 16)
    nwkid = (dev_addr_int >> 25) & 0x7F
    return nwkid


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


def process_raw_message(
    raw_message: str,
    message_format: Literal["hex", "base64"] = "hex",
    decrypt_message: bool = True,
    decode_message: bool = True,
    ttn_only: bool = True,
) -> dict:
    message_info = _fetch_message_info(raw_message, message_format)
    dev_addr = message_info.get("devAddr")
    if not dev_addr:
        return message_info
    message_info["nwkId"] = extract_nwkid(dev_addr)
    if ttn_only and message_info["nwkId"] != 19:
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
        decrypted_payload = _decrypt_message(
            message_info["rawMessage"], session_info
        )
        if decrypted_payload:
            message_info["decryptedPayload"] = decrypted_payload

    if decode_message and "decryptedPayload" in message_info:
        decoded_payload = _decode_message(
            message_info["decryptedPayload"], message_info
        )
        if decoded_payload:
            message_info["decodedPayload"] = decoded_payload

    return message_info
