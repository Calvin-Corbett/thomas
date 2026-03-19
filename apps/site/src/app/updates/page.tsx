import type { Metadata } from "next";
import { getSiteReleaseFeedWithState, type SiteReleaseFeedState } from "@/lib/site-release-data";
import { SystemPageShell } from "@/components/system-page";
import { UpdatesPageFeed } from "@/components/updates-page-feed";
import { safeLoad } from "@/lib/safe-load";

export const metadata: Metadata = {
  title: "What's New",
  description: "Release notes and updates for Thomas.",
};

export default async function UpdatesPage() {
  const feedStateResult = await safeLoad(() =>
    getSiteReleaseFeedWithState({ limit: 20, includePrerelease: false, channel: "stable" }),
  );

  const fetchFailed = !feedStateResult.ok;
  const feedState: SiteReleaseFeedState = feedStateResult.ok
    ? feedStateResult.data
    : {
        releases: [],
        source: "none",
        status: "empty",
      };

  const dataSourceLabel =
    feedState.source === "github"
      ? "Release data: live GitHub feed."
      : feedState.source === "local"
      ? "Release data: local cache fallback."
      : "Release data: unavailable (no entries).";

  const statusHint =
    feedState.source === "github"
      ? "live"
      : feedState.source === "local"
      ? "cached"
      : "unavailable";

  return (
    <SystemPageShell
      title="What's New"
      versionLabel={feedState.releases[0]?.tag ?? "No release yet"}
    >
      <UpdatesPageFeed
        releases={feedState.releases}
        dataSourceLabel={dataSourceLabel}
        showFailureNotice={fetchFailed || feedState.source === "local"}
        failureMessage={
          fetchFailed
            ? `Release feed is currently unavailable${feedStateResult.ok ? "" : ` (${feedStateResult.error})`}. Showing ${statusHint} dataset.`
            : null
        }
      />
    </SystemPageShell>
  );
}
