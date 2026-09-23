if (typeof global.Request !== "undefined") {
  globalThis.Request = global.Request;
  globalThis.Response = global.Response;
  globalThis.Headers = global.Headers;
  globalThis.fetch = global.fetch;
}

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

if (typeof globalThis.crypto === "undefined" || !globalThis.crypto.subtle) {
  const { webcrypto } = require("crypto");
  globalThis.crypto = webcrypto;
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
