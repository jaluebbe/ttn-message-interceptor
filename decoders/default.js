function decodeUplink(input) {
  return {
    data: {
      bytes: input.bytes
    },
    warnings: [],
    errors: []
  };
}

module.exports = { decodeUplink };
