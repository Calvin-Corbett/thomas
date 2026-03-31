export function parseThomasResponse(rawText) {
  const raw = String(rawText || "").trim();
  if (!raw) {
    return { text: "" };
  }

  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      return {
        text:
          String(parsed.text || parsed.message || parsed.reply || parsed.output || "").trim() ||
          extractDoneText(parsed.done),
        payload: parsed,
      };
    }
  } catch {}

  const textParts = [];
  let doneText = "";
  let payload;

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    try {
      const event = JSON.parse(trimmed);
      if (!event || typeof event !== "object") {
        continue;
      }
      payload = event;
      const chunk = extractEventText(event);
      if (chunk) {
        textParts.push(chunk);
      }
      const type = String(event.type || "").toLowerCase();
      if (type === "done") {
        doneText = extractDoneText(event);
      } else if (type === "error") {
        throw new Error(String(event.error || "Thomas returned an error event."));
      }
    } catch (error) {
      if (error instanceof SyntaxError) {
        continue;
      }
      throw error;
    }
  }

  return { text: textParts.join("").trim() || doneText.trim(), payload };
}

function extractDoneText(value) {
  if (!value || typeof value !== "object") {
    return "";
  }
  return String(value.text || value.message || value.reply || "").trim();
}

function extractEventText(event) {
  if (!event || typeof event !== "object") {
    return "";
  }

  const type = String(event.type || "").toLowerCase();
  if (type === "done") {
    return "";
  }

  if (["text", "assistant_delta", "delta", "message_delta"].includes(type)) {
    return String(event.text || event.delta || event.content || "");
  }

  return "";
}

async function readThomasStream(response) {
  if (!response.body) {
    return parseThomasResponse(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const textParts = [];
  let doneText = "";
  let payload;
  let buffer = "";

  async function closeReader() {
    try {
      await reader.cancel();
    } catch {}
  }

  function handlePacket(packet) {
    if (!packet || typeof packet !== "object") {
      return null;
    }

    payload = packet;
    const chunk = extractEventText(packet);
    if (chunk) {
      textParts.push(chunk);
    }

    const type = String(packet.type || "").toLowerCase();
    if (type === "done") {
      doneText = extractDoneText(packet);
      return { done: true };
    }
    if (type === "error") {
      throw new Error(String(packet.error || "Thomas returned an error event."));
    }
    return null;
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      let nextBreak = buffer.indexOf("\n");
      while (nextBreak >= 0) {
        const line = buffer.slice(0, nextBreak).trim();
        buffer = buffer.slice(nextBreak + 1);
        if (line) {
          const signal = handlePacket(JSON.parse(line));
          if (signal?.done) {
            await closeReader();
            return { text: textParts.join("").trim() || doneText.trim(), payload };
          }
        }
        nextBreak = buffer.indexOf("\n");
      }
    }

    if (buffer.trim()) {
      handlePacket(JSON.parse(buffer.trim()));
    }

    return { text: textParts.join("").trim() || doneText.trim(), payload };
  } finally {
    await closeReader();
  }
}

export class ThomasClient {
  constructor({ baseUrl, apiToken, timeoutMs }) {
    this.baseUrl = baseUrl;
    this.apiToken = apiToken;
    this.timeoutMs = timeoutMs;
  }

  async sendMessage({ sessionId, prompt, metadata }) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const headers = {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson, application/json",
      };

      if (this.apiToken) {
        headers.Authorization = `Bearer ${this.apiToken}`;
      }

      const response = await fetch(`${this.baseUrl}/api/chat`, {
        method: "POST",
        headers,
        signal: controller.signal,
        body: JSON.stringify({
          session_id: sessionId,
          message: prompt,
          text: prompt,
          channel: "discord",
          source: "discord_bridge",
          client: "discord_bot",
          surface: "discord",
          mode: "auto",
          metadata,
        }),
      });
      if (!response.ok) {
        const rawText = await response.text();
        throw new Error(`Thomas returned HTTP ${response.status}: ${rawText.slice(0, 400)}`);
      }

      const contentType = String(response.headers.get("content-type") || "").toLowerCase();
      if (contentType.includes("application/x-ndjson")) {
        return await readThomasStream(response);
      }

      return parseThomasResponse(await response.text());
    } finally {
      clearTimeout(timeout);
    }
  }
}
