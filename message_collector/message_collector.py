#!venv/bin/python3
import socket
import json
import os
import redis
from semtech_udp import process_message as process_udp_message

redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
redis_port = int(os.environ.get("REDIS_PORT", 6379))
redis_connection = redis.Redis(host=redis_host, port=redis_port)

UDP_IP = os.environ.get("COLLECTOR_HOST", "127.0.0.1")
UDP_PORT = int(os.environ.get("COLLECTOR_PORT", 1701))

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
    gps_raw = redis_connection.get("gps_latest")
    gateway_location = json.loads(gps_raw) if gps_raw else None
    for _rxpk in rxpk_list:
        if gateway_eui:
            _rxpk["gateway_eui"] = gateway_eui
        if gateway_location:
            _rxpk["gateway_location"] = gateway_location
        _json_rxpk = json.dumps(_rxpk)
        redis_connection.publish("rxpk", _json_rxpk)
    redis_connection.publish("gateway_push_data", json.dumps(message_data))
