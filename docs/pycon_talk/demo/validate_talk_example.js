#!/usr/bin/env node
/**
 * validate_talk_example.js
 *
 * Validates the LoRaWAN decoding example used in the PyConDE talk.
 * Run from the nodejs/ directory where lora-packet is installed:
 *
 *   node validate_talk_example.js
 *
 * Assumes decoders_api.js is running on localhost:3000.
 */

const lora_packet = require("lora-packet");

const BASE_URL = "http://localhost:3000";

const APP_S_KEY = "2B7E151628AED2A6ABF7158809CF4F3C";
const NWK_S_KEY = "3C4FCF09F9B21C8A880F5C7A5A3D8C8B";
const PAYLOAD   = Buffer.from("F09F918BF09F8C8D", "hex");  // 👋🌍

async function post(endpoint, body) {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`${endpoint} returned ${response.status}: ${text}`);
    }
    return response.json();
}

async function main() {
    // ── Step 0: Generate a valid LoRaWAN frame ────────────────────────────────
    console.log("=== Step 0: Generate LoRaWAN frame ===");
    const packet = lora_packet.fromFields(
        {
            MType:   "Unconfirmed Data Up",
            DevAddr: Buffer.from("A1B2C3D4", "hex"),
            FCnt:    2,
            FPort:   1,
            payload: PAYLOAD,
        },
        Buffer.from(APP_S_KEY, "hex"),
        Buffer.from(NWK_S_KEY, "hex")
    );
    const raw_hex = packet.getPHYPayload().toString("hex");
    console.log("Raw frame (hex):", raw_hex);
    console.log();

    // ── Step 1: Parse frame via /info/hex ────────────────────────────────────
    console.log("=== Step 1: Parse frame (/info/hex) ===");
    const info = await post("/info/hex", { payload: raw_hex });
    console.log("MType:     ", info.mType);
    console.log("DevAddr:   ", info.devAddr);
    console.log("FCtrl:     ", info.fCtrl);
    console.log("FCnt:      ", info.fCnt);
    console.log("FPort:     ", info.fPort);
    console.log("MIC:       ", info.mic);
    console.log("FRMPayload:", info.frmPayload);
    console.log();

    // ── Step 2: Decrypt via /decrypt/hex ─────────────────────────────────────
    console.log("=== Step 2: Decrypt payload (/decrypt/hex) ===");
    const decrypted = await post("/decrypt/hex", {
        payload:   raw_hex,
        app_s_key: APP_S_KEY,
        nwk_s_key: NWK_S_KEY,
    });
    console.log("Decrypted (hex):", decrypted);
    console.log("Decrypted (utf8):", Buffer.from(decrypted, "hex").toString("utf8"));
    console.log();

    // ── Step 3: Decode via /decode/hex ───────────────────────────────────────
    console.log("=== Step 3: Decode payload (/decode/hex) ===");
    const decoded = await post("/decode/hex", {
        payload:     decrypted,
        application: "demo",
        device:      "hello_world",
        fPort:       info.fPort,
    });
    console.log("Decoded:", JSON.stringify(decoded, null, 2));

    // ── Summary ───────────────────────────────────────────────────────────────
    console.log();
    console.log("=== Summary ===");
    const text = decoded?.data?.text;
    if (text) {
        console.log(`✓ Success: payload decoded to "${text}"`);
    } else {
        console.error("✗ Decoding produced unexpected result");
        process.exit(1);
    }
}

main().catch((err) => {
    console.error("✗ Error:", err.message);
    process.exit(1);
});
