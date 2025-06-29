const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const port = 3000;

app.use(express.json());

function loadDecoder(application, device) {
    const decoderPath = path.join(__dirname, '../decoders', application, `${device}.js`);
    if (fs.existsSync(decoderPath)) {
        return require(decoderPath);
    } else {
        throw new Error(`Decoder not found for application "${application}" and device "${device}".`);
    }
}

function decodePayload(req, res, format) {
    const {
        application,
        device,
        payload,
        fPort
    } = req.body;

    if (!application || !device || !payload || !fPort) {
        return res.status(400).json({
            error: 'Invalid input. "application", "device", "payload", and "fPort" fields are required.'
        });
    }

    try {
        const decoder = loadDecoder(application, device);
        const bytes = Buffer.from(payload, format);
        const input = {
            bytes: Array.from(bytes),
            fPort
        };
        const result = decoder.decodeUplink(input);
        res.json(result);
    } catch (error) {
        res.status(500).json({
            error: 'Failed to decode data.',
            details: error.message
        });
    }
}

app.post('/decode/hex', (req, res) => {
    decodePayload(req, res, 'hex');
});

app.post('/decode/base64', (req, res) => {
    decodePayload(req, res, 'base64');
});

app.listen(port, (err) => {
    if (err) {
        console.error(`Failed to start server: ${err.message}`);
        process.exit(1);
    }
    console.log(`Decoder API listening at http://localhost:${port}`);
});
