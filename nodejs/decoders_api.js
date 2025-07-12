const express = require('express');
const path = require('path');
const fs = require('fs');
const lora_packet = require("lora-packet");

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());

const ERROR_MESSAGES = {
    MISSING_FIELDS: 'Invalid input. Required fields are missing.',
    INVALID_MIC: 'Invalid MIC. The packet integrity check failed.',
    DECRYPTION_FAILED: 'Failed to decrypt data.',
    DECODING_FAILED: 'Failed to decode data.'
};

const decoderCache = {};

function validateFields(fields, body) {
    const missingFields = fields.filter(field => !body[field]);
    return missingFields.length > 0 ? `Missing required fields: ${missingFields.join(', ')}` : null;
}

function sendError(res, status, message, details = null) {
    res.status(status).json({ error: message, details });
}

async function loadDecoder(application, device) {
    const cacheKey = `${application}:${device}`;
    if (decoderCache[cacheKey]) return decoderCache[cacheKey];

    const decoderPath = path.join(__dirname, '../decoders', application, `${device}.js`);
    try {
        await fs.promises.access(decoderPath);
        const decoder = require(decoderPath);
        decoderCache[cacheKey] = decoder;
        return decoder;
    } catch {
        throw new Error(`Decoder not found for application "${application}" and device "${device}".`);
    }
}

async function decodePayload(req, res, format) {
    const { application, device, payload, fPort } = req.body;

    const validationError = validateFields(['application', 'device', 'payload', 'fPort'], req.body);
    if (validationError) {
        return sendError(res, 400, validationError);
    }

    try {
        const decoder = await loadDecoder(application, device);
        const bytes = Buffer.from(payload, format);
        const input = {
            bytes: Array.from(bytes),
            fPort
        };
        const result = decoder.decodeUplink(input);
        res.json(result);
    } catch (error) {
        sendError(res, 500, ERROR_MESSAGES.DECODING_FAILED, error.message);
    }
}

function decryptPayload(req, res, format) {
    const { payload, app_s_key, nwk_s_key } = req.body;

    const validationError = validateFields(['payload', 'app_s_key', 'nwk_s_key'], req.body);
    if (validationError) {
        return sendError(res, 400, validationError);
    }

    try {
        const bytes = Buffer.from(payload, format);
        const packet = lora_packet.fromWire(bytes);
        const AppSKey = Buffer.from(app_s_key, 'hex');
        const NwkSKey = Buffer.from(nwk_s_key, 'hex');

        if (!lora_packet.verifyMIC(packet, NwkSKey)) {
            return sendError(res, 400, ERROR_MESSAGES.INVALID_MIC);
        }

        const decryptedPayload = lora_packet.decrypt(packet, AppSKey, NwkSKey);
        res.json(decryptedPayload.toString('hex'));
    } catch (error) {
        sendError(res, 500, ERROR_MESSAGES.DECRYPTION_FAILED, error.message);
    }
}

function extractMessageInfo(req, res, format) {
    const { payload } = req.body;

    const validationError = validateFields(['payload'], req.body);
    if (validationError) {
        return sendError(res, 400, validationError);
    }

    try {
        const bytes = Buffer.from(payload, format);
        const packet = lora_packet.fromWire(bytes);
        const messageInfo = {
            rawMessage: bytes.toString('hex'),
            devAddr: packet.DevAddr.toString('hex'),
            fPort: packet.getFPort(),
            fCnt: packet.getFCnt(),
            mic: packet.MIC.toString('hex'),
            mType: packet.getMType(),
            direction: packet.getDir() === 0 ? 'uplink' : 'downlink',
            frmPayload: packet.FRMPayload.toString('hex'),
            macPayload: packet.MACPayload.toString('hex'),
            fCtrl: packet.FCtrl.toString('hex'),
            fOpts: packet.FOpts.toString('hex'),
            mhdr: packet.MHDR.toString('hex')
        };

        res.json(messageInfo);
    } catch (error) {
        sendError(res, 500, 'Failed to extract message information.', error.message);
    }
}

app.post('/decode/hex', (req, res) => decodePayload(req, res, 'hex'));
app.post('/decode/base64', (req, res) => decodePayload(req, res, 'base64'));
app.post('/decrypt/hex', (req, res) => decryptPayload(req, res, 'hex'));
app.post('/decrypt/base64', (req, res) => decryptPayload(req, res, 'base64'));
app.post('/info/hex', (req, res) => extractMessageInfo(req, res, 'hex'));
app.post('/info/base64', (req, res) => extractMessageInfo(req, res, 'base64'));

app.listen(port, (err) => {
    if (err) {
        console.error(`Failed to start server: ${err.message}`);
        process.exit(1);
    }
    console.log(`Decoder API listening at http://localhost:${port}`);
});
