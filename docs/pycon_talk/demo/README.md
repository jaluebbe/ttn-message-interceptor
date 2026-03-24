# Talk Demo – LoRaWAN Decoding Example

This folder contains the files used to validate the decoding example shown in the PyConDE talk.

## Files

- **`validate_talk_example.js`** – Node.js script that generates a valid LoRaWAN frame and validates all three decoding steps against the running API
- **`hello_world.js`** – Minimal payload decoder that converts raw bytes to a UTF-8 string (👋🌍)

## Prerequisites

- `decoders_api.js` is running on `localhost:3000` (see `nodejs/` folder)
- `hello_world.js` is copied to `decoders/demo/hello_world.js` in the repository root

```bash
mkdir -p decoders/demo
cp hello_world.js ../../decoders/demo/hello_world.js
```

## Running the validation

Run from the `nodejs/` folder where `lora-packet` is installed:

```bash
cd nodejs/
node ../docs/pycon_talk/demo/validate_talk_example.js
```

Expected output:

```
=== Step 0: Generate LoRaWAN frame ===
Raw frame (hex): 40d4c3b2a100010001fb9125ea0f5d49148752e7fd

=== Step 1: Parse frame (/info/hex) ===
DevAddr: a1b2c3d4
FCnt:    1
FPort:   1
MType:   Unconfirmed Data Up

=== Step 2: Decrypt payload (/decrypt/hex) ===
Decrypted (hex): f09f918bf09f8c8d
Decrypted (utf8): 👋🌍

=== Step 3: Decode payload (/decode/hex) ===
Decoded: {
  "data": {
    "text": "👋🌍"
  },
  "warnings": [],
  "errors": []
}

=== Summary ===
✓ Success: payload decoded to "👋🌍"
```
