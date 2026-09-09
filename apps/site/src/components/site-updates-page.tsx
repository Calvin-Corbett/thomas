import { getSiteReleaseFeedWithState, type SiteReleaseFeedState } from "@/lib/site-release-data";
import { SystemPageShell } from "@/components/system-page";
import { UpdatesPageFeed } from "@/components/updates-page-feed";
import { safeLoad } from "@/lib/safe-load";
import { getSiteCopy } from "@/lib/site-copy";
import { type SiteLocale } from "@/lib/site-locale";

function getNoReleaseLabel(locale: SiteLocale) {
  if (locale === "ja-JP") return "まだリリースはありません";
  if (locale === "zh-CN") return "暂时还没有发布版本";
  return "No release yet";
}

export async function SiteUpdatesPage({ locale = "en" }: { locale?: SiteLocale }) {
  const copy = getSiteCopy(locale);
  const noReleaseLabel = getNoReleaseLabel(locale);
  const feedStateResult = await safeLoad(() =>
    getSiteReleaseFeedWithState({ limit: 20, includePrerelease: false, channel: "stable" }),
  );

  const fetchFailed = !feedStateResult.ok;
  const feedState: SiteReleaseFeedState = feedStateResult.ok
    ? feedStateResult.data
    : { releases: [], source: "none", status: "empty" };

  const dataSourceLabel =
    feedState.source === "github"
      ? copy.updates.liveData
      : feedState.source === "local"
        ? copy.updates.cachedData
        : copy.updates.unavailableData;

  const statusHint =
    feedState.source === "github"
      ? copy.updates.unavailableMessageSuffixLive
      : feedState.source === "local"
        ? copy.updates.unavailableMessageSuffixCached
        : copy.updates.unavailableMessageSuffixUnavailable;

  return (
    <SystemPageShell title={copy.updates.title} versionLabel={feedState.releases[0]?.tag ?? noReleaseLabel}>
      <UpdatesPageFeed
        releases={feedState.releases}
        dataSourceLabel={dataSourceLabel}
        showFailureNotice={fetchFailed || feedState.source === "local"}
        labels={copy.components.updatesFeed}
        failureMessage={
          fetchFailed
            ? `${copy.updates.unavailableMessagePrefix}${feedStateResult.ok ? "" : ` (${feedStateResult.error})`}. ${statusHint}`
            : null
        }
      />
    </SystemPageShell>
  );
}
