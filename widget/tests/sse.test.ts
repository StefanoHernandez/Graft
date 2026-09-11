import assert from "node:assert/strict";
import test from "node:test";

import { createSseParser, type SseEvent } from "../src/sse.js";

const encoder = new TextEncoder();

function collect(chunks: string[]): SseEvent[] {
  const events: SseEvent[] = [];
  const parser = createSseParser((event) => events.push(event));
  for (const chunk of chunks) parser.push(encoder.encode(chunk));
  return events;
}

test("parses a simple frame", () => {
  assert.deepEqual(collect(['event: delta\ndata: {"text":"hi"}\n\n']), [
    { event: "delta", data: '{"text":"hi"}' },
  ]);
});

test("emits nothing until the frame is complete", () => {
  assert.deepEqual(collect(["event: delta\ndata: partial"]), []);
});

test("accepts CRLF line endings", () => {
  assert.deepEqual(collect(["event: done\r\ndata: {}\r\n\r\n"]), [
    { event: "done", data: "{}" },
  ]);
});

test("ignores heartbeat comments", () => {
  const events = collect([": keep-alive\n\n", "event: delta\ndata: x\n\n"]);
  assert.deepEqual(events, [{ event: "delta", data: "x" }]);
});

test("joins multiple data lines with a newline", () => {
  assert.deepEqual(collect(["event: delta\ndata: one\ndata: two\n\n"]), [
    { event: "delta", data: "one\ntwo" },
  ]);
});

test("defaults the event name when the frame omits it", () => {
  assert.deepEqual(collect(["data: bare\n\n"]), [{ event: "message", data: "bare" }]);
});

test("handles several frames arriving in one chunk", () => {
  const events = collect(["event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"]);
  assert.deepEqual(events.map((e) => e.event), ["a", "b"]);
});

test("survives a split at every single byte boundary", () => {
  // The real transport splits wherever it likes, including mid-field.
  const body = 'event: delta\ndata: {"text":"hello"}\n\nevent: done\ndata: {"ok":true}\n\n';
  for (let cut = 1; cut < body.length; cut += 1) {
    const events = collect([body.slice(0, cut), body.slice(cut)]);
    assert.deepEqual(
      events,
      [
        { event: "delta", data: '{"text":"hello"}' },
        { event: "done", data: '{"ok":true}' },
      ],
      `split at ${cut}`,
    );
  }
});

test("survives a split inside a multi-byte character", () => {
  const body = 'event: delta\ndata: {"text":"perché è così"}\n\n';
  const bytes = encoder.encode(body);
  for (let cut = 1; cut < bytes.length; cut += 1) {
    const events: SseEvent[] = [];
    const parser = createSseParser((event) => events.push(event));
    parser.push(bytes.slice(0, cut));
    parser.push(bytes.slice(cut));
    assert.deepEqual(events, [{ event: "delta", data: '{"text":"perché è così"}' }], `cut ${cut}`);
  }
});

test("a lone byte at a time still reassembles the frame", () => {
  const bytes = encoder.encode('event: delta\ndata: {"text":"è"}\n\n');
  const events: SseEvent[] = [];
  const parser = createSseParser((event) => events.push(event));
  for (const byte of bytes) parser.push(new Uint8Array([byte]));
  assert.deepEqual(events, [{ event: "delta", data: '{"text":"è"}' }]);
});
