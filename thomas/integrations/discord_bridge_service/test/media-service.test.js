import test from "node:test";
import assert from "node:assert/strict";

import {
  buildMetadataArgs,
  buildSearchArgs,
  buildStreamUrlArgs,
  isLikelyUrl,
  isSpotifyUrl,
  normalizeMediaEntry,
} from "../src/media-service.js";

test("buildSearchArgs uses ytsearch and node runtime", () => {
  assert.deepEqual(buildSearchArgs("lofi hip hop", 3), [
    "-m",
    "yt_dlp",
    "ytsearch3:lofi hip hop",
    "--dump-json",
    "--skip-download",
    "--flat-playlist",
    "--playlist-end",
    "3",
    "--no-warnings",
    "--ignore-errors",
    "--quiet",
    "--js-runtimes",
    "node",
  ]);
});

test("buildMetadataArgs and buildStreamUrlArgs target the requested URL", () => {
  const url = "https://www.youtube.com/watch?v=test";
  assert.ok(buildMetadataArgs(url).includes(url));
  assert.equal(buildStreamUrlArgs(url).at(-1), url);
});

test("normalizeMediaEntry keeps the important metadata", () => {
  assert.deepEqual(
    normalizeMediaEntry({
      id: "abc",
      title: "Example",
      webpage_url: "https://youtube.com/watch?v=abc",
      channel: "Example Channel",
      duration: 91.2,
    }),
    {
      id: "abc",
      title: "Example",
      webpageUrl: "https://youtube.com/watch?v=abc",
      channel: "Example Channel",
      uploader: null,
      durationSeconds: 91,
    },
  );
});

test("url helpers distinguish youtube and spotify links", () => {
  assert.equal(isLikelyUrl("https://youtube.com/watch?v=abc"), true);
  assert.equal(isLikelyUrl("lofi hip hop"), false);
  assert.equal(isSpotifyUrl("https://open.spotify.com/track/123"), true);
  assert.equal(isSpotifyUrl("https://youtube.com/watch?v=abc"), false);
});
