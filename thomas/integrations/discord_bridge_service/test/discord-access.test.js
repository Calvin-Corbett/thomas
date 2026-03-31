import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_DELEGATE_CAPABILITIES,
  THOMAS_ACCESS_CAPABILITIES,
  buildAccessGrant,
  describeCapabilities,
  getRequiredCapabilityForNativeCommand,
  getUserCapabilities,
  normalizeAccessGrants,
} from "../src/discord-access.js";

test("normalizeAccessGrants keeps only valid user ids and capabilities", () => {
  assert.deepEqual(
    normalizeAccessGrants({
      "123": { capabilities: ["talk", "media", "invalid"], grantedBy: "456" },
      nope: { capabilities: ["talk"] },
      "789": { capabilities: [] },
    }),
    {
      "123": {
        capabilities: ["talk", "media"],
        grantedBy: "456",
      },
    },
  );
});

test("getUserCapabilities gives owner full access and delegates limited access", () => {
  const context = {
    ownerOnlyMode: true,
    ownerUserIds: new Set(["1"]),
    accessGrants: {
      "2": { capabilities: ["media"] },
    },
  };

  assert.deepEqual(
    getUserCapabilities(context, "1"),
    [
      THOMAS_ACCESS_CAPABILITIES.TALK,
      THOMAS_ACCESS_CAPABILITIES.MEDIA,
      THOMAS_ACCESS_CAPABILITIES.SETTINGS,
    ],
  );
  assert.deepEqual(getUserCapabilities(context, "2"), ["media"]);
  assert.deepEqual(getUserCapabilities(context, "3"), []);
});

test("buildAccessGrant and describeCapabilities format delegated access cleanly", () => {
  const grant = buildAccessGrant(DEFAULT_DELEGATE_CAPABILITIES, { grantedBy: "1" });
  assert.deepEqual(grant.capabilities, ["talk", "media"]);
  assert.equal(grant.grantedBy, "1");
  assert.equal(describeCapabilities(["talk", "media"]), "chat and music access");
  assert.equal(describeCapabilities(["media"]), "music access");
});

test("getRequiredCapabilityForNativeCommand maps settings and media commands", () => {
  assert.equal(
    getRequiredCapabilityForNativeCommand({ type: "play" }),
    THOMAS_ACCESS_CAPABILITIES.MEDIA,
  );
  assert.equal(
    getRequiredCapabilityForNativeCommand({ type: "join_voice_channel" }),
    THOMAS_ACCESS_CAPABILITIES.MEDIA,
  );
  assert.equal(
    getRequiredCapabilityForNativeCommand({ type: "set_voice_wake_required" }),
    THOMAS_ACCESS_CAPABILITIES.SETTINGS,
  );
});
