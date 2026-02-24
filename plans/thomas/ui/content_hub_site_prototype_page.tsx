// Moved out of apps/site. This prototype is retained for internal product work.
type PlatformStat = {
  name: string;
  connected: boolean;
  followers: number;
  postsThisWeek: number;
  engagementRate: string;
  queued: number;
};

type WorkflowTemplate = {
  name: string;
  trigger: string;
  automation: string;
  approval: string;
};

type SchedulerItem = {
  day: string;
  time: string;
  channel: string;
  type: string;
  status: "Queued" | "Drafting" | "Awaiting Approval";
};

const platformStats: PlatformStat[] = [
  {
    name: "X / Twitter",
    connected: true,
    followers: 12420,
    postsThisWeek: 11,
    engagementRate: "4.1%",
    queued: 6,
  },
  {
    name: "LinkedIn",
    connected: true,
    followers: 3805,
    postsThisWeek: 4,
    engagementRate: "6.4%",
    queued: 3,
  },
  {
    name: "Instagram",
    connected: false,
    followers: 0,
    postsThisWeek: 0,
    engagementRate: "--",
    queued: 0,
  },
  {
    name: "YouTube Shorts",
    connected: true,
    followers: 2140,
    postsThisWeek: 2,
    engagementRate: "5.7%",
    queued: 2,
  },
];

const workflowTemplates: WorkflowTemplate[] = [
  {
    name: "Research to Post",
    trigger: "Daily topic sweep at 8:00 AM",
    automation: "Thomas drafts one insight post per connected platform",
    approval: "Single-click approve with platform-specific edits",
  },
  {
    name: "Longform to Shortform",
    trigger: "New article, transcript, or changelog item detected",
    automation: "Thomas creates 6 snippets (thread, carousel, short, quote cards)",
    approval: "Bulk approve and auto-schedule in best engagement windows",
  },
  {
    name: "Launch Day Burst",
    trigger: "Product release tag is published",
    automation: "Thomas generates announcement + follow-up posts across channels",
    approval: "Approval gate per channel with rollback to draft",
  },
];

const schedulerQueue: SchedulerItem[] = [
  {
    day: "Monday",
    time: "9:30 AM",
    channel: "LinkedIn",
    type: "Thought leadership",
    status: "Queued",
  },
  {
    day: "Monday",
    time: "1:00 PM",
    channel: "X / Twitter",
    type: "Build update thread",
    status: "Drafting",
  },
  {
    day: "Tuesday",
    time: "11:00 AM",
    channel: "YouTube Shorts",
    type: "Release highlight",
    status: "Awaiting Approval",
  },
  {
    day: "Wednesday",
    time: "8:45 AM",
    channel: "LinkedIn",
    type: "Case study recap",
    status: "Queued",
  },
];

const managerCapabilities = [
  {
    title: "Unified Content Queue",
    detail: "See every draft, scheduled post, and published asset in one timeline.",
  },
  {
    title: "Cross-Platform Variants",
    detail: "Thomas rewrites the same core idea to match each channel's native style and limits.",
  },
  {
    title: "Approvals and Guardrails",
    detail: "Require approval before publish, enforce banned terms, and lock brand voice rules.",
  },
  {
    title: "Performance Feedback Loop",
    detail: "Top-performing posts become reusable prompt patterns for future workflow runs.",
  },
];

const controlSurfaceItems = [
  "Connections and channel status",
  "Active sessions and run-state",
  "Cron automation jobs",
  "Skills and API key readiness",
  "Execution approvals",
  "Logs and health checks",
];

const coreNavigation = [
  "Home",
  "Planner",
  "Create",
  "Calendar",
  "Library",
  "Inbox",
  "Analytics",
  "Automations",
  "Integrations",
  "Settings",
];

const implementationChecklist = [
  "Accounts, Platforms, and Identity",
  "Universal Content Model",
  "Asset Library",
  "Planning and Campaigns",
  "Composer",
  "Scheduling and Queueing",
  "Publishing Reliability",
  "Unified Inbox",
  "Analytics and Reporting",
  "Listening and Trend Intel",
  "Collaboration and Approvals",
  "Automations",
  "AI Layer",
  "Creator Business Ops",
  "Governance and Security",
  "Developer Extensibility",
];

function formatNumber(value: number): string {
  return value.toLocaleString();
}

export default function ContentHubPagePrototype() {
  const connectedCount = platformStats.filter((platform) => platform.connected).length;
  const totalAudience = platformStats.reduce((total, platform) => total + platform.followers, 0);
  const queuedPosts = platformStats.reduce((total, platform) => total + platform.queued, 0);

  return (
    <section className="content-hub-shell">
      <div className="hub-hero">
        <p className="eyebrow">Content Hub</p>
        <h1 className="page-title">Manage every content channel from one Thomas workflow.</h1>
        <p className="page-intro">
          Connect platforms, build automations, and let Thomas research, draft, and schedule posts while you keep
          approval control.
        </p>
        <div className="hub-hero-cta">
          <a className="cta-primary" href="#workflow-builder">
            Build A Workflow
          </a>
          <a className="cta-secondary" href="#scheduler">
            Open Scheduler
          </a>
        </div>
      </div>

      <div className="hub-stats-grid" aria-label="Content Hub summary metrics">
        <article className="hub-stat-card">
          <p>Connected Platforms</p>
          <strong>{connectedCount}</strong>
          <span>out of {platformStats.length} configured channels</span>
        </article>
        <article className="hub-stat-card">
          <p>Total Audience Reach</p>
          <strong>{formatNumber(totalAudience)}</strong>
          <span>followers across connected platforms</span>
        </article>
        <article className="hub-stat-card">
          <p>Scheduled Queue</p>
          <strong>{queuedPosts}</strong>
          <span>posts ready for auto-publish</span>
        </article>
      </div>

      <section className="section-shell">
        <div className="section-head">
          <h2>Connected platform stats</h2>
          <span className="hub-section-hint">Live cards per connected account</span>
        </div>
        <div className="hub-platform-grid">
          {platformStats.map((platform) => (
            <article key={platform.name} className="hub-platform-card">
              <div className="hub-platform-header">
                <h3>{platform.name}</h3>
                <span className={`hub-connection-pill${platform.connected ? " is-online" : ""}`}>
                  {platform.connected ? "Connected" : "Not Connected"}
                </span>
              </div>
              <div className="hub-platform-metrics">
                <p>
                  Followers <strong>{platform.connected ? formatNumber(platform.followers) : "--"}</strong>
                </p>
                <p>
                  Posts This Week <strong>{platform.connected ? platform.postsThisWeek : "--"}</strong>
                </p>
                <p>
                  Engagement <strong>{platform.connected ? platform.engagementRate : "--"}</strong>
                </p>
                <p>
                  In Queue <strong>{platform.connected ? platform.queued : "--"}</strong>
                </p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-shell" id="workflow-builder">
        <div className="section-head">
          <h2>Workflow builder</h2>
          <span className="hub-section-hint">Build once, run daily</span>
        </div>
        <div className="hub-workflow-grid">
          {workflowTemplates.map((workflow) => (
            <article key={workflow.name} className="hub-workflow-card">
              <h3>{workflow.name}</h3>
              <p>
                <span>Trigger:</span> {workflow.trigger}
              </p>
              <p>
                <span>Automation:</span> {workflow.automation}
              </p>
              <p>
                <span>Approval:</span> {workflow.approval}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-shell" id="scheduler">
        <div className="section-head">
          <h2>Scheduler</h2>
          <span className="hub-section-hint">Time-zone aware publish queue</span>
        </div>
        <div className="hub-scheduler-shell">
          <table className="hub-scheduler-table">
            <thead>
              <tr>
                <th>Day</th>
                <th>Time</th>
                <th>Platform</th>
                <th>Content Type</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {schedulerQueue.map((item) => (
                <tr key={`${item.day}-${item.time}-${item.channel}`}>
                  <td>{item.day}</td>
                  <td>{item.time}</td>
                  <td>{item.channel}</td>
                  <td>{item.type}</td>
                  <td>
                    <span className="hub-status-pill">{item.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section-shell">
        <div className="section-head">
          <h2>Thomas content manager tools</h2>
          <span className="hub-section-hint">Everything needed to run multi-platform output</span>
        </div>
        <div className="hub-manager-grid">
          {managerCapabilities.map((capability) => (
            <article key={capability.title} className="hub-manager-card">
              <h3>{capability.title}</h3>
              <p>{capability.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-shell">
        <div className="section-head">
          <h2>Chat-first control pattern</h2>
          <span className="hub-section-hint">Dashboard visibility for what is running and what needs approval</span>
        </div>
        <div className="hub-manager-grid">
          {controlSurfaceItems.map((item) => (
            <article key={item} className="hub-manager-card">
              <h3>{item}</h3>
              <p>Built into the same workspace so creators can operate from chat and still retain controls.</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-shell">
        <div className="section-head">
          <h2>Core information architecture</h2>
          <span className="hub-section-hint">Minimal pages and one unified tracker</span>
        </div>
        <div className="hub-manager-grid">
          <article className="hub-manager-card">
            <h3>Core left-nav</h3>
            <p>{coreNavigation.join(" | ")}</p>
          </article>
          <article className="hub-manager-card">
            <h3>Everything checklist coverage</h3>
            <p>{implementationChecklist.join(" | ")}</p>
          </article>
        </div>
      </section>
    </section>
  );
}
