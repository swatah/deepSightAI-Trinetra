require("@testing-library/jest-dom");

if (typeof globalThis.TextEncoder === "undefined") {
  const { TextEncoder, TextDecoder } = require("util");
  globalThis.TextEncoder = TextEncoder;
  globalThis.TextDecoder = TextDecoder;
}

if (typeof globalThis.ReadableStream === "undefined") {
  const { ReadableStream } = require("stream/web");
  globalThis.ReadableStream = ReadableStream;
}

if (typeof globalThis.setImmediate === "undefined") {
  globalThis.setImmediate = (fn, ...args) => setTimeout(fn, 0, ...args);
  globalThis.clearImmediate = (id) => clearTimeout(id);
}
