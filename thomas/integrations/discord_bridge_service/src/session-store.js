import fs from "node:fs/promises";
import path from "node:path";

export class SessionStore {
  constructor({ dataDir, sessionPrefix }) {
    this.dataDir = dataDir;
    this.sessionPrefix = sessionPrefix;
    this.filePath = path.join(dataDir, "sessions.json");
    this.state = { versions: {} };
    this.loaded = false;
  }

  async ensureLoaded() {
    if (this.loaded) {
      return;
    }

    await fs.mkdir(this.dataDir, { recursive: true });
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && parsed.versions && typeof parsed.versions === "object") {
        this.state = parsed;
      }
    } catch (error) {
      if (error && error.code !== "ENOENT") {
        throw error;
      }
    }

    this.loaded = true;
  }

  async getSessionId(scopeKey) {
    await this.ensureLoaded();
    const version = this.state.versions[scopeKey] || 1;
    return `${this.sessionPrefix}:${scopeKey}:v${version}`;
  }

  async reset(scopeKey) {
    await this.ensureLoaded();
    const nextVersion = (this.state.versions[scopeKey] || 1) + 1;
    this.state.versions[scopeKey] = nextVersion;
    await fs.writeFile(this.filePath, JSON.stringify(this.state, null, 2), "utf8");
    return `${this.sessionPrefix}:${scopeKey}:v${nextVersion}`;
  }
}

export function buildScopeKey(message) {
  if (!message.guild) {
    return `dm:${message.author.id}`;
  }

  return `guild:${message.guild.id}:channel:${message.channel.id}`;
}

export function buildVoiceScopeKey({ guildId, channelId }) {
  return `guild:${guildId}:voice:${channelId}`;
}
