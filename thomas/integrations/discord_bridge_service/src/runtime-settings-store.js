import { EventEmitter } from "node:events";
import fsSync from "node:fs";
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

export class RuntimeSettingsStore extends EventEmitter {
  constructor({
    dataDir,
    defaults,
  }) {
    super();
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
    this.fileWatcher = null;
    this.reloadTimer = null;
    this.lastKnownMtimeMs = 0;
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
    if (!this.loaded) {
      await this.reloadFromDisk({ emitChange: false });
      this.loaded = true;
    }
    this.startWatching();
  }

  getMtimeMsSync() {
    try {
      return fsSync.statSync(this.filePath).mtimeMs || 0;
    } catch {
      return 0;
    }
  }

  updateState(nextState, { emitChange = true } = {}) {
    const previousState = this.state;
    const previousSerialized = JSON.stringify(previousState);
    const nextSerialized = JSON.stringify(nextState);
    this.state = nextState;
    if (emitChange && previousSerialized !== nextSerialized) {
      this.emit("change", this.getState(), {
        ...previousState,
        voiceWakeWords: [...(previousState.voiceWakeWords || [])],
        accessGrants: JSON.parse(JSON.stringify(previousState.accessGrants || {})),
      });
    }
  }

  async reloadFromDisk({ emitChange = true } = {}) {
    await fs.mkdir(this.dataDir, { recursive: true });
    let nextState = { ...this.defaults };
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        nextState = this.normalizeState(parsed);
      }
      this.lastKnownMtimeMs = this.getMtimeMsSync();
    } catch (error) {
      if (!error || error.code !== "ENOENT") {
        throw error;
      }
      this.lastKnownMtimeMs = 0;
    }

    this.updateState(nextState, { emitChange });
  }

  refreshFromDiskSync() {
    const currentMtimeMs = this.getMtimeMsSync();
    if (currentMtimeMs === this.lastKnownMtimeMs) {
      return;
    }

    this.lastKnownMtimeMs = currentMtimeMs;
    if (!currentMtimeMs) {
      this.updateState({ ...this.defaults }, { emitChange: true });
      return;
    }

    try {
      const raw = fsSync.readFileSync(this.filePath, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        this.updateState(this.normalizeState(parsed), { emitChange: true });
      }
    } catch {}
  }

  scheduleReloadFromDisk() {
    if (this.reloadTimer) {
      clearTimeout(this.reloadTimer);
    }
    this.reloadTimer = setTimeout(() => {
      this.reloadTimer = null;
      void this.reloadFromDisk({ emitChange: true }).catch(() => {});
    }, 80);
  }

  startWatching() {
    if (this.fileWatcher) {
      return;
    }

    try {
      this.fileWatcher = fsSync.watch(this.dataDir, (_eventType, filename) => {
        const changedFile = String(filename || "").trim();
        if (changedFile && changedFile !== path.basename(this.filePath)) {
          return;
        }
        this.scheduleReloadFromDisk();
      });
      this.fileWatcher.on("error", () => {});
    } catch {}
  }

  getState() {
    this.refreshFromDiskSync();
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
    const nextState = this.normalizeState({
      ...this.state,
      ...patch,
    });
    this.state = nextState;
    await fs.writeFile(this.filePath, JSON.stringify(nextState, null, 2), "utf8");
    this.lastKnownMtimeMs = this.getMtimeMsSync();
    this.updateState(nextState, { emitChange: true });
    return this.getState();
  }

  close() {
    if (this.reloadTimer) {
      clearTimeout(this.reloadTimer);
      this.reloadTimer = null;
    }
    if (this.fileWatcher) {
      this.fileWatcher.close();
      this.fileWatcher = null;
    }
  }
}
