import logging
import json
import os
import arrow
import redis
from message_processor import process_raw_message
from message_database import insert_message
from requests import HTTPError

redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
redis_port = int(os.environ.get("REDIS_PORT", 6379))
REDIS_CHANNEL = "rxpk"

redis_client = redis.StrictRedis(
    host=redis_host, port=6379, decode_responses=True
)


def process_packet(packet: dict):
    if "data" in packet:
        _message_received = packet["time"]
        _timestamp = arrow.get(_message_received).timestamp()
        _gateway_eui = packet.get("gateway_eui")
        try:
            _message = process_raw_message(packet["data"], "base64")
        except HTTPError:
            logging.error(f"Problem with: {packet}")
            return
        if _gateway_eui is not None:
            _message["gatewayEui"] = _gateway_eui
        _json_message = json.dumps(_message)
        if _message.get("nwkId") == 19:
            insert_message(_timestamp, _gateway_eui, _json_message)
            redis_client.publish("ttn_messages", _json_message)
        else:
            redis_client.publish("other_messages", _json_message)


pubsub = redis_client.pubsub()
pubsub.subscribe(REDIS_CHANNEL)

print(f"Listening for messages on Redis channel: {REDIS_CHANNEL}")
for message in pubsub.listen():
    if message["type"] == "message":
        process_packet(json.loads(message["data"]))
