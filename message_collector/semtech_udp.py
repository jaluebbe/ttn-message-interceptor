import json
import struct

MESSAGE_TYPES = {
    0x00: "Push Data",
    0x01: "Push Ack",
    0x02: "Pull Data",
    0x03: "Pull Resp",
    0x04: "Pull Ack",
    0x05: "TX Ack",
}


def parse_header(data: bytes) -> dict:
    """
    Parse the 12-byte Semtech UDP header.

    Args:
        data (bytes): The raw UDP packet (at least 12 bytes).

    Returns:
        dict: Parsed header information.
    """
    if len(data) < 12:
        raise ValueError(
            "Data is too short to contain a valid Semtech UDP header"
        )
    protocol_version, random_token, message_type, gateway_id = struct.unpack(
        ">BHB8s", data[:12]
    )
    gateway_id_hex = gateway_id.hex()
    message_type_desc = MESSAGE_TYPES.get(message_type, "Unknown")
    return {
        "protocol_version": protocol_version,
        "random_token": random_token,
        "message_type": message_type,
        "message_type_desc": message_type_desc,
        "gateway_id": gateway_id_hex,
    }


def process_message(data: bytes):
    header = parse_header(data)
    if header["message_type_desc"] in ["Push Data", "Pull Resp"]:
        try:
            json_payload = json.loads(data[12:])
            return {"header": header, "payload": json_payload}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON payload")
    else:
        return {"header": header}
