type DownloadCapture = {
  distinctId: string;
  platform: string;
  channel: string;
  releaseTag: string;
  assetName: string;
  source: string;
};

export async function captureDownloadIntent(data: DownloadCapture): Promise<void> {
  const key = process.env.POSTHOG_PROJECT_API_KEY;
  if (!key) return;

  const host = process.env.POSTHOG_HOST || "https://us.i.posthog.com";
  const endpoint = `${host.replace(/\/$/, "")}/capture/`;

  await fetch(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({
      api_key: key,
      event: "download_intent",
      distinct_id: data.distinctId,
      properties: {
        platform: data.platform,
        channel: data.channel,
        release_tag: data.releaseTag,
        asset_name: data.assetName,
        source: data.source,
      },
    }),
    cache: "no-store",
  }).catch(() => {
    // Ignore analytics transport failures.
  });
}
