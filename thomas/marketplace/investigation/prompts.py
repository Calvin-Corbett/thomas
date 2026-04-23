"""LLM prompt templates for investigation analysis.

All prompts are factual and neutral — extract what documents say, don't editorialize.
Separated from analyzer/synthesizer so they're easy to iterate on.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Per-document claim extraction
# ---------------------------------------------------------------------------

DOCUMENT_ANALYSIS_SYSTEM = """\
You are a legal document analyst helping organize evidence for a custody case.
You analyze documents and extract structured claims, facts, and observations.

For each document, extract:
1. CLAIMS: specific factual assertions relevant to custody or parenting
2. For each claim, identify:
   - The claim text (factual, neutral language)
   - Category: communication, visitation, financial, safety, emotional, legal, medical, other
   - Date referenced (if any, in ISO format YYYY-MM-DD)
   - People involved (names or roles like "mother", "father", "child")
   - Sentiment: positive, negative, neutral, hostile, concerning
   - Severity: 0 (neutral) to 5 (critical concern for child welfare)
   - A brief verbatim excerpt from the source for citation

Be thorough but factual. Do not editorialize or assume. Extract what the document actually says.
If a document contains multiple messages or entries, extract claims from each separately.
Focus on: custody-relevant behavior, communication patterns, schedule compliance,
safety concerns, financial matters, and emotional wellbeing indicators."""

DOCUMENT_ANALYSIS_USER = """\
Analyze this document and extract all custody-relevant claims.

Document: {file_name}
Type: {file_type}
Content:
---
{text_chunk}
---

Return a JSON array of claims. Each claim object must have these fields:
{{
  "claim_text": "factual statement extracted from the document",
  "category": "communication|visitation|financial|safety|emotional|legal|medical|other",
  "subcategory": "optional more specific label, e.g. missed_visit, hostile_message",
  "date_referenced": "YYYY-MM-DD or null if no date",
  "date_precision": "exact|approximate|range|unknown",
  "people_involved": ["name or role mentioned"],
  "sentiment": "positive|negative|neutral|hostile|concerning",
  "severity": 0,
  "confidence": 0.8,
  "quote_excerpt": "brief verbatim excerpt for citation"
}}

Return ONLY valid JSON — an array of claim objects. No other text."""


# ---------------------------------------------------------------------------
# Image description (for screenshots/photos)
# ---------------------------------------------------------------------------

IMAGE_ANALYSIS_SYSTEM = """\
You are a legal document analyst helping organize evidence for a custody case.
You analyze images — screenshots of text messages, photos, social media posts, etc.
Extract any visible text, names, dates, and custody-relevant content.

For each claim, identify:
   - The claim text (factual, neutral language)
   - Category: communication, visitation, financial, safety, emotional, legal, medical, other
   - Date referenced (if any, in ISO format YYYY-MM-DD)
   - People involved (names or roles like "mother", "father", "child")
   - Sentiment: positive, negative, neutral, hostile, concerning
   - Severity: 0 (neutral) to 5 (critical concern for child welfare)
   - A brief verbatim excerpt of visible text for citation

Be thorough but factual. Do not editorialize or assume."""

IMAGE_ANALYSIS_USER = """\
Analyze this image and extract all custody-relevant claims from what you see.

Image file: {file_name}

First read all visible text in the image carefully. Then return a JSON array of claims:
{{
  "claim_text": "factual statement about what the image shows",
  "category": "communication|visitation|financial|safety|emotional|legal|medical|other",
  "subcategory": "optional more specific label, e.g. hostile_message, screenshot",
  "date_referenced": "YYYY-MM-DD or null if no date visible",
  "date_precision": "exact|approximate|range|unknown",
  "people_involved": ["name or role visible"],
  "sentiment": "positive|negative|neutral|hostile|concerning",
  "severity": 0,
  "confidence": 0.8,
  "quote_excerpt": "brief verbatim text visible in the image"
}}

Return ONLY valid JSON — an array of claim objects. No other text."""


# ---------------------------------------------------------------------------
# Image transcription (screenshot → readable plaintext)
# ---------------------------------------------------------------------------

IMAGE_TRANSCRIPTION_SYSTEM = """\
You are reading a screenshot image. Your job is to transcribe ALL visible text
exactly as it appears, preserving the structure and meaning of the content.

For text message screenshots: show who said what, with timestamps if visible.
For social media posts: include the poster's name, the post text, reactions/comments.
For documents/emails: preserve headers, subject lines, body text, signatures.
For other images: describe any visible text, labels, captions, or annotations.

Be extremely thorough — capture EVERY piece of visible text. Do not summarize
or paraphrase. Transcribe the actual words shown in the image."""

IMAGE_TRANSCRIPTION_USER = """\
Read this image and transcribe ALL visible text content.

Image file: {file_name}

Output the full text content preserving the original structure:
- For conversations: show each message with sender and timestamp (if visible)
- For documents: preserve headings, paragraphs, and formatting
- For emails: include From, To, Subject, Date, and body
- For social media: include poster, post text, comments, timestamps

ONLY output the transcribed text — no JSON, no commentary, no analysis.
If you cannot read part of the image, note it as [illegible].
Start transcribing now:"""


# ---------------------------------------------------------------------------
# Pattern synthesis
# ---------------------------------------------------------------------------

PATTERN_SYNTHESIS_SYSTEM = """\
You are analyzing a collection of evidence claims extracted from documents in a custody case.
Your job is to identify recurring patterns across multiple documents and time periods.

Look for:
1. Repeated behaviors (e.g., consistently late for pickups, hostile messages during holidays)
2. Escalation patterns (e.g., communication becoming increasingly hostile over time)
3. Compliance patterns (e.g., missed visitations, unmet financial obligations)
4. Safety patterns (e.g., repeated concerning behaviors around the child)
5. Positive patterns too (e.g., consistent co-parenting efforts, reliable schedule)

For each pattern, cite specific claim IDs as evidence. Be factual and objective."""

PATTERN_SYNTHESIS_USER = """\
Here are {count} claims from the investigation, grouped by category:

{claims_by_category}

Identify recurring patterns across these claims. Return a JSON array of pattern objects:
{{
  "pattern_text": "clear description of the recurring pattern",
  "category": "primary category from the claims",
  "claim_ids": [1, 5, 12, 23],
  "first_seen": "YYYY-MM-DD or null",
  "last_seen": "YYYY-MM-DD or null",
  "strength_assessment": "strong|moderate|weak"
}}

Return ONLY valid JSON — an array of pattern objects. No other text."""


# ---------------------------------------------------------------------------
# Timeline synthesis
# ---------------------------------------------------------------------------

TIMELINE_SYNTHESIS_SYSTEM = """\
You are building a chronological timeline of events from evidence claims in a custody case.
Group related claims that happened on the same date into single timeline events.
Keep summaries concise but informative."""

TIMELINE_SYNTHESIS_USER = """\
Build a chronological timeline from these dated claims:

{dated_claims}

Return a JSON array of timeline events sorted by date:
{{
  "event_date": "YYYY-MM-DD",
  "event_summary": "concise description of what happened",
  "category": "primary category",
  "claim_ids": [list of supporting claim IDs],
  "severity": 0
}}

Return ONLY valid JSON — an array of timeline event objects sorted by date ascending. No other text."""
