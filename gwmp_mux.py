#!venv/bin/python3
"""
gwmp_mux.py – Semtech GWMP UDP multiplexer

Sits between the sx1302_hal lora_pkt_fwd packet forwarder and the upstream
LoRaWAN network server. Duplicates every PUSH_DATA frame (uplink) to a local
consumer (e.g. message_collector) while maintaining the full upstream path
including downlinks.

For mobile operation, GPS coordinates are read from a Redis channel and
injected into the PUSH_DATA stat frame before forwarding upstream. The local
consumer always receives the original unmodified frame.

Architecture:

    gpsd → your workflow → Redis (GPS_REDIS_CHANNEL)
                                 │
    lora_pkt_fwd                 │
         │ UDP :1700 (localhost)  │
    ┌────▼──────────────────┐    │
    │       gwmp_mux        │←───┘  injects GPS into stat frames
    └────┬──────────────────┘
         ├──→ eu1.cloud.thethings.network:1700  (GPS-enriched stat)
         └──→ localhost:1701                    (original PUSH_DATA)

GWMP packet types handled (protocol v2):
  0x00  PUSH_DATA   fwd → server   stat enriched with GPS; forwarded + copied
  0x01  PUSH_ACK    server → fwd   generated locally; upstream ACK discarded
  0x02  PULL_DATA   fwd → server   forwarded; ACK generated locally
  0x03  PULL_RESP   server → fwd   relayed to forwarder (downlinks)
  0x04  PULL_ACK    server → fwd   generated locally; upstream ACK discarded
  0x05  TX_ACK      fwd → server   forwarded transparently

Configuration via environment variables:
  MUX_LISTEN_PORT       Port to bind (default: 1700)
  MUX_UPSTREAM_HOST     Upstream server hostname (default: eu1.cloud.thethings.network)
  MUX_UPSTREAM_PORT     Upstream server port (default: 1700)
  MUX_CONSUMER_HOST     Local consumer host (default: 127.0.0.1)
  MUX_CONSUMER_PORT     Local consumer port (default: 1701)
  MUX_LOG_LEVEL         Logging level (default: INFO)

  GPS_REDIS_HOST        Redis host for GPS subscription (default: 127.0.0.1)
  GPS_REDIS_PORT        Redis port (default: 6379)
  GPS_REDIS_CHANNEL     Redis channel name (default: gps)
  GPS_MIN_STATUS        Minimum status value for a valid fix (default: 2)
"""

import json
import logging
import os
import redis
import signal
import socket
import sys
import threading
from threading import Lock

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LISTEN_ADDR = (
    "127.0.0.1",
    int(os.environ.get("MUX_LISTEN_PORT", 1700)),
)
UPSTREAM_ADDR = (
    os.environ.get("MUX_UPSTREAM_HOST", "eu1.cloud.thethings.network"),
    int(os.environ.get("MUX_UPSTREAM_PORT", 1700)),
)
CONSUMER_ADDR = (
    os.environ.get("MUX_CONSUMER_HOST", "127.0.0.1"),
    int(os.environ.get("MUX_CONSUMER_PORT", 1701)),
)

LOG_LEVEL = os.environ.get("MUX_LOG_LEVEL", "INFO").upper()

# GPS via Redis
GPS_REDIS_HOST    = os.environ.get("GPS_REDIS_HOST",    "127.0.0.1")
GPS_REDIS_PORT    = int(os.environ.get("GPS_REDIS_PORT", 6379))
GPS_REDIS_CHANNEL = os.environ.get("GPS_REDIS_CHANNEL", "gps")
GPS_MIN_STATUS    = int(os.environ.get("GPS_MIN_STATUS",  2))  # gpsd TPV mode: 2=2D fix, 3=3D fix; only published by gps_poller when mode > 1

# ---------------------------------------------------------------------------
# GWMP constants
# ---------------------------------------------------------------------------

PUSH_DATA       = 0x00
PUSH_ACK        = 0x01
PULL_DATA       = 0x02
PULL_RESP       = 0x03
PULL_ACK        = 0x04
TX_ACK          = 0x05

GWMP_HEADER_LEN = 4   # version(1) + token(2) + type(1)
RECV_BUF        = 4096

# ---------------------------------------------------------------------------

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gwmp-mux")


def _build_ack(packet: bytes, ack_type: int) -> bytes:
    """Build a 4-byte ACK reusing the protocol version and token from *packet*."""
    return bytes([packet[0], packet[1], packet[2], ack_type])


# ---------------------------------------------------------------------------
# GPS provider
# ---------------------------------------------------------------------------

class GpsProvider:
    """
    Subscribes to a Redis channel and caches the latest valid GPS position.

    Expected message fields: lat, lon, alt (MSL metres), status.
    A fix is considered valid when status >= GPS_MIN_STATUS.
    """

    def __init__(self) -> None:
        self._pos: dict | None = None  # {"lat": float, "lon": float, "alt": float}
        self._lock = Lock()
        self._client = redis.Redis(
            host=GPS_REDIS_HOST, port=GPS_REDIS_PORT, decode_responses=True
        )

    def _subscribe_loop(self) -> None:
        pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(GPS_REDIS_CHANNEL)
        log.info("GPS: subscribed to Redis channel '%s'", GPS_REDIS_CHANNEL)
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            gps = json.loads(message["data"])
            if gps.get("mode", 0) >= GPS_MIN_STATUS:
                with self._lock:
                    self._pos = {
                        "lat": float(gps["lat"]),
                        "lon": float(gps["lon"]),
                        "alt": float(gps["alt"]),
                    }
                log.debug("GPS fix: %.6f, %.6f, %.1f m",
                          self._pos["lat"], self._pos["lon"], self._pos["alt"])
            else:
                with self._lock:
                    self._pos = None

    def start(self) -> None:
        t = threading.Thread(target=self._subscribe_loop, daemon=True, name="gps")
        t.start()

    def position(self) -> dict | None:
        """Return latest valid position or None if no fix."""
        with self._lock:
            return self._pos


class GWMPMultiplexer:
    # PUSH_DATA layout: version(1) + token(2) + type(1) + gateway_EUI(8) = 12 bytes before JSON
    PUSH_DATA_HDR_LEN = 12

    def __init__(self, gps: GpsProvider) -> None:
        self._gps = gps
        # Socket the packet forwarder connects to
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(LISTEN_ADDR)

        # Outbound socket for the upstream network server
        self._upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Outbound socket for the local consumer (fire-and-forget)
        self._consumer_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Source endpoint of the forwarder's pull socket – needed to relay
        # PULL_RESP (downlinks) back. Protected by a lock as it is written
        # by one thread and read by another.
        self._pull_addr: tuple | None = None
        self._pull_addr_lock = Lock()

        self._running = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ack(self, dest: tuple, packet: bytes, ack_type: int) -> None:
        try:
            self._listen_sock.sendto(_build_ack(packet, ack_type), dest)
        except OSError as exc:
            log.warning("ACK to %s failed: %s", dest, exc)

    def _forward_upstream(self, data: bytes) -> None:
        try:
            self._upstream_sock.sendto(data, UPSTREAM_ADDR)
        except OSError as exc:
            log.warning("upstream send failed: %s", exc)

    def _forward_consumer(self, data: bytes) -> None:
        try:
            self._consumer_sock.sendto(data, CONSUMER_ADDR)
        except OSError as exc:
            log.debug("consumer send failed (not running?): %s", exc)

    def _inject_gps(self, data: bytes) -> bytes:
        """
        If the PUSH_DATA payload contains a 'stat' object and a valid GPS fix
        is available, overwrite lati/long/alti with current coordinates.
        Returns the original data unchanged if no stat or no fix.
        """
        pos = self._gps.position()
        if pos is None:
            return data
        header = data[:self.PUSH_DATA_HDR_LEN]
        payload = json.loads(data[self.PUSH_DATA_HDR_LEN:])
        if "stat" not in payload:
            return data
        payload["stat"]["lati"] = pos["lat"]
        payload["stat"]["long"] = pos["lon"]
        payload["stat"]["alti"] = int(round(pos["alt"]))
        return header + json.dumps(payload, separators=(",", ":")).encode()

    # ------------------------------------------------------------------
    # Thread: packets from lora_pkt_fwd
    # ------------------------------------------------------------------

    def _from_forwarder(self) -> None:
        while self._running:
            try:
                data, addr = self._listen_sock.recvfrom(RECV_BUF)
            except OSError:
                break
            if len(data) < GWMP_HEADER_LEN:
                continue

            pkt_type = data[3]

            if pkt_type == PUSH_DATA:
                self._ack(addr, data, PUSH_ACK)            # immediate local ACK
                self._forward_upstream(self._inject_gps(data))  # GPS-enriched to TTN
                self._forward_consumer(data)                # original to local app
                log.debug("PUSH_DATA %s → upstream + consumer", addr)

            elif pkt_type == PULL_DATA:
                with self._pull_addr_lock:
                    self._pull_addr = addr
                self._ack(addr, data, PULL_ACK)        # immediate local ACK
                self._forward_upstream(data)            # keepalive to TTN
                log.debug("PULL_DATA %s → upstream", addr)

            elif pkt_type == TX_ACK:
                self._forward_upstream(data)
                log.debug("TX_ACK %s → upstream", addr)

            else:
                log.warning("unexpected type 0x%02x from forwarder %s", pkt_type, addr)

    # ------------------------------------------------------------------
    # Thread: packets from upstream network server
    # ------------------------------------------------------------------

    def _from_upstream(self) -> None:
        while self._running:
            try:
                data, addr = self._upstream_sock.recvfrom(RECV_BUF)
            except OSError:
                break
            if len(data) < GWMP_HEADER_LEN:
                continue

            pkt_type = data[3]

            if pkt_type in (PUSH_ACK, PULL_ACK):
                # Already ACK'd locally – discard to avoid duplicate ACKs
                pass

            elif pkt_type == PULL_RESP:
                # Downlink command from TTN – must reach the forwarder
                with self._pull_addr_lock:
                    pull_addr = self._pull_addr
                if pull_addr:
                    try:
                        self._listen_sock.sendto(data, pull_addr)
                        log.debug("PULL_RESP relayed to forwarder %s", pull_addr)
                    except OSError as exc:
                        log.warning("PULL_RESP relay failed: %s", exc)
                else:
                    log.warning("PULL_RESP received but forwarder pull address unknown")

            else:
                log.warning("unexpected type 0x%02x from upstream %s", pkt_type, addr)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        log.info("gwmp-mux started")
        log.info("  listen   : %s:%d", *LISTEN_ADDR)
        log.info("  upstream : %s:%d", *UPSTREAM_ADDR)
        log.info("  consumer : %s:%d", *CONSUMER_ADDR)
        log.info("  GPS      : redis %s:%d channel '%s'",
                 GPS_REDIS_HOST, GPS_REDIS_PORT, GPS_REDIS_CHANNEL)

        t1 = threading.Thread(target=self._from_forwarder, daemon=True, name="from-fwd")
        t2 = threading.Thread(target=self._from_upstream,  daemon=True, name="from-upstream")
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def stop(self) -> None:
        log.info("gwmp-mux stopping")
        self._running = False
        for s in (self._listen_sock, self._upstream_sock, self._consumer_sock):
            try:
                s.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------

def main() -> None:
    gps = GpsProvider()
    gps.start()
    mux = GWMPMultiplexer(gps)

    def _handle_signal(sig, _frame):
        mux.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    mux.run()


if __name__ == "__main__":
    main()
