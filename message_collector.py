import socket
import json
import os
import redis
import arrow
from message_database import insert_message
from semtech_udp import process_message as process_udp_message

if "REDIS_HOST" in os.environ:
    redis_host = os.environ["REDIS_HOST"]
else:
    redis_host = "127.0.0.1"
redis_connection = redis.Redis(host=redis_host)

UDP_IP = "0.0.0.0"
UDP_PORT = 1700

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"Listening for LoRaWAN packets on {UDP_IP}:{UDP_PORT}...")


while True:
    data, addr = sock.recvfrom(4096)
    message_data = process_udp_message(data)
    if message_data.get("header", {}).get("message_type") != 0:
        continue
    gateway_eui = message_data["header"].get("gateway_id")
    json_payload = message_data["payload"]
    rxpk_list = json_payload.get("rxpk", [])
    for _rxpk in rxpk_list:
        if gateway_eui:
            _rxpk["gateway_eui"] = gateway_eui
        _timestamp = arrow.get(_rxpk["time"]).int_timestamp
        _json_rxpk = json.dumps(_rxpk)
        redis_connection.publish("rxpk", _json_rxpk)
        insert_message(_timestamp, gateway_eui, _json_rxpk)
    redis_connection.publish("gateway_push_data", json.dumps(message_data))
