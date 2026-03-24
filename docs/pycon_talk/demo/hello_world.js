function decodeUplink(input) {
  return {
    data: {
      text: Buffer.from(input.bytes).toString("utf8")
    },
    warnings: [],
    errors: []
  };
}

module.exports = { decodeUplink };
