import test from "node:test";
import assert from "node:assert/strict";

import {
  replyLooksClarificationFallback,
  replyLooksInternal,
  sanitizeDiscordReply,
} from "../src/discord-format.js";

test("sanitizeDiscordReply leaves normal replies alone", () => {
  assert.equal(sanitizeDiscordReply("mentionless-ok"), "mentionless-ok");
});

test("sanitizeDiscordReply extracts a direct reply from leaked router notes", () => {
  const leaked = `
I’m treating this as a live Discord-handling task in the Thomas workspace.

The repo guardrails are loaded. I’m checking the startup lane and whether this worktree is clean enough.

Best reply to send:
You're right. Be specific about what you need, and I'll answer directly without the extra fluff.

If you want me to actually send it next, give me one of:
a Discord webhook or bot token plus the channel ID
`;

  assert.equal(
    sanitizeDiscordReply(leaked),
    "You're right. Be specific about what you need, and I'll answer directly without the extra fluff.",
  );
});

test("sanitizeDiscordReply strips internal paragraphs when a clean answer remains", () => {
  const leaked = `
I’m treating this as a Discord-response task for War Machine Pro in #general.

mentionless-ok
`;

  assert.equal(sanitizeDiscordReply(leaked), "mentionless-ok");
});

test("sanitizeDiscordReply trims reply-with snippets before repo notes", () => {
  const leaked =
    'I’m treating this as a Discord-response task. Reply with: voice check received loud and clear Repo note: I stayed in chat lane only.';

  assert.equal(sanitizeDiscordReply(leaked), "voice check received loud and clear");
});

test("replyLooksInternal catches tool-call meta answers", () => {
  assert.equal(
    replyLooksInternal(
      "I don't see any recorded tool calls in this conversation context. So the reliable answer is: no tools were executed.",
    ),
    true,
  );
});

test("sanitizeDiscordReply replaces tool-call meta answers", () => {
  assert.equal(
    sanitizeDiscordReply(
      "I don't see any recorded tool calls in this conversation context. So the reliable answer is: no tools were executed.",
    ),
    "Say that again in one short sentence and I'll answer directly.",
  );
});

test("replyLooksClarificationFallback catches the repeated voice failure line", () => {
  assert.equal(
    replyLooksClarificationFallback("Say that again in one short sentence and I'll answer directly."),
    true,
  );
  assert.equal(
    replyLooksClarificationFallback("The capital of Texas is Austin."),
    false,
  );
});
