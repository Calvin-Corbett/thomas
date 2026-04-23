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

  global.fetch = async () =>
    new Response(
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
  } finally {
    global.fetch = originalFetch;
  }
});

test("ThomasClient uses the legacy chat route by default", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response('{"text":"ok"}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const client = new ThomasClient({
    baseUrl: "http://127.0.0.1:8899",
    apiToken: null,
    timeoutMs: 1_000,
  });

  const result = await client.sendMessage({
    sessionId: "sess-1",
    prompt: "hello",
    metadata: { source: "discord-bridge" },
  });

  assert.equal(result.text, "ok");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8899/api/chat");
  const body = JSON.parse(String(calls[0].options.body));
  assert.equal(body.mode, "auto");
  assert.equal(body.channel, "discord");
});

test("ThomasClient can target v2 chat with low-latency overrides", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response('{"type":"done","text":"fast reply"}\n', {
      status: 200,
      headers: { "content-type": "application/x-ndjson" },
    });
  };

  const client = new ThomasClient({
    baseUrl: "http://127.0.0.1:8899",
    apiToken: null,
    timeoutMs: 1_000,
  });

  const result = await client.sendMessage({
    sessionId: "sess-voice",
    prompt: "what time is it",
    apiPath: "/api/v2/chat",
    autonomyLevel: 1,
    tokenEconomy: "cheap",
    reasoningEffort: "low",
    metadata: { source: "discord-voice-bridge" },
  });

  assert.equal(result.text, "fast reply");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8899/api/v2/chat");
  const body = JSON.parse(String(calls[0].options.body));
  assert.equal(body.autonomy_level, 1);
  assert.equal(body.token_economy, "cheap");
  assert.equal(body.reasoning_effort, "low");
});
