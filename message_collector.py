import socket
import json
import os
import time
import redis
from message_database import insert_message
from semtech_udp import process_message as process_udp_message
from message_processor import process_raw_message

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


def handle_message_data(message_data):
    ttn_messages = [
        message
        for rxpk in message_data["payload"].get("rxpk", [])
        if (message := process_raw_message(rxpk["data"]))
        and message.get("nwkId") == 19
    ]
    message_data["ttn_messages"] = ttn_messages
    serialized_message_data = json.dumps(message_data)
    redis_connection.publish("gateway_push_data", serialized_message_data)
    if ttn_messages:
        timestamp = int(time.time())
        gateway_eui = message_data["header"].get("gateway_id", "unknown")
        json_payload = message_data["payload"]
        insert_message(timestamp, gateway_eui, json.dumps(json_payload))
        redis_connection.publish("gateway_ttn_data", serialized_message_data)


while True:
    data, addr = sock.recvfrom(4096)
    message_data = process_udp_message(data)
    if message_data.get("header", {}).get("message_type") != 0:
        continue
    handle_message_data(message_data)
