import fs from "node:fs";
import path from "node:path";

const KNOWN_PIPER_VOICE_PROFILES = [
  {
    id: "en_US-ryan-high",
    label: "Ryan High",
    aliases: ["ryan", "ryan high", "en us ryan high"],
  },
  {
    id: "en_US-lessac-high",
    label: "Lessac High",
    aliases: ["lessac", "lessac high", "en us lessac high"],
  },
  {
    id: "en_US-lessac-medium",
    label: "Lessac Medium",
    aliases: ["lessac medium", "en us lessac medium"],
  },
];

function normalizeVoiceAlias(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function titleCaseWords(value) {
  return String(value || "")
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export function discoverPiperVoiceProfiles(dataDir, currentModel = null) {
  const knownById = new Map(KNOWN_PIPER_VOICE_PROFILES.map((profile) => [profile.id, profile]));
  const discoveredIds = new Set();

  try {
    const entries = fs.readdirSync(dataDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".onnx")) {
        continue;
      }
      discoveredIds.add(entry.name.slice(0, -5));
    }
  } catch {}

  if (currentModel) {
    discoveredIds.add(currentModel);
  }

  const profiles = [];
  for (const id of discoveredIds) {
    const known = knownById.get(id);
    if (known) {
      profiles.push(known);
      continue;
    }

    profiles.push({
      id,
      label: titleCaseWords(path.basename(id)),
      aliases: [normalizeVoiceAlias(id)],
    });
  }

  for (const profile of KNOWN_PIPER_VOICE_PROFILES) {
    if (!profiles.some((entry) => entry.id === profile.id)) {
      profiles.push(profile);
    }
  }

  return profiles.sort((left, right) => left.label.localeCompare(right.label));
}

export function resolveVoiceProfile(value, profiles = KNOWN_PIPER_VOICE_PROFILES) {
  const normalized = normalizeVoiceAlias(value);
  if (!normalized) {
    return null;
  }

  for (const profile of profiles) {
    const aliases = new Set([
      normalizeVoiceAlias(profile.id),
      normalizeVoiceAlias(profile.label),
      ...(profile.aliases || []).map(normalizeVoiceAlias),
    ]);
    if (aliases.has(normalized)) {
      return profile;
    }
  }

  return null;
}

export function formatVoiceProfileLabel(model, profiles = KNOWN_PIPER_VOICE_PROFILES) {
  const profile = profiles.find((entry) => entry.id === model);
  return profile?.label || model;
}

export function buildVoiceProfileChoices(dataDir, currentModel = null) {
  return discoverPiperVoiceProfiles(dataDir, currentModel)
    .slice(0, 25)
    .map((profile) => ({
      name: profile.label,
      value: profile.id,
    }));
}
