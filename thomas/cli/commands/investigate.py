"""thomas investigate — background document analysis and evidence patterns.

Usage::

    thomas investigate run ./evidence --case-name "custody-2026" --profile codex
    thomas investigate status
    thomas investigate patterns
    thomas investigate timeline
    thomas investigate search "missed visitation"
    thomas investigate export --format md
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

log = logging.getLogger(__name__)


def _get_store():
    from thomas.investigation.store import InvestigationStore
    return InvestigationStore()


def _resolve_case(store, case_id: Optional[str]):
    """Resolve case by ID or return latest."""
    if case_id:
        case = store.get_case(case_id)
        if not case:
            click.echo(f"Case not found: {case_id}", err=True)
            raise SystemExit(1)
        return case
    case = store.get_latest_case()
    if not case:
        click.echo("No investigation cases found. Run 'thomas investigate run <folder>' first.", err=True)
        raise SystemExit(1)
    return case


def _ocr_augment(prompt: str, image_path) -> str:
    """Append OCR text to prompt as a fallback when vision model not available."""
    try:
        from thomas.vision.ocr_fallback import extract_text_from_images
        texts = extract_text_from_images([Path(image_path)])
        if texts and texts[0] and not texts[0].startswith("(OCR"):
            return prompt + "\n\nExtracted text from image (via OCR):\n---\n" + texts[0] + "\n---"
    except Exception:
        pass
    return prompt + "\n\n(Image could not be read — no vision model or OCR available.)"


async def _create_llm_call(config, model_profile: str):
    """Create a vision-aware LLM call function.

    Returns ``(llm, llm_call)`` where *llm* is the :class:`LLMClient`
    (caller must close it) and *llm_call* is an async callable matching
    the signature expected by :class:`DocumentAnalyzer`.
    """
    from thomas.core.llm import LLMClient

    llm = LLMClient(config, profile=model_profile)

    _vision_checked: dict = {}

    def _check_vision() -> bool:
        if "ok" not in _vision_checked:
            try:
                from thomas.vision.handler import model_supports_vision
                _vision_checked["ok"] = model_supports_vision(model_profile)
            except Exception:
                _vision_checked["ok"] = False
        return _vision_checked["ok"]

    async def llm_call(system: str, prompt: str, *, image_path=None) -> str:
        messages = [{"role": "system", "content": system}]

        if image_path and Path(image_path).is_file():
            if _check_vision():
                try:
                    from thomas.vision.handler import _read_image_b64
                    media_type, b64 = _read_image_b64(Path(image_path))
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{media_type};base64,{b64}",
                            }},
                        ],
                    })
                except Exception as img_err:
                    log.warning("Vision failed, falling back to OCR: %s", img_err)
                    prompt = _ocr_augment(prompt, image_path)
                    messages.append({"role": "user", "content": prompt})
            else:
                prompt = _ocr_augment(prompt, image_path)
                messages.append({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        response = await llm.chat(messages)
        return response.get("text", "") if isinstance(response, dict) else str(response)

    return llm, llm_call


@click.group()
def investigate():
    """Background document investigation and evidence analysis."""


@investigate.command("run")
@click.argument("folder_path", type=click.Path(exists=True, file_okay=False))
@click.option("--case-name", "case_name", default=None, help="Name for this investigation case.")
@click.option("--profile", default=None, help="LLM profile for analysis (e.g., codex, openai).")
@click.option("--resume", is_flag=True, help="Resume analysis on an existing case.")
@click.option("--no-synthesis", is_flag=True, help="Ingest and analyze only, skip pattern synthesis.")
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def investigate_run(ctx, folder_path, case_name, profile, resume, no_synthesis, verbose):
    """Ingest and analyze a folder of documents for evidence patterns."""
    from thomas.core.config import load_config
    from thomas.investigation.analyzer import DocumentAnalyzer
    from thomas.investigation.ingest import DocumentIngester, IngestResult
    from thomas.investigation.store import InvestigationStore
    from thomas.investigation.synthesizer import InvestigationSynthesizer

    folder = Path(folder_path).resolve()
    store = InvestigationStore()

    # Create or resume case
    if resume:
        case = store.find_case_by_source(str(folder))
        if not case:
            click.echo(f"No existing case for {folder}. Starting new case.", err=True)
            resume = False

    if not resume:
        name = case_name or folder.name
        case = store.create_case(name=name, source_path=str(folder))

    click.echo(f"[investigate] Case: {case.name} ({case.id})")
    click.echo(f"[investigate] Scanning {folder}...")

    # Phase 1: Ingest
    ingester = DocumentIngester(store)

    def on_ingest_progress(fname, current, total):
        if verbose:
            click.echo(f"[ingest    ] Processing: {fname} ({current}/{total})")

    result = ingester.ingest_folder(
        folder, case.id,
        skip_existing=True,
        on_progress=on_ingest_progress,
    )

    click.echo(
        f"[ingest    ] Done: {result.ingested} ingested, "
        f"{result.skipped_existing} skipped, {result.failed} failed "
        f"(of {result.total_files} files)"
    )
    if result.errors and verbose:
        for fp, err in result.errors[:5]:
            click.echo(f"[ingest    ] ERROR: {fp}: {err}")

    # Phase 2: Analyze (needs LLM)
    config = load_config()
    model_profile = profile or config.default_model or "local"

    async def run_analysis():
        llm, llm_call = await _create_llm_call(config, model_profile)

        try:
            analyzer = DocumentAnalyzer(store)

            def on_analyze_progress(fname, current, total, claims):
                click.echo(f"[analyze   ] {fname} ({current}/{total}) -> {claims} claims")

            batch = await analyzer.analyze_pending(
                case.id, llm_call, on_progress=on_analyze_progress
            )
            click.echo(
                f"[analyze   ] Done: {batch.analyzed} analyzed, "
                f"{batch.failed} failed, {batch.total_claims} total claims"
            )

            # Phase 3: Synthesize
            if not no_synthesis and batch.total_claims > 0:
                click.echo("[synthesis ] Detecting patterns...")
                synth = InvestigationSynthesizer(store)
                syn_result = await synth.run_full_synthesis(case.id, llm_call)
                click.echo(
                    f"[synthesis ] {syn_result.patterns_found} patterns, "
                    f"{syn_result.timeline_events} timeline events"
                )
                if syn_result.error:
                    click.echo(f"[synthesis ] Warning: {syn_result.error}", err=True)

        finally:
            try:
                await llm.close()
            except Exception:
                pass

    pending = store.get_pending_documents(case.id)
    if pending:
        image_count = sum(
            1 for d in pending
            if d.file_type == "image" or d.extraction_method == "image_placeholder"
        )
        text_count = len(pending) - image_count
        click.echo(f"[analyze   ] Analyzing {len(pending)} documents with profile '{model_profile}'...")
        if image_count:
            click.echo(f"[analyze   ] ({image_count} images will be transcribed first, {text_count} text docs)")
        asyncio.run(run_analysis())
    else:
        click.echo("[analyze   ] No pending documents to analyze.")

    # Summary
    summary = store.get_case_summary(case.id)
    click.echo(f"[done      ] {summary['documents']['total']} docs, "
               f"{summary['claims']} claims, {summary['patterns']} patterns, "
               f"{summary['timeline_events']} timeline events")
    click.echo(f"[done      ] Query with 'thomas investigate status' or ask Thomas in chat.")
    store.close()


@investigate.command("transcribe")
@click.option("--case-id", default=None)
@click.option("--profile", default=None, help="LLM profile for vision transcription.")
@click.option("--save-txt", is_flag=True, help="Write .txt file alongside each original image.")
@click.option("-v", "--verbose", is_flag=True)
def investigate_transcribe(case_id, profile, save_txt, verbose):
    """Transcribe image documents to readable plaintext via vision LLM.

    Converts screenshots, photos, and image files into searchable text
    transcripts. Transcripts are saved in the investigation database and
    optionally written as .txt files alongside the original images.
    """
    from thomas.core.config import load_config
    from thomas.investigation.analyzer import DocumentAnalyzer
    from thomas.investigation.store import InvestigationStore

    store = InvestigationStore()
    case = _resolve_case(store, case_id)

    # Find image documents needing transcription
    image_docs = store.get_image_documents(case.id, only_untranscribed=True)
    if not image_docs:
        click.echo("[transcribe] No image documents needing transcription.")
        store.close()
        return

    click.echo(f"[transcribe] Case: {case.name} ({case.id})")
    click.echo(f"[transcribe] {len(image_docs)} images to transcribe")

    config = load_config()
    model_profile = profile or config.default_model or "local"

    async def run_transcription():
        llm, llm_call = await _create_llm_call(config, model_profile)

        try:
            analyzer = DocumentAnalyzer(store)
            transcribed = 0
            total_chars = 0

            for i, doc in enumerate(image_docs):
                click.echo(
                    f"[transcribe] {doc.file_name} ({i + 1}/{len(image_docs)})...",
                    nl=False,
                )

                transcript = await analyzer.transcribe_image(
                    doc_id=doc.id,
                    file_path=doc.file_path,
                    file_name=doc.file_name,
                    llm_call=llm_call,
                )

                if transcript:
                    transcribed += 1
                    total_chars += len(transcript)
                    click.echo(f" {len(transcript):,} chars")

                    if save_txt:
                        txt_path = Path(doc.file_path).with_suffix(
                            Path(doc.file_path).suffix + ".txt"
                        )
                        try:
                            txt_path.write_text(transcript, encoding="utf-8")
                            if verbose:
                                click.echo(f"[transcribe]   -> {txt_path}")
                        except OSError as e:
                            click.echo(f" (save failed: {e})", err=True)
                else:
                    click.echo(" FAILED")

            click.echo(
                f"[transcribe] Done: {transcribed}/{len(image_docs)} transcribed, "
                f"{total_chars:,} total chars"
            )

        finally:
            try:
                await llm.close()
            except Exception:
                pass

    click.echo(f"[transcribe] Using profile '{model_profile}'...")
    asyncio.run(run_transcription())
    store.close()


@investigate.command("status")
@click.option("--case-id", default=None)
@click.option("--json", "as_json", is_flag=True)
def investigate_status(case_id, as_json):
    """Show investigation processing status."""
    store = _get_store()
    case = _resolve_case(store, case_id)
    summary = store.get_case_summary(case.id)
    store.close()

    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Case: {summary['case_name']} ({summary['case_id']})")
        click.echo(f"Source: {summary['source_path']}")
        docs = summary["documents"]
        click.echo(f"Documents: {docs['total']} total ({docs['analyzed']} analyzed, "
                    f"{docs['pending']} pending, {docs['failed']} failed)")
        click.echo(f"Claims: {summary['claims']}")
        click.echo(f"Patterns: {summary['patterns']}")
        click.echo(f"Timeline events: {summary['timeline_events']}")


@investigate.command("patterns")
@click.option("--case-id", default=None)
@click.option("--category", default=None)
@click.option("--min-strength", type=float, default=0.0)
@click.option("--json", "as_json", is_flag=True)
def investigate_patterns(case_id, category, min_strength, as_json):
    """Show detected patterns with evidence counts."""
    store = _get_store()
    case = _resolve_case(store, case_id)
    patterns = store.get_patterns(case.id, min_strength=min_strength, category=category)
    store.close()

    if as_json:
        click.echo(json.dumps(patterns, ensure_ascii=False, indent=2))
    else:
        if not patterns:
            click.echo("No patterns found. Run 'thomas investigate run <folder>' first.")
            return
        click.echo(f"Patterns for case: {case.name} ({len(patterns)} found)\n")
        for p in patterns:
            click.echo(f"  [{p['category']}] strength={p['strength']:.2f} "
                        f"evidence={p['evidence_count']}")
            click.echo(f"    {p['pattern_text']}")
            if p.get("first_seen") or p.get("last_seen"):
                click.echo(f"    Period: {p.get('first_seen', '?')} → {p.get('last_seen', '?')}")
            click.echo()


@investigate.command("timeline")
@click.option("--case-id", default=None)
@click.option("--start", "start_date", default=None, help="ISO date YYYY-MM-DD")
@click.option("--end", "end_date", default=None, help="ISO date YYYY-MM-DD")
@click.option("--json", "as_json", is_flag=True)
def investigate_timeline(case_id, start_date, end_date, as_json):
    """Show chronological timeline of events."""
    store = _get_store()
    case = _resolve_case(store, case_id)
    events = store.get_timeline(case.id, start_date=start_date, end_date=end_date)
    store.close()

    if as_json:
        click.echo(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        if not events:
            click.echo("No timeline events found.")
            return
        click.echo(f"Timeline for case: {case.name} ({len(events)} events)\n")
        for e in events:
            sev = f" [severity={e['severity']}]" if e.get("severity", 0) > 0 else ""
            cat = f" ({e['category']})" if e.get("category") else ""
            click.echo(f"  {e['event_date']}{cat}{sev}")
            click.echo(f"    {e['event_summary']}")


@investigate.command("search")
@click.argument("query")
@click.option("--case-id", default=None)
@click.option("--category", default=None)
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True)
def investigate_search(query, case_id, category, limit, as_json):
    """Search claims and documents by keyword."""
    store = _get_store()
    case = _resolve_case(store, case_id)
    claims = store.search_claims(query, case.id, category=category, limit=limit)
    store.close()

    if as_json:
        click.echo(json.dumps(claims, ensure_ascii=False, indent=2))
    else:
        if not claims:
            click.echo(f"No claims matching '{query}'.")
            return
        click.echo(f"Found {len(claims)} claims matching '{query}':\n")
        for c in claims:
            date_str = f" [{c.get('date_referenced', '')}]" if c.get("date_referenced") else ""
            sev = f" severity={c['severity']}" if c.get("severity", 0) > 0 else ""
            click.echo(f"  [{c['category']}]{date_str}{sev}")
            click.echo(f"    {c['claim_text']}")
            if c.get("quote_excerpt"):
                click.echo(f"    Source: \"{c['quote_excerpt']}\"")
            click.echo()


@investigate.command("cases")
@click.option("--json", "as_json", is_flag=True)
def investigate_cases(as_json):
    """List all investigation cases."""
    store = _get_store()
    cases = store.list_cases()
    store.close()

    if as_json:
        click.echo(json.dumps(
            [{"id": c.id, "name": c.name, "source_path": c.source_path, "status": c.status}
             for c in cases],
            ensure_ascii=False, indent=2,
        ))
    else:
        if not cases:
            click.echo("No investigation cases. Run 'thomas investigate run <folder>' to start.")
            return
        for c in cases:
            click.echo(f"  {c.id}  {c.name}  ({c.status})  {c.source_path}")


@investigate.command("export")
@click.option("--case-id", default=None)
@click.option("--format", "fmt", type=click.Choice(["json", "md", "court"]), default="md")
@click.option("--output", "output_path", type=click.Path(), default=None)
@click.option(
    "--copy-sources", "copy_sources_dir", type=click.Path(), default=None,
    help="Copy all referenced source files (images, etc.) to this directory alongside the report.",
)
def investigate_export(case_id, fmt, output_path, copy_sources_dir):
    """Export investigation findings to a file."""
    import shutil

    store = _get_store()
    case = _resolve_case(store, case_id)
    summary = store.get_case_summary(case.id)
    patterns = store.get_patterns(case.id)
    timeline = store.get_timeline(case.id)
    # Use source-linked claims for all formats
    claims = store.get_claims_with_source(case.id, limit=2000)
    documents = store.get_documents(case.id)
    store.close()

    if fmt == "json":
        data = {
            "case": {"id": case.id, "name": case.name, "source_path": case.source_path},
            "summary": summary,
            "patterns": patterns,
            "timeline": timeline,
            "claims": claims,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(data, ensure_ascii=False, indent=2)
    elif fmt == "court":
        content = _build_court_report(case, summary, patterns, timeline, claims, documents)
    else:
        # Markdown (simple) — now with source file references
        lines = [
            f"# Investigation Report: {case.name}",
            f"",
            f"**Case ID:** {case.id}",
            f"**Source:** {case.source_path}",
            f"**Documents:** {summary['documents']['total']} "
            f"({summary['documents']['analyzed']} analyzed)",
            f"**Claims:** {summary['claims']}",
            f"**Exported:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "---",
            "",
            "## Patterns",
            "",
        ]
        for p in patterns:
            lines.append(f"### {p['pattern_text']}")
            lines.append(f"- **Category:** {p['category']}")
            lines.append(f"- **Strength:** {p['strength']:.2f}")
            lines.append(f"- **Evidence:** {p['evidence_count']} claims")
            if p.get("first_seen") or p.get("last_seen"):
                lines.append(f"- **Period:** {p.get('first_seen', '?')} → {p.get('last_seen', '?')}")
            lines.append("")

        lines.extend(["---", "", "## Timeline", ""])
        for e in timeline:
            sev = f" (severity {e['severity']})" if e.get("severity", 0) > 0 else ""
            lines.append(f"- **{e['event_date']}**{sev}: {e['event_summary']}")
        lines.append("")

        lines.extend(["---", "", "## All Claims", ""])
        for c in claims:
            date_str = f" [{c.get('date_referenced', '')}]" if c.get("date_referenced") else ""
            src = f" *(Source: {c['source_file_name']})*" if c.get("source_file_name") else ""
            lines.append(f"- **[{c['category']}]**{date_str} {c['claim_text']}{src}")
            if c.get("quote_excerpt"):
                lines.append(f"  > {c['quote_excerpt']}")

        content = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        click.echo(f"Exported to {output_path}")
    else:
        click.echo(content)

    # Copy source files if requested
    if copy_sources_dir:
        sources_dir = Path(copy_sources_dir)
        sources_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for doc in documents:
            src = Path(doc.file_path)
            if src.is_file():
                dest = sources_dir / src.name
                # Avoid name collisions
                if dest.exists():
                    dest = sources_dir / f"{src.stem}_{doc.id}{src.suffix}"
                try:
                    shutil.copy2(str(src), str(dest))
                    copied += 1
                except Exception as e:
                    click.echo(f"[export] Warning: could not copy {src.name}: {e}", err=True)
        click.echo(f"[export] Copied {copied} source files to {sources_dir}")


def _build_court_report(case, summary, patterns, timeline, claims, documents) -> str:
    """Generate a structured court-ready evidence report."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build document index (id → index number)
    doc_index: Dict[int, int] = {}
    for idx, d in enumerate(documents, 1):
        doc_index[d.id] = idx

    # Compute date range from claims
    dated = [c.get("date_referenced") for c in claims if c.get("date_referenced")]
    date_range = f"{min(dated)} to {max(dated)}" if dated else "undetermined"

    # Group claims by doc_id for counting
    claims_per_doc: Dict[int, int] = {}
    for c in claims:
        did = c.get("doc_id", 0)
        claims_per_doc[did] = claims_per_doc.get(did, 0) + 1

    lines: List[str] = []

    # ── Header ──
    lines.extend([
        f"# Evidence Analysis Report: {case.name}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| **Report Date** | {now_str} |",
        f"| **Evidence Period** | {date_range} |",
        f"| **Documents Analyzed** | {summary['documents']['analyzed']} of {summary['documents']['total']} |",
        f"| **Evidence Claims** | {summary['claims']} |",
        f"| **Patterns Detected** | {summary['patterns']} |",
        f"| **Timeline Events** | {summary['timeline_events']} |",
        "",
    ])

    # ── Executive Summary ──
    lines.extend(["## Executive Summary", ""])
    lines.append(
        f"Analysis of {summary['documents']['total']} documents spanning {date_range} "
        f"identified {summary['patterns']} recurring behavioral patterns "
        f"across {summary['claims']} individual evidence claims."
    )
    lines.append("")
    top = patterns[:5]
    if top:
        lines.append("**Key Findings:**")
        lines.append("")
        for p in top:
            period = ""
            if p.get("first_seen") and p.get("last_seen"):
                period = f" ({p['first_seen']} to {p['last_seen']})"
            elif p.get("first_seen"):
                period = f" (from {p['first_seen']})"
            lines.append(
                f"- **{p['pattern_text']}** — "
                f"supported by {p['evidence_count']} pieces of evidence{period} "
                f"(strength: {p['strength']:.1f})"
            )
        lines.append("")

    # ── Evidence by Category ──
    categories = ["communication", "visitation", "safety", "emotional",
                   "financial", "legal", "medical", "other"]
    lines.extend(["---", "", "## Evidence Analysis by Category", ""])

    for cat in categories:
        cat_patterns = [p for p in patterns if p.get("category") == cat]
        cat_claims = [c for c in claims if c.get("category") == cat]
        if not cat_patterns and not cat_claims:
            continue

        lines.append(f"### {cat.title()}")
        lines.append(f"*{len(cat_claims)} claims, {len(cat_patterns)} patterns*")
        lines.append("")

        for p in cat_patterns:
            lines.append(f"**Pattern: {p['pattern_text']}**")
            lines.append(f"- Strength: {p['strength']:.1f} | Evidence: {p['evidence_count']} claims")
            if p.get("first_seen") or p.get("last_seen"):
                lines.append(f"- Period: {p.get('first_seen', '?')} to {p.get('last_seen', '?')}")

            # Show supporting claims with source citations
            cited_ids = set(p.get("claim_ids", []))
            supporting = [c for c in cat_claims if c.get("id") in cited_ids][:5]
            if supporting:
                lines.append("- Supporting evidence:")
                for c in supporting:
                    dnum = doc_index.get(c.get("doc_id", 0), "?")
                    src_name = c.get("source_file_name", "")
                    src_ref = f" ({src_name})" if src_name else ""
                    date_str = f" [{c['date_referenced']}]" if c.get("date_referenced") else ""
                    sev = f" (severity {c['severity']})" if c.get("severity", 0) > 2 else ""
                    lines.append(f"  - {c['claim_text']}{date_str}{sev} *(Doc #{dnum}{src_ref})*")
                    if c.get("quote_excerpt"):
                        lines.append(f"    > \"{c['quote_excerpt']}\"")
            lines.append("")

        # Show remaining uncited high-severity claims
        cited_all = set()
        for p in cat_patterns:
            cited_all.update(p.get("claim_ids", []))
        uncited_high = [
            c for c in cat_claims
            if c.get("id") not in cited_all and c.get("severity", 0) >= 3
        ]
        if uncited_high:
            lines.append(f"**Additional high-severity claims ({cat.title()}):**")
            for c in uncited_high[:10]:
                dnum = doc_index.get(c.get("doc_id", 0), "?")
                src_name = c.get("source_file_name", "")
                src_ref = f" ({src_name})" if src_name else ""
                date_str = f" [{c['date_referenced']}]" if c.get("date_referenced") else ""
                lines.append(
                    f"- {c['claim_text']}{date_str} — severity {c['severity']} "
                    f"*(Doc #{dnum}{src_ref})*"
                )
                if c.get("quote_excerpt"):
                    lines.append(f"  > \"{c['quote_excerpt']}\"")
            lines.append("")

    # ── Timeline ──
    lines.extend(["---", "", "## Chronological Timeline", ""])
    if timeline:
        for e in timeline:
            sev_marker = ""
            if e.get("severity", 0) >= 4:
                sev_marker = " [HIGH SEVERITY]"
            elif e.get("severity", 0) >= 2:
                sev_marker = " [NOTABLE]"
            lines.append(f"- **{e['event_date']}**{sev_marker}: {e['event_summary']}")
    else:
        lines.append("*No dated events extracted.*")
    lines.append("")

    # ── Document Index ──
    lines.extend(["---", "", "## Document Index", ""])
    lines.append("| # | File | Type | Claims | Source Path |")
    lines.append("| --- | --- | --- | --- | --- |")
    for idx, d in enumerate(documents, 1):
        count = claims_per_doc.get(d.id, 0)
        lines.append(f"| {idx} | {d.file_name} | {d.file_type} | {count} | {d.file_path} |")
    lines.append("")

    # ── Source Transcripts (image documents with transcribed text) ──
    image_docs = [d for d in documents if d.file_type == "image" and d.extracted_text]
    if image_docs:
        lines.extend(["---", "", "## Source Transcripts", ""])
        lines.append(
            "*Below are transcripts of image evidence (screenshots, photos). "
            "Each transcript was extracted from the original image file listed.*"
        )
        lines.append("")
        for d in image_docs:
            idx = doc_index.get(d.id, "?")
            lines.append(f"### Doc #{idx}: {d.file_name}")
            lines.append(f"*Original image: `{d.file_path}`*")
            lines.append("")
            # Show transcript in a blockquote for readability
            for line in (d.extracted_text or "").split("\n"):
                lines.append(f"> {line}")
            lines.append("")

    lines.extend([
        "---",
        "",
        f"*Report generated {now_str}. "
        f"This report was produced by automated document analysis and should be reviewed for accuracy.*",
    ])

    return "\n".join(lines)


def register_investigate_commands(cli):
    """Register the investigate command group with the CLI."""
    cli.add_command(investigate, "investigate")
