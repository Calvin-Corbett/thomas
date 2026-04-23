import { DownloadButton } from "@/components/download-button";
import { CodeBlock } from "@/components/system-code-block";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { safeLoad } from "@/lib/safe-load";
import { getCanonicalSiteUrl, getReleasesUrl } from "@/lib/site-config";
import { getSiteCopy } from "@/lib/site-copy";
import { getSiteReleaseFeedWithState, type SiteReleaseAsset, type SiteReleaseFeedState } from "@/lib/site-release-data";
import { type SiteLocale } from "@/lib/site-locale";

const pluginStoreOrigin = getCanonicalSiteUrl().replace(/\/+$/, "");

const featuredPlugins = [
  {
    id: "life-manager",
    name: "Life Manager",
    openInThomasUrl: `thomas://install-plugin?plugin_id=life-manager&store=${encodeURIComponent(pluginStoreOrigin)}&channel=stable`,
    manualDownloadUrl: `${pluginStoreOrigin}/api/v1/plugins/life-manager/manual-download`,
  },
];

function getDownloadContent(locale: SiteLocale) {
  if (locale === "ja-JP") {
    return {
      noReleaseYet: "公開リリースはまだありません",
      publishedLabel: "公開日",
      platformLabels: { windows: "Windows", macos: "macOS", linux: "Linux" },
      installGuidance: {
        windows: [
          "実際に Thomas を使うアカウントでインストーラを実行してください。",
          "localhost へのアクセスはローカル制御チャネルに必要な範囲だけ許可してください。",
          "危険な承認を増やす前に、まずはドライランで流れを確認してください。",
        ],
        macos: [
          "サイトから取得した macOS ビルドを使用してください。",
          "初回起動を macOS が止めた場合のみ、セキュリティ設定を開いてください。",
          "繰り返し使うワークフローを有効にする前に、コマンド実行権限を確認してください。",
        ],
        linux: [
          "実行権限のある安定したパスにバイナリを配置してください。",
          "より厳密に管理したい場合は専用ユーザーを使ってください。",
          "初回起動前にチェックサムを確認してください。",
        ],
      },
      hardwareRequirements: [
        "CPU: 最新の x64 または ARM64。",
        "GPU: 重いローカル生成には NVIDIA RTX 3080 クラス推奨。",
        "RAM: 本格利用では最低 16GB。",
        "ディスク: キャッシュ、ログ、トレース用に 8GB 以上の空き容量。",
      ],
    };
  }

  if (locale === "zh-CN") {
    return {
      noReleaseYet: "暂时还没有公开版本",
      publishedLabel: "发布日期",
      platformLabels: { windows: "Windows", macos: "macOS", linux: "Linux" },
      installGuidance: {
        windows: [
          "请使用实际运行 Thomas 的账户执行安装程序。",
          "只为本地控制通道开放必要的 localhost 访问。",
          "在批准高风险操作前，先跑一遍可检查的演练流程。",
        ],
        macos: [
          "请使用网站提供的 macOS 构建。",
          "只有在 macOS 阻止首次启动时才去系统安全设置里放行。",
          "在启用可重复工作流前先确认命令访问权限。",
        ],
        linux: [
          "把二进制放在固定且具备执行权限的路径下。",
          "如果你想更严格控制，建议使用专用用户。",
          "首次启动前先验证校验和。",
        ],
      },
      hardwareRequirements: [
        "CPU：较新的 x64 或 ARM64。",
        "GPU：重度本地生成建议使用 NVIDIA RTX 3080 级别。",
        "内存：完整本地工作流至少 16GB。",
        "磁盘：缓存、日志和追踪输出建议保留 8GB 可用空间。",
      ],
    };
  }

  return {
    noReleaseYet: "No public release yet",
    publishedLabel: "Published",
    platformLabels: { windows: "Windows", macos: "macOS", linux: "Linux" },
    installGuidance: {
      windows: [
        "Run the installer from the account that will actually use Thomas.",
        "Allow localhost access only for the local control channel.",
        "Start with a dry-run workflow before approving anything risky.",
      ],
      macos: [
        "Use the downloaded macOS build from the site.",
        "Open Security settings only if macOS blocks first launch.",
        "Confirm command access before turning on repeatable workflows.",
      ],
      linux: [
        "Install the binary in a stable path with execute permission.",
        "Use a dedicated user when you want tighter control.",
        "Verify the checksum before first launch.",
      ],
    },
    hardwareRequirements: [
      "CPU: modern x64 or ARM64.",
      "GPU: NVIDIA RTX 3080 class recommended for heavy local generation.",
      "RAM: 16GB minimum for full local workflows.",
      "Disk: 8GB free for cache, logs, and trace output.",
    ],
  };
}

function getAssetDigest(assets: SiteReleaseAsset[], platform: "windows" | "macos" | "linux") {
  const key = platform === "windows" ? "win" : platform === "macos" ? "mac" : "linux";
  return assets.find((asset) => asset.name.toLowerCase().includes(key))?.digest ?? null;
}

export async function SiteDownloadPage({
  locale = "en",
  searchParams,
}: {
  locale?: SiteLocale;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const copy = getSiteCopy(locale);
  const content = getDownloadContent(locale);
  const params = searchParams ? await searchParams : undefined;
  const status = typeof params?.status === "string" ? params.status : undefined;
  const alert = !status
    ? null
    : status === "manual-not-configured"
      ? copy.download.statusManual
      : status === "release-not-found"
        ? copy.download.statusReleaseMissing
        : status === "asset-not-found"
          ? copy.download.statusAssetMissing
          : null;
  const releasesUrl = getReleasesUrl();
  const feedStateResult = await safeLoad(() =>
    getSiteReleaseFeedWithState({ limit: 5, includePrerelease: false, channel: "stable" }),
  );

  const feedState: SiteReleaseFeedState = feedStateResult.ok
    ? feedStateResult.data
    : {
        releases: [],
        source: "none",
        status: "empty",
      };

  const history = feedState.releases;
  const latestRelease = history[0] ?? null;
  const releaseTag = latestRelease?.tag ?? content.noReleaseYet;
  const digestsAvailable = latestRelease?.assets?.some((asset) => Boolean(asset.digest)) ?? false;
  const platformCards = [
    {
      label: copy.download.platformLabels.windows,
      href: "/api/download?platform=windows&channel=stable&source=download_page_windows",
    },
    {
      label: content.platformLabels.macos,
      href: "/api/download?platform=macos&channel=stable&source=download_page_mac",
    },
    {
      label: content.platformLabels.linux,
      href: "/api/download?platform=linux&channel=stable&source=download_page_linux",
    },
  ];

  const installChecks = [
    {
      label: copy.download.platformLabels.windows,
      platform: "windows" as const,
      command: `Get-FileHash .\\thomas-win.exe -Algorithm SHA256`,
    },
    {
      label: content.platformLabels.macos,
      platform: "macos" as const,
      command: `shasum -a 256 ./thomas-macos`,
    },
    {
      label: content.platformLabels.linux,
      platform: "linux" as const,
      command: `sha256sum ./thomas-linux`,
    },
  ];

  const checks = latestRelease
    ? installChecks.map((item) => ({
        ...item,
        digest: getAssetDigest(latestRelease.assets, item.platform),
      }))
    : installChecks.map((item) => ({ ...item, digest: null }));

  return (
    <SystemPageShell eyebrow={copy.download.eyebrow} title={copy.download.title} versionLabel={releaseTag}>
      {alert ? <div className="alert-note">{alert}</div> : null}

      <div className="system-metric-grid">
        <DownloadButton
          source="download_page_auto"
          className="cta-primary"
          labelPrefix={copy.components.downloadButton}
          platformLabels={content.platformLabels}
        />
        {platformCards.map((platform) => (
          <a key={platform.label} className="cta-secondary" href={platform.href}>
            {copy.components.downloadButton} {platform.label}
          </a>
        ))}
      </div>

      <SystemSection title={copy.download.verifyTitle}>
        <p className="system-metric-line">
          {digestsAvailable ? copy.download.digestsPublished : copy.download.digestsMissing}
        </p>

        {checks.map((check) => (
          <details
            key={check.label}
            className="system-subsection"
            data-system-detail-id={`download-${check.label.toLowerCase()}-checksum-check`}
          >
            <summary className="system-metric-title">
              {check.label} {copy.download.checksumSuffix}
            </summary>
            <CodeBlock title={`${check.label.toLowerCase()}-sha256`} language="bash">
              {check.command}
            </CodeBlock>
          </details>
        ))}

        {digestsAvailable ? (
          <details className="system-subsection" data-system-detail-id="download-published-digests">
            <summary className="system-metric-title">{copy.download.digestReference}</summary>
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

      <SystemSection title={copy.download.featurePluginsTitle}>
        <p className="system-metric-line">{copy.download.featurePluginsIntro}</p>
        <div className="plugin-store-list">
          {featuredPlugins.map((plugin) => (
            <article key={plugin.id} className="plugin-store-card">
              <div>
                <p className="plugin-store-kicker">{copy.download.officialPlugin}</p>
                <h3>{plugin.name}</h3>
                <p className="system-metric-line">{copy.download.pluginSubtitle}</p>
                <p className="system-metric-note">{copy.download.pluginDescription}</p>
              </div>
              <div className="plugin-store-actions">
                <a className="cta-primary" href={plugin.openInThomasUrl}>
                  {copy.download.openInThomas}
                </a>
                <a className="cta-secondary" href={plugin.manualDownloadUrl}>
                  {copy.download.downloadZip}
                </a>
              </div>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection title={copy.download.installNotesTitle}>
        <details className="system-subsection" data-system-detail-id="download-platform-windows-notes">
          <summary className="system-metric-title">{copy.download.platformLabels.windows}</summary>
          <ul className="system-bullets">
            {content.installGuidance.windows.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="download-platform-macos-notes">
          <summary className="system-metric-title">{content.platformLabels.macos}</summary>
          <ul className="system-bullets">
            {content.installGuidance.macos.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="download-platform-linux-notes">
          <summary className="system-metric-title">{content.platformLabels.linux}</summary>
          <ul className="system-bullets">
            {content.installGuidance.linux.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      </SystemSection>

      <SystemSection title={copy.download.systemRequirementsTitle}>
        <ul className="system-bullets">
          {content.hardwareRequirements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </SystemSection>

      <SystemSection title={copy.download.versionHistoryTitle}>
        <div className="system-version-list">
          {history.length === 0 ? (
            <p className="system-metric-line">{copy.download.noHistory}</p>
          ) : (
            history.map((release) => (
              <details
                key={release.id}
                className="system-version-card"
                data-system-detail-id={`download-release-${release.id}`}
              >
                <summary>
                  <p className="system-section-title">
                    {copy.components.updatesFeed.versionPrefix} {release.tag}
                  </p>
                </summary>
                <p className="system-metric-line">
                  {content.publishedLabel}: {new Date(release.publishedAt).toLocaleDateString(locale)}
                </p>
                <p className="system-metric-note">{release.notes}</p>
              </details>
            ))
          )}
        </div>
        {releasesUrl ? (
          <p className="system-metric-line" style={{ marginTop: "0.6rem" }}>
            <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
              {copy.download.fullNotes}
            </a>
          </p>
        ) : null}
      </SystemSection>
    </SystemPageShell>
  );
}
