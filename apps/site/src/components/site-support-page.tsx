import { getRepoUrl } from "@/lib/site-config";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { CodeBlock } from "@/components/system-code-block";
import { getSiteCopy } from "@/lib/site-copy";
import { type SiteLocale } from "@/lib/site-locale";

function getSupportContent(locale: SiteLocale) {
  if (locale === "ja-JP") {
    return {
      issueTemplate: `## 何が起きたか
- 問題を起こしたコマンドまたは依頼
- 期待していた結果
- 実際の結果

## 環境
- Thomas のバージョン
- OS とアーキテクチャ

## 再現手順
- 正確な再現手順
- 取得できればログの最後の 20 行
- スクリーンショットまたは端末キャプチャ
`,
      fixes: {
        installer: [
          "ダウンロードした内容が使っている OS に合っているか確認してください。",
          "Download ページのチェックサム確認コマンドでファイルを検証してください。",
          "ログを有効にしてもう一度インストーラを試してください。",
        ],
        commandBlocked: [
          "承認設定とポリシーモードを確認してください。",
          "そのコマンドが自分のバージョンに含まれているか確認してください。",
          "報告時には完全なエラー出力を添えてください。",
        ],
        behaviorWrong: [
          "最新のリリースノートに破壊的変更がないか確認してください。",
          "可能ならクリーンな環境でも同じ操作を試してください。",
          "報告時には時刻付きのログ抜粋を添えてください。",
        ],
      },
    };
  }

  if (locale === "zh-CN") {
    return {
      issueTemplate: `## 出了什么问题
- 触发问题的命令或请求
- 你预期的结果
- 实际发生的结果

## 环境
- Thomas 版本
- 操作系统和架构

## 复现步骤
- 准确的复现步骤
- 如果方便，请附上最后 20 行日志
- 截图或终端画面
`,
      fixes: {
        installer: [
          "确认下载内容与你的操作系统匹配。",
          "使用 Download 页面里的校验命令确认文件没有损坏。",
          "开启日志后再试一次安装程序。",
        ],
        commandBlocked: [
          "检查你的审批设置和策略模式。",
          "确认这个命令在你安装的版本中确实存在。",
          "提交问题时附上完整错误输出。",
        ],
        behaviorWrong: [
          "先看最新发布说明里有没有破坏性变更。",
          "如果可以，尝试在全新安装上复现同样操作。",
          "提交问题时附上带时间戳的日志片段。",
        ],
      },
    };
  }

  return {
    issueTemplate: `## What failed
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
`,
    fixes: {
      installer: [
        "Make sure the download matches your operating system.",
        "Run the checksum command from the Download page to verify the file.",
        "Try the installer again with logging enabled.",
      ],
      commandBlocked: [
        "Check your approval settings and policy mode.",
        "Confirm the command exists in your installed version.",
        "Include the full error output when reporting the issue.",
      ],
      behaviorWrong: [
        "Check the latest release notes for breaking changes.",
        "Try the same action on a fresh install if possible.",
        "Include a timestamped log excerpt when reporting the issue.",
      ],
    },
  };
}

export function SiteSupportPage({ locale = "en" }: { locale?: SiteLocale }) {
  const repoUrl = getRepoUrl();
  const copy = getSiteCopy(locale);
  const content = getSupportContent(locale);

  return (
    <SystemPageShell title={copy.support.title} intro={copy.support.intro}>
      <SystemSection title={copy.support.reportIssue}>
        {repoUrl ? (
          <a
            className="cta-primary"
            href={`${repoUrl}/issues/new/choose`}
            target="_blank"
            rel="noreferrer"
            style={{ display: "inline-flex", width: "fit-content" }}
          >
            {copy.support.openIssue}
          </a>
        ) : (
          <p className="system-metric-line">{copy.support.githubUnavailable}</p>
        )}
      </SystemSection>

      <SystemSection title={copy.support.whatToInclude}>
        <p className="system-metric-line">{copy.support.whatToIncludeIntro}</p>
        <ul className="system-bullets">
          <li>{copy.support.bullets.command}</li>
          <li>{copy.support.bullets.error}</li>
          <li>{copy.support.bullets.os}</li>
          <li>{copy.support.bullets.repro}</li>
        </ul>
      </SystemSection>

      <SystemSection title={copy.support.issueTemplate}>
        <p className="system-metric-line">{copy.support.issueTemplateIntro}</p>
        <CodeBlock title="issue-template.md" language="text">
          {content.issueTemplate}
        </CodeBlock>
      </SystemSection>

      <SystemSection title={copy.support.commonFixes}>
        <details className="system-subsection" data-system-detail-id="support-triage-installer">
          <summary className="system-metric-title">{copy.support.installerFix}</summary>
          <ul className="system-bullets">
            {content.fixes.installer.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="support-triage-command-blocked">
          <summary className="system-metric-title">{copy.support.commandBlocked}</summary>
          <ul className="system-bullets">
            {content.fixes.commandBlocked.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
        <details className="system-subsection" data-system-detail-id="support-triage-behavior">
          <summary className="system-metric-title">{copy.support.behaviorWrong}</summary>
          <ul className="system-bullets">
            {content.fixes.behaviorWrong.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      </SystemSection>

      <p className="system-metric-line" style={{ marginTop: "0.5rem" }}>
        {copy.support.securityWarning}
      </p>
    </SystemPageShell>
  );
}
