import fs from "node:fs/promises";
import path from "node:path";

import { normalizeAccessGrants } from "./discord-access.js";

function normalizeWakeWords(value, fallback = []) {
  const items = Array.isArray(value) ? value : fallback;
  const normalized = items
    .map((item) => String(item || "").trim())
    .filter(Boolean);

  return normalized.length > 0 ? normalized : [...fallback];
}

function normalizeBoolean(value, fallback) {
  if (typeof value === "boolean") {
    return value;
  }
  return fallback;
}

function normalizeInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export class RuntimeSettingsStore {
  constructor({
    dataDir,
    defaults,
  }) {
    this.dataDir = dataDir;
    this.filePath = path.join(dataDir, "runtime-settings.json");
    this.defaults = {
      requireMention: Boolean(defaults.requireMention),
      voiceRequireWakeWord: Boolean(defaults.voiceRequireWakeWord),
      voiceWakeWords: normalizeWakeWords(defaults.voiceWakeWords, ["thomas"]),
      voiceMediaVolume: normalizeInteger(defaults.voiceMediaVolume, 100),
      voiceProfile: String(defaults.voiceProfile || "").trim() || null,
      accessGrants: normalizeAccessGrants(defaults.accessGrants),
    };
    this.state = { ...this.defaults };
    this.loaded = false;
  }

  normalizeState(candidate = {}) {
    return {
      requireMention: normalizeBoolean(candidate.requireMention, this.defaults.requireMention),
      voiceRequireWakeWord: normalizeBoolean(
        candidate.voiceRequireWakeWord,
        this.defaults.voiceRequireWakeWord,
      ),
      voiceWakeWords: normalizeWakeWords(candidate.voiceWakeWords, this.defaults.voiceWakeWords),
      voiceMediaVolume: Math.min(200, Math.max(0, normalizeInteger(candidate.voiceMediaVolume, this.defaults.voiceMediaVolume))),
      voiceProfile: String(candidate.voiceProfile || "").trim() || this.defaults.voiceProfile,
      accessGrants: normalizeAccessGrants(candidate.accessGrants ?? this.state.accessGrants ?? this.defaults.accessGrants),
    };
  }

  async ensureLoaded() {
    if (this.loaded) {
      return;
    }

    await fs.mkdir(this.dataDir, { recursive: true });
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        this.state = this.normalizeState(parsed);
      }
    } catch (error) {
      if (error && error.code !== "ENOENT") {
        throw error;
      }
      this.state = { ...this.defaults };
    }

    this.loaded = true;
  }

  getState() {
    return {
      ...this.state,
      voiceWakeWords: [...this.state.voiceWakeWords],
      accessGrants: JSON.parse(JSON.stringify(this.state.accessGrants || {})),
    };
  }

  get(key) {
    return this.getState()[key];
  }

  async update(patch) {
    await this.ensureLoaded();
    this.state = this.normalizeState({
      ...this.state,
      ...patch,
    });
    await fs.writeFile(this.filePath, JSON.stringify(this.state, null, 2), "utf8");
    return this.getState();
  }
}
