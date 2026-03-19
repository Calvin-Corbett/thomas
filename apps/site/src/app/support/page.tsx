import type { Metadata } from "next";
import { getRepoUrl } from "@/lib/site-config";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { CodeBlock } from "@/components/system-code-block";

export const metadata: Metadata = {
  title: "Support",
  description: "Get help with Thomas or report an issue.",
};

const issueTemplate = `## What failed
- Command or prompt that triggered the issue
- Expected output
- Actual output

## Environment
- Thomas version
- OS and architecture

## Repro steps
- Exact reproduction steps
- Last 20 lines from logs (if available)
- Screenshot or terminal capture
`;

export default function SupportPage() {
  const repoUrl = getRepoUrl();

  return (
    <SystemPageShell
      title="Support"
      intro="Found a bug or need help? Here's how to reach us."
    >
      <SystemSection title="Report an issue">
        {repoUrl ? (
          <a
            className="cta-primary"
            href={`${repoUrl}/issues/new/choose`}
            target="_blank"
            rel="noreferrer"
            style={{ display: "inline-flex", width: "fit-content" }}
          >
            Open a GitHub Issue
          </a>
        ) : (
          <p className="system-metric-line">GitHub issue reporting will be available once repository integration is configured.</p>
        )}
      </SystemSection>

      <SystemSection title="What to include">
        <p className="system-metric-line">A good bug report helps us fix things fast. Tell us:</p>
        <ul className="system-bullets">
          <li>What command you ran (or what you clicked).</li>
          <li>The error message you saw.</li>
          <li>Your OS and Thomas version.</li>
          <li>Steps to reproduce the issue, if possible.</li>
        </ul>
      </SystemSection>

      <SystemSection title="Issue template">
        <p className="system-metric-line">Copy and paste this into your GitHub issue:</p>
        <CodeBlock title="issue-template.md" language="text">
          {issueTemplate}
        </CodeBlock>
      </SystemSection>

      <SystemSection title="Common fixes">
        <details className="system-subsection" data-system-detail-id="support-triage-installer">
          <summary className="system-metric-title">Installer won't run</summary>
          <ul className="system-bullets">
            <li>Make sure the download matches your OS (Windows/Mac/Linux).</li>
            <li>Run the checksum command from the Download page to verify the file.</li>
            <li>Try running it again with logging enabled.</li>
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="support-triage-command-blocked">
          <summary className="system-metric-title">Command blocked or denied</summary>
          <ul className="system-bullets">
            <li>Check your approval settings and policy mode.</li>
            <li>Make sure the command exists in your version (check release notes).</li>
            <li>Include the full error output when reporting.</li>
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="support-triage-behavior">
          <summary className="system-metric-title">Something isn't working right</summary>
          <ul className="system-bullets">
            <li>Check the latest release notes for breaking changes.</li>
            <li>Try the same action on a fresh install if possible.</li>
            <li>Include a log excerpt with timestamps when reporting.</li>
          </ul>
        </details>
      </SystemSection>

      <p className="system-metric-line" style={{ marginTop: "0.5rem" }}>
        Please don't include API keys, tokens, or passwords in bug reports. Replace them with placeholders.
      </p>
    </SystemPageShell>
  );
}
