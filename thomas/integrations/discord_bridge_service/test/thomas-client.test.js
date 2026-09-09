import test from "node:test";
import assert from "node:assert/strict";

import { ThomasClient, parseThomasResponse } from "../src/thomas-client.js";

test("parseThomasResponse handles plain json payloads", () => {
  const parsed = parseThomasResponse(JSON.stringify({ text: "hello from thomas" }));
  assert.equal(parsed.text, "hello from thomas");
});

test("parseThomasResponse handles ndjson stream payloads", () => {
  const parsed = parseThomasResponse(
    [
      JSON.stringify({ type: "text", text: "hello " }),
      JSON.stringify({ type: "text", text: "world" }),
      JSON.stringify({ type: "done", text: "ignored done text" }),
    ].join("\n"),
  );
  assert.equal(parsed.text, "hello world");
});

test("parseThomasResponse falls back to done text", () => {
  const parsed = parseThomasResponse(JSON.stringify({ done: { text: "done text" } }));
  assert.equal(parsed.text, "done text");
});

test("ThomasClient resolves once the done event arrives", async () => {
  const originalFetch = global.fetch;
  const encoder = new TextEncoder();
  let streamCancelled = false;
  let requestedUrl = "";
  let requestedPayload = {};

  global.fetch = async (url, options) => {
    requestedUrl = String(url);
    requestedPayload = JSON.parse(String(options?.body || "{}"));
    return new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(JSON.stringify({ type: "text", text: "pong" }) + "\n"));
          controller.enqueue(encoder.encode(JSON.stringify({ type: "done", text: "pong" }) + "\n"));
        },
        cancel() {
          streamCancelled = true;
        },
      }),
      {
        status: 200,
        headers: {
          "Content-Type": "application/x-ndjson; charset=utf-8",
        },
      },
    );
  };

  try {
    const client = new ThomasClient({
      baseUrl: "http://127.0.0.1:8899",
      apiToken: "",
      timeoutMs: 5_000,
    });

    const result = await client.sendMessage({
      sessionId: "test-session",
      prompt: "Say only: pong",
      metadata: { source: "test" },
    });

    assert.equal(result.text, "pong");
    assert.equal(streamCancelled, true);
    assert.equal(requestedUrl, "http://127.0.0.1:8899/api/v2/chat");
    assert.equal(requestedPayload.session_id, "test-session");
    assert.equal(requestedPayload.message, "Say only: pong");
    assert.equal("text" in requestedPayload, false);
  } finally {
    global.fetch = originalFetch;
  }
});
