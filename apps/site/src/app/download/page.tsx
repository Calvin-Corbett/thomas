import type { Metadata } from "next";
import { DownloadButton } from "@/components/download-button";
import { getCanonicalSiteUrl, getReleasesUrl } from "@/lib/site-config";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { CodeBlock } from "@/components/system-code-block";
import { safeLoad } from "@/lib/safe-load";
import {
  getSiteReleaseFeedWithState,
  type SiteReleaseAsset,
  type SiteReleaseFeedState,
} from "@/lib/site-release-data";

export const metadata: Metadata = {
  title: "Download",
  description: "Download Thomas for Windows, Mac, or Linux.",
};

const platformCards = [
  { label: "Windows", href: "/api/download?platform=windows&channel=stable&source=download_page_windows" },
  { label: "Mac", href: "/api/download?platform=macos&channel=stable&source=download_page_mac" },
  { label: "Linux", href: "/api/download?platform=linux&channel=stable&source=download_page_linux" },
];

const hardwareRequirements = [
  "CPU: modern x64 or ARM64.",
  "GPU: NVIDIA RTX 3080 class recommended for heavy local generation.",
  "RAM: 16GB minimum for full local workflows.",
  "Disk: 8GB free for cache, logs, and trace output.",
];

const pluginStoreOrigin = getCanonicalSiteUrl().replace(/\/+$/, "");

const featuredPlugins = [
  {
    id: "life-manager",
    name: "Life Manager",
    subtitle: "Tasks, agenda, habits, and goals in one local-first plugin.",
    description:
      "Installs as its own Thomas sidebar tab and keeps all state local to your active Thomas profile.",
    openInThomasUrl: `thomas://install-plugin?plugin_id=life-manager&store=${encodeURIComponent(pluginStoreOrigin)}&channel=stable`,
    manualDownloadUrl: `${pluginStoreOrigin}/api/v1/plugins/life-manager/manual-download`,
  },
];

const installGuidance = {
  windows: [
    "Run as the operator account that owns your automation directories.",
    "Allow localhost loopback prompts for local control channel only.",
    "Start with a dry-run workflow before any approval override path.",
  ],
  macos: [
    "Use downloaded artifact from the macOS endpoint.",
    "Open Security settings only if macOS blocks first-run execution.",
    "Verify command access before enabling automation.",
  ],
  linux: [
    "Install binary under a fixed path with execute permissions.",
    "Use a dedicated operator user with controlled access.",
    "Verify checksum before first startup.",
  ],
};

function statusMessage(status: string | undefined): string | null {
  if (!status) return null;
  if (status === "manual-not-configured") {
    return "Downloads are not configured yet. Add THOMAS_DOWNLOAD_URL_* env vars in production.";
  }
  if (status === "release-not-found") {
    return "No public release is available yet. Publish a release or set manual URLs.";
  }
  if (status === "asset-not-found") {
    return "Release exists, but no installer matched that platform and channel.";
  }
  return null;
}

function getAssetDigest(assets: SiteReleaseAsset[], platform: "windows" | "macos" | "linux") {
  const key = platform === "windows" ? "win" : platform === "macos" ? "mac" : "linux";
  return assets.find((asset) => asset.name.toLowerCase().includes(key))?.digest ?? null;
}

export default async function DownloadPage({ searchParams }: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  const params = searchParams ? await searchParams : undefined;
  const status = typeof params?.status === "string" ? params.status : undefined;
  const alert = statusMessage(status);
  const releasesUrl = getReleasesUrl();
  const feedStateResult = await safeLoad(() =>
    getSiteReleaseFeedWithState({ limit: 5, includePrerelease: false, channel: "stable" }),
  );

  const feedState: SiteReleaseFeedState = feedStateResult.ok ? feedStateResult.data : {
    releases: [],
    source: "none",
    status: "empty",
  };

  const history = feedState.releases;
  const latestRelease = history[0] ?? null;
  const releaseTag = latestRelease?.tag ?? "No public release yet";
  const digestsAvailable = latestRelease?.assets?.some((asset) => Boolean(asset.digest)) ?? false;

  const installChecks = [
    { label: "Windows", platform: "windows" as const, command: `Get-FileHash .\\thomas-win.exe -Algorithm SHA256` },
    { label: "macOS", platform: "macos" as const, command: `shasum -a 256 ./thomas-macos` },
    { label: "Linux", platform: "linux" as const, command: `sha256sum ./thomas-linux` },
  ];

  const checks = latestRelease
    ? installChecks.map((item) => ({
        ...item,
        digest: getAssetDigest(latestRelease.assets, item.platform),
      }))
    : installChecks.map((item) => ({ ...item, digest: null }));

  return (
    <SystemPageShell
      eyebrow="Download"
      title="Download Thomas"
      versionLabel={releaseTag}
    >
      {alert ? (
        <div className="alert-note">{alert}</div>
      ) : null}

      <div className="system-metric-grid">
        <DownloadButton source="download_page_auto" className="cta-primary" />
        {platformCards.map((platform) => (
          <a key={platform.label} className="cta-secondary" href={platform.href}>
            Download for {platform.label}
          </a>
        ))}
      </div>

      <SystemSection title="Verify your download">
        {digestsAvailable ? (
          <p className="system-metric-line">SHA-256 digests were published with this release.</p>
        ) : (
          <p className="system-metric-line">SHA-256 digests will appear here when published.</p>
        )}

        {checks.map((check) => (
          <details
            key={check.label}
            className="system-subsection"
            data-system-detail-id={`download-${check.label.toLowerCase()}-checksum-check`}
          >
            <summary className="system-metric-title">{check.label} checksum command</summary>
            <CodeBlock title={`${check.label.toLowerCase()}-sha256`} language="bash">
              {check.command}
            </CodeBlock>
          </details>
        ))}

        {digestsAvailable ? (
          <details className="system-subsection" data-system-detail-id="download-published-digests">
            <summary className="system-metric-title">Published digest reference</summary>
            <CodeBlock title="release digest manifest" language="text">
              {history
                .flatMap((release) => release.assets)
                .filter((asset): asset is SiteReleaseAsset => Boolean(asset.digest))
                .map((asset) => `${asset.name}: ${asset.digest}`)
                .join("\n")}
            </CodeBlock>
          </details>
        ) : null}
      </SystemSection>

      <SystemSection title="Feature plugins">
        <p className="system-metric-line">
          Automatic install opens Thomas with a <code>thomas://</code> deep link. If the protocol handler is unavailable,
          download the plugin ZIP and import it from Thomas Marketplace with <strong>Install From File</strong>.
        </p>
        <div className="plugin-store-list">
          {featuredPlugins.map((plugin) => (
            <article key={plugin.id} className="plugin-store-card">
              <div>
                <p className="plugin-store-kicker">Official plugin</p>
                <h3>{plugin.name}</h3>
                <p className="system-metric-line">{plugin.subtitle}</p>
                <p className="system-metric-note">{plugin.description}</p>
              </div>
              <div className="plugin-store-actions">
                <a className="cta-primary" href={plugin.openInThomasUrl}>
                  Open in Thomas
                </a>
                <a className="cta-secondary" href={plugin.manualDownloadUrl}>
                  Download ZIP
                </a>
              </div>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection title="Platform install notes">
        <details className="system-subsection" data-system-detail-id="download-platform-windows-notes">
          <summary className="system-metric-title">Windows</summary>
          <ul className="system-bullets">
            {installGuidance.windows.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="download-platform-macos-notes">
          <summary className="system-metric-title">macOS</summary>
          <ul className="system-bullets">
            {installGuidance.macos.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="download-platform-linux-notes">
          <summary className="system-metric-title">Linux</summary>
          <ul className="system-bullets">
            {installGuidance.linux.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      </SystemSection>

      <SystemSection title="System Requirements">
        <ul className="system-bullets">
          {hardwareRequirements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </SystemSection>

      <SystemSection title="Version history">
        <div className="system-version-list">
          {history.length === 0 ? (
            <p className="system-metric-line">No release history is available yet.</p>
          ) : (
            history.map((release) => (
              <details key={release.id} className="system-version-card" data-system-detail-id={`download-release-${release.id}`}>
                <summary>
                  <p className="system-section-title">Version {release.tag}</p>
                </summary>
                <p className="system-metric-line">Published: {new Date(release.publishedAt).toLocaleDateString()}</p>
                <p className="system-metric-note">{release.notes}</p>
              </details>
            ))
          )}
        </div>
        {releasesUrl ? (
          <p className="system-metric-line" style={{ marginTop: "0.6rem" }}>
            <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
              View full release notes on GitHub
            </a>
          </p>
        ) : null}
      </SystemSection>
    </SystemPageShell>
  );
}
