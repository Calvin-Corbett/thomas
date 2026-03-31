function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizePhrase(value) {
  return String(value || "").trim().toLowerCase();
}

export function buildTextWakePhrases({ botNames = [], configuredWakeWords = [] } = {}) {
  const phrases = new Set();

  for (const wakeWord of configuredWakeWords) {
    const normalized = normalizePhrase(wakeWord);
    if (normalized) {
      phrases.add(normalized);
    }
  }

  for (const name of botNames) {
    const normalized = normalizePhrase(name);
    if (!normalized) {
      continue;
    }

    phrases.add(normalized);
    phrases.add(`hey ${normalized}`);
    phrases.add(`yo ${normalized}`);
    phrases.add(`ok ${normalized}`);
    phrases.add(`okay ${normalized}`);
  }

  return [...phrases];
}

export function isTextAddressedToBot(text, options = {}) {
  const content = String(text || "").trim();
  if (!content) {
    return false;
  }

  const phrases = buildTextWakePhrases(options);
  return phrases.some((phrase) =>
    new RegExp(`^${escapeRegExp(phrase)}(?:$|[\\s,.:;!?-])`, "i").test(content),
  );
}
