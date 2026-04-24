"""Constants for Mission Control Content Hub aggregation."""

from __future__ import annotations

import re
from typing import Any, Dict, List


_CONTENT_ACTIVE_STATUSES = {"queued", "running", "awaiting_approval"}
_CONTENT_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "dead"}
_CONTENT_PLATFORM_ALIASES: Dict[str, str] = {
    "x": "X / Twitter",
    "twitter": "X / Twitter",
    "tweet": "X / Twitter",
    "tweets": "X / Twitter",
    "x.com": "X / Twitter",
    "linkedin": "LinkedIn",
    "linked_in": "LinkedIn",
    "instagram": "Instagram",
    "insta": "Instagram",
    "youtube": "YouTube Shorts",
    "youtube_shorts": "YouTube Shorts",
    "shorts": "YouTube Shorts",
    "tiktok": "TikTok",
    "tik_tok": "TikTok",
    "facebook": "Facebook",
    "fb": "Facebook",
    "threads": "Threads",
}
_CONTENT_TEXT_PLATFORM_HINTS: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:twitter|tweet|x\.com)\b", re.IGNORECASE), "X / Twitter"),
    (re.compile(r"\b(?:linkedin|linked\s*in)\b", re.IGNORECASE), "LinkedIn"),
    (re.compile(r"\b(?:instagram|insta)\b", re.IGNORECASE), "Instagram"),
    (re.compile(r"\b(?:youtube|shorts?)\b", re.IGNORECASE), "YouTube Shorts"),
    (re.compile(r"\b(?:tiktok|tik\s*tok)\b", re.IGNORECASE), "TikTok"),
    (re.compile(r"\b(?:facebook|meta)\b", re.IGNORECASE), "Facebook"),
    (re.compile(r"\bthreads\b", re.IGNORECASE), "Threads"),
]
_CONTENT_HINT_FIELDS = (
    "platform",
    "platforms",
    "target_platform",
    "target_platforms",
    "channel",
    "channels",
    "publish_to",
    "destination",
    "destinations",
    "target",
    "targets",
)
_CONTENT_KEYWORD_RE = re.compile(
    r"\b(?:content|post|social|channel|publish|tweet|thread|shorts?|campaign|creator|audience)\b",
    re.IGNORECASE,
)
_CONTENT_PLATFORM_ORDER: List[str] = [
    "X / Twitter",
    "LinkedIn",
    "Instagram",
    "YouTube Shorts",
    "TikTok",
    "Facebook",
    "Threads",
]
_CONTENT_FALLBACK_PLATFORM = "All Channels"
_CONTENT_RELEVANT_JOB_KINDS = {
    "workflow_task",
    "autonomy_task",
    "daily_briefing",
    "reminder",
    "video_generation",
}
_CONTENT_HUB_NAV_ITEMS: List[Dict[str, str]] = [
    {"id": "home", "label": "Home", "description": "Today view with live control status, approvals, and health."},
    {"id": "planner", "label": "Planner", "description": "Ideas, briefs, campaigns, and assignment tracking."},
    {"id": "create", "label": "Create", "description": "Composer for multi-platform variants and reusable templates."},
    {"id": "calendar", "label": "Calendar", "description": "Schedule and queue management with recurrence + drag/drop planning."},
    {"id": "library", "label": "Library", "description": "Asset vault, metadata, rights, and brand-kit governance."},
    {"id": "inbox", "label": "Inbox", "description": "Unified comments, mentions, and DM operations."},
    {"id": "analytics", "label": "Analytics", "description": "Cross-platform performance and reporting summaries."},
    {"id": "automations", "label": "Automations", "description": "Trigger-condition-action workflows and agent runs."},
    {"id": "integrations", "label": "Integrations", "description": "Platform connections, API keys, and capability checks."},
    {"id": "settings", "label": "Settings", "description": "Security, roles, permissions, and workspace controls."},
]
_CONTENT_HUB_ORGANIZATION_AXES: List[Dict[str, str]] = [
    {"id": "time", "label": "By time", "description": "Calendar schedule, queues, recurrence, and launch shifts."},
    {"id": "campaign", "label": "By campaign/project", "description": "Launches, pillars, goals, dependencies, and owners."},
    {"id": "asset", "label": "By asset", "description": "Library-first flow for media, variants, metadata, and reuse."},
]
_CONTENT_HUB_CHECKLIST_TEMPLATE: List[Dict[str, Any]] = [
    {
        "id": "accounts_identity",
        "title": "1) Accounts, Platforms, and Identity",
        "summary": "Fast and safe connection management for every channel/workspace.",
        "items": [
            "OAuth per platform with clear scopes and connection health.",
            "Multi-account, multi-brand workspace model with role boundaries.",
            "Capability detection per channel (supported post types, fields, and schedule limits).",
            "Secure token vault, rotation/revocation, and audit trail for connections.",
        ],
    },
    {
        "id": "content_model",
        "title": "2) Universal Content Model",
        "summary": "Manage once, generate platform-native variants everywhere.",
        "items": [
            "Canonical objects: Asset, Post, Variant, Campaign, Approval, Performance snapshot.",
            "Custom status flow from Idea to Archived with approvals in-line.",
            "Taxonomy by pillar, audience segment, funnel stage, and tags.",
            "Versioning, diffs, restore, and attachment validation by platform.",
        ],
    },
    {
        "id": "library",
        "title": "3) Asset Library",
        "summary": "Searchable vault for upload/import, rights, and reuse (no in-hub media editing).",
        "items": [
            "Bulk upload and external storage imports (Drive/Dropbox/OneDrive/S3/R2).",
            "Smart collections, metadata extraction, and where-used graph.",
            "Rights/expiration tracking, retention controls, and archival lifecycle.",
            "Virus scanning, integrity checks, alt text, caption-file attachment support.",
        ],
    },
    {
        "id": "planning",
        "title": "4) Planning: Ideas, Briefs, Campaigns",
        "summary": "Move from random posting to strategic campaign execution.",
        "items": [
            "Idea inbox from notes/URLs/transcripts.",
            "Brief templates with hook, promise, CTA, persona, and legal fields.",
            "Campaign goals, deliverables, dependencies, and owner tracking.",
            "Research panel for reference examples, hashtags, and evergreen FAQ angles.",
        ],
    },
    {
        "id": "composer",
        "title": "5) Composer",
        "summary": "Create once, branch variants, and keep platform constraints visible.",
        "items": [
            "Platform/account targeting with post-type specific field support.",
            "Caption editor with limits, hashtag sets, mention suggestions, and previews.",
            "Variant generation and duplication workflows for A/B testing.",
            "Localization, region-specific copy variants, and compliance warnings.",
        ],
    },
    {
        "id": "scheduling",
        "title": "6) Scheduling, Queueing, Calendar",
        "summary": "Consistency engine for cadence, timing, and publish dependencies.",
        "items": [
            "Day/week/month/agenda views with drag-drop scheduling.",
            "Evergreen/campaign/priority queues plus timezone-aware publishing.",
            "Gap/conflict detection and bulk schedule management.",
            "Recurrence rules, dependency chains, and rescheduling engine.",
        ],
    },
    {
        "id": "publishing_reliability",
        "title": "7) Publishing and Reliability",
        "summary": "Ensure delivery, retries, observability, and incident response.",
        "items": [
            "Scheduled, manual, and human-confirmed publish modes.",
            "Retry handling with transient/permanent failure classification.",
            "Lifecycle tracking: scheduled, sent, accepted, live URL captured.",
            "Incident center, per-post logs, rate-limit handling, and dedupe warnings.",
        ],
    },
    {
        "id": "engagement_hub",
        "title": "8) Engagement Hub (Unified Inbox)",
        "summary": "One queue for comments/mentions/DMs with team assignment.",
        "items": [
            "Inbound streams for comments, replies, mentions, and DMs where APIs allow.",
            "Filters, assignment, SLA timers, and collision detection.",
            "Saved replies/snippets, moderation rules, and case conversion.",
            "Spike alerts and mobile push workflows.",
        ],
    },
    {
        "id": "analytics",
        "title": "9) Analytics and Reporting",
        "summary": "Answers over vanity charts with post/campaign-level outcomes.",
        "items": [
            "Cross-platform overview for reach, engagement, growth, CTR/watch-time.",
            "Post/campaign breakdowns with period-over-period benchmarking.",
            "Scheduled report exports (CSV/PDF) and UTM/link tracking.",
            "AI insight layer: why performance moved and what to do next.",
        ],
    },
    {
        "id": "listening",
        "title": "10) Social Listening and Trend Intel",
        "summary": "Track brand/keyword movement and convert trends into content plans.",
        "items": [
            "Keyword, hashtag, mention, and reference tracking.",
            "Topic clusters and optional sentiment scoring.",
            "Trend detection and inspiration board with reusable hook taxonomy.",
            "AI assist to convert trend signals into pillar-ready post concepts.",
        ],
    },
    {
        "id": "collaboration",
        "title": "11) Collaboration and Approvals",
        "summary": "Safe teamwork with strict approval gates and traceability.",
        "items": [
            "Role model: owner/admin/editor/approver/viewer/client.",
            "Single and multi-stage approval flows with required approvers by content type.",
            "Draft comments, change requests, and approval lock/reapproval enforcement.",
            "Task/capacity planning and full audit history.",
        ],
    },
    {
        "id": "automation",
        "title": "12) Automations",
        "summary": "Turn recurring workflows into transparent, logged automation runs.",
        "items": [
            "Time-based cron, event-based, HITL approval, and agentic automation modes.",
            "Trigger -> Conditions -> Actions builder with reusable workflow blocks.",
            "Webhook in/out plus Zapier/Make/n8n style bridge points.",
            "Run history, trace logs, and failure remediation paths.",
        ],
    },
    {
        "id": "ai_layer",
        "title": "13) AI Layer",
        "summary": "Copilot across planner/composer/scheduling/inbox/analytics, not a gimmick tab.",
        "items": [
            "Idea/brief generation tied to pillars, audience, and campaign goals.",
            "Brand-voice rewrite and platform-native variant generation.",
            "Best-time and cadence recommendations from history.",
            "Reply drafting, thread summarization, and analytics narrative guidance.",
        ],
    },
    {
        "id": "business_ops",
        "title": "14) Creator Business Ops",
        "summary": "Optional monetization operations for sponsorships, affiliates, and commerce.",
        "items": [
            "Sponsorship CRM with deliverables linked to scheduled posts.",
            "Affiliate/promo tracking with outcome visibility.",
            "Rights tracking for UGC/licensed content.",
            "Commerce catalog references and product-tag workflow support where available.",
        ],
    },
    {
        "id": "security",
        "title": "15) Governance and Security",
        "summary": "Security-first execution model inspired by real ecosystem incidents.",
        "items": [
            "Least-privilege roles, publish gates, and destructive-action confirmations.",
            "Encrypted secrets storage with rotation/revocation visibility.",
            "Signed integrations/skills with sandboxing and explicit permission prompts.",
            "Retention, backup, abuse protections, and safe-mode defaults.",
        ],
    },
    {
        "id": "extensibility",
        "title": "16) Developer and Power User Extensibility",
        "summary": "API and marketplace model for advanced automation at scale.",
        "items": [
            "Scoped API endpoints and webhook contracts.",
            "Integration SDK and verified skill marketplace model.",
            "Sandbox runner with run traces and observability.",
            "Export/import pipelines and enterprise controls (SSO/SCIM-ready path).",
        ],
    },
]
