# ttn-message-interceptor

Decode and process LoRaWAN messages directly at the gateway, in parallel with
forwarding them to The Things Network (TTN).

## Architecture

```
SX1302 CoreCell (SPI)
        │
  lora_pkt_fwd              builds from: github.com/Lora-net/sx1302_hal
        │ UDP :1700
   gwmp_mux.py               duplicates uplink frames, injects GPS into stat
        │                           ▲
        │                   gps_poller.py  gpsd → Redis "gps_latest" key
        │
        ├──→ eu1.cloud.thethings.network:1700  (TTN, GPS-enriched stat)
        └──→ localhost:1701
                │
      message_collector       UDP listener → Redis pub/sub
                │
           Redis pub/sub
                │
      message_handler.py      decrypts + decodes → lorawan_messages (SQLite)
                │
           messages.db (SQLite)
                │             ┌── ttn_storage_fetcher.py  (TTN Storage → SQLite)
                │             └── reprocess_messages.py   (hourly retry cron)
                │
      message_api.py          FastAPI read-only REST API :8080
```

**Supporting services:**

- `decoders_api.js` (Node.js) – runs device-specific JavaScript payload decoders, called by `message_processor.py`
- `request_ttn_devices.py` / `device_database.py` – fetch TTN device sessions and generate decoder files (daily cron)

## Repository Layout

```
gateway/
  global_conf.json              lora_pkt_fwd config (points to gwmp_mux)
etc/
  systemd/system/               all systemd service files
  cron.d/ttn_storage_fetcher    every-20-min cron for TTN Storage sync
  cron.daily/update_ttn_devices daily cron for device session + decoder refresh
nodejs/
  decoders_api.js               Node.js payload decoder API
routers/
  ttn_messages.py               FastAPI router: GPS + sensor endpoints (SQLite)
  location.py                   FastAPI router: gateway location (Redis)
gwmp_mux.py                     Semtech GWMP UDP multiplexer with GPS injection
gps_poller.py                   gpsd → Redis
message_collector/              UDP listener → Redis publisher
message_handler.py              Redis subscriber → decrypt/decode → SQLite
message_processor.py            LoRaWAN frame decryptor + payload decoder
message_database.py             SQLite schema, indexes, migrations
message_api.py                  FastAPI app entry point
reprocess_messages.py           Retry decoding of undecoded gateway messages
request_ttn_devices.py          Fetch TTN device sessions via API
device_database.py              Generate decoder files from device sessions
ttn_storage_fetcher.py          Mirror TTN Storage Integration → SQLite
```

---

## Installation

All steps below assume a fresh Raspberry Pi OS Bookworm installation.
Steps 1–3 run as a **sudo-capable user**. Steps 4–7 run as **ttnuser**.
Steps 8–10 return to the **sudo-capable user**.

---

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y git make gcc gpsd gpsd-clients chrony redis \
                    python3 python3-pip python3-venv nodejs anacron
```

Enable SPI:

```bash
sudo raspi-config nonint do_spi 0
```

---

### 2. Create the application user

A single `ttnuser` runs all components. It needs SPI and GPIO access for
the packet forwarder:

```bash
sudo useradd --create-home ttnuser
sudo usermod -aG spi,gpio,i2c ttnuser
```

---

### 3. Build and install the packet forwarder binary

> The sx1302_hal is only used for building the binary. All deployment
> configuration lives in this repository.

```bash
git clone https://github.com/Lora-net/sx1302_hal.git
cd sx1302_hal && make clean all && cd ..

sudo mkdir -p /opt/lora_pkt_fwd
sudo cp sx1302_hal/packet_forwarder/lora_pkt_fwd /opt/lora_pkt_fwd/
sudo chown -R ttnuser:ttnuser /opt/lora_pkt_fwd
sudo chmod 750 /opt/lora_pkt_fwd/lora_pkt_fwd
```

---

### 4. Switch to ttnuser

```bash
sudo su - ttnuser
```

---

### 5. Clone the repository and set up Python environment

```bash
git clone https://github.com/jaluebbe/ttn-message-interceptor.git
cd ttn-message-interceptor
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt
```

---

### 6. Configure

**Gateway EUI** – retrieve it from the hardware and note it down:

```bash
ip link show | grep 'link/ether'
```

The EUI is the MAC address with `fffe` inserted in the middle (e.g. `aa:bb:cc:dd:ee:ff` → `aabbccddffeeff`).

Edit `gateway/global_conf.json` and replace `YOUR_GATEWAY_EUI` with the actual value, then copy to the system location. Return to the sudo user for this:

```bash
exit  # back to sudo user
sudo mkdir -p /etc/opt/lora_pkt_fwd
sudo cp /home/ttnuser/ttn-message-interceptor/gateway/global_conf.json \
        /etc/opt/lora_pkt_fwd/global_conf.json
sudo cp /home/ttnuser/ttn-message-interceptor/gateway/reset_lgw.sh \
        /opt/lora_pkt_fwd/reset_lgw.sh
sudo chown ttnuser:ttnuser /etc/opt/lora_pkt_fwd/global_conf.json \
                           /opt/lora_pkt_fwd/reset_lgw.sh
sudo su - ttnuser
cd ttn-message-interceptor
```

> `reset_lgw.sh` must reside in the same directory as the `lora_pkt_fwd` binary.

**TTN credentials** – create a `.env` file with your TTN API token:

```bash
echo 'TTN_TOKEN=your_token_here' > .env
chmod 600 .env
```

The token needs at least read access to applications, devices and their session keys.

To also mirror messages received by **remote gateways** via TTN Storage Integration, add the application IDs:

```bash
echo 'TTN_STORAGE_APPLICATIONS=my-app-1,my-app-2' >> .env
```

**Device sessions and decoders** – fetch all device sessions and generate the decoder files:

```bash
venv/bin/python3 request_ttn_devices.py
venv/bin/python3 device_database.py
```

**Database** – initialise the SQLite database (creates tables, indexes, enables WAL):

```bash
venv/bin/python3 message_database.py
```

**TTN Storage** – run an initial fetch of all historical messages:

```bash
venv/bin/python3 ttn_storage_fetcher.py
```

**Cron jobs** – add two jobs to ttnuser's crontab for ongoing syncing and hourly reprocessing of undecoded messages:

```bash
crontab -e
```

Add:

```
*/20 * * * * cd /home/ttnuser/ttn-message-interceptor && TTN_STORAGE_LAST=25m venv/bin/python3 ttn_storage_fetcher.py
0 * * * *    cd /home/ttnuser/ttn-message-interceptor && venv/bin/python3 reprocess_messages.py >> /home/ttnuser/reprocess_messages.log 2>&1
```

The 20-minute fetch keeps messages near real-time and stays within TTN's rate limit of 10 requests per 60 s.
`reprocess_messages.py` only writes to the log when at least one message was updated or an HTTP error occurred.

**GPS time synchronisation** – configure chrony to use the GPS PPS signal.
Exit to the sudo user and edit `/etc/chrony/chrony.conf`:

```bash
exit  # back to sudo user
```

Add to `/etc/chrony/chrony.conf`:

```
makestep 1 -1
refclock SHM 0 offset 0.2 refid GPS
```

```bash
sudo systemctl restart chrony
```

Verify with `chronyc sources` – the GPS row's `Reach` value should be above zero after a fix is acquired.

---

### 7. Install the daily device refresh cron

As the sudo user:

```bash
sudo cp /home/ttnuser/ttn-message-interceptor/etc/cron.daily/update_ttn_devices \
        /etc/cron.daily/update_ttn_devices
sudo chmod 755 /etc/cron.daily/update_ttn_devices
```

This fetches the full 44 h TTN Storage history and refreshes device sessions once per day, even if the Pi was offline (anacron).

---

### 8. Install and enable systemd services

```bash
sudo cp /home/ttnuser/ttn-message-interceptor/etc/systemd/system/*.service \
        /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable gwmp_mux lora_pkt_fwd gps_poller \
                      decoders_api message_collector \
                      message_handler ttn_message_api
```

---

### 9. Start services

`lora_pkt_fwd` depends on `gwmp_mux` via `Requires=`; systemd enforces the order automatically.

```bash
sudo systemctl start gwmp_mux gps_poller lora_pkt_fwd \
                     decoders_api message_collector \
                     message_handler ttn_message_api
```

---

### 10. Verify

```bash
sudo systemctl status gwmp_mux lora_pkt_fwd message_handler ttn_message_api
```

A healthy startup shows in the logs:

```
gwmp_mux: listen 127.0.0.1:1700 | upstream eu1.cloud.thethings.network:1700 | consumer 127.0.0.1:1701
lora_pkt_fwd: [main] concentrator started, packet can now be received
lora_pkt_fwd: [down] PULL_ACK received in XX ms
```

The API is reachable at `http://<pi-hostname>:8080/docs`.

---

## Management

| Action | Command |
|---|---|
| Status overview | `sudo systemctl status gwmp_mux lora_pkt_fwd message_handler ttn_message_api` |
| Live logs | `journalctl -u gwmp_mux -u lora_pkt_fwd -f` |
| Restart forwarder | `sudo systemctl restart lora_pkt_fwd` |
| Restart API | `sudo systemctl restart ttn_message_api` |
| Update gateway config | edit `gateway/global_conf.json`, re-copy to `/etc/opt/lora_pkt_fwd/` |
| Update device sessions | `venv/bin/python3 request_ttn_devices.py && venv/bin/python3 device_database.py` |

## Lightweight deployment (planned)

The processing pipeline (`message_handler`, `message_api`) can also run on a
separate host without a LoRaWAN concentrator, receiving frames from a
commercial Semtech-compatible gateway over UDP. Docker Compose configuration
for this use case will be added later.
