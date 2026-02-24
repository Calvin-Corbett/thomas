"""Per-document LLM analysis — extract structured claims from document text.

Sends each document's text to the LLM with a structured extraction prompt.
Returns JSON claims (factual assertions with category, date, people, sentiment, etc.).
Chunks large documents to fit context windows.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pathlib import Path

from thomas.investigation.prompts import (
    DOCUMENT_ANALYSIS_SYSTEM,
    DOCUMENT_ANALYSIS_USER,
    IMAGE_ANALYSIS_SYSTEM,
    IMAGE_ANALYSIS_USER,
    IMAGE_TRANSCRIPTION_SYSTEM,
    IMAGE_TRANSCRIPTION_USER,
)
from thomas.investigation.store import Claim, InvestigationStore

log = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    doc_id: int
    claims_extracted: int = 0
    error: Optional[str] = None


@dataclass
class BatchAnalysisResult:
    total: int = 0
    analyzed: int = 0
    failed: int = 0
    total_claims: int = 0
    errors: List[str] = field(default_factory=list)


class DocumentAnalyzer:
    """Analyze documents via LLM to extract structured claims."""

    def __init__(
        self,
        store: InvestigationStore,
        *,
        max_chunk_chars: int = 20_000,
        max_claims_per_doc: int = 50,
    ):
        self.store = store
        self.max_chunk_chars = max_chunk_chars
        self.max_claims_per_doc = max_claims_per_doc

    async def analyze_document(
        self,
        doc_id: int,
        case_id: str,
        text: str,
        file_name: str,
        file_type: str,
        llm_call: Callable,
    ) -> AnalysisResult:
        """Analyze a single document. Send text to LLM, parse claims."""
        result = AnalysisResult(doc_id=doc_id)

        try:
            chunks = self._chunk_text(text)
            all_claims: List[Dict[str, Any]] = []

            for chunk in chunks:
                prompt = DOCUMENT_ANALYSIS_USER.format(
                    file_name=file_name,
                    file_type=file_type,
                    text_chunk=chunk,
                )

                response = await llm_call(
                    system=DOCUMENT_ANALYSIS_SYSTEM,
                    prompt=prompt,
                )

                parsed = self._parse_claims_response(response)
                all_claims.extend(parsed)

                if len(all_claims) >= self.max_claims_per_doc:
                    all_claims = all_claims[: self.max_claims_per_doc]
                    break

            result.claims_extracted = self._store_parsed_claims(case_id, doc_id, all_claims)

            self.store.mark_document_analyzed(doc_id)

        except Exception as exc:
            log.warning("Analysis failed for doc %d: %s", doc_id, exc)
            result.error = str(exc)
            self.store.mark_document_failed(doc_id, str(exc))

        return result

    async def transcribe_image(
        self,
        doc_id: int,
        file_path: str,
        file_name: str,
        llm_call: Callable,
    ) -> Optional[str]:
        """Phase 1: Transcribe an image to readable plaintext via vision LLM.

        Returns the transcript text, or None on failure.
        Saves the transcript to ``document.extracted_text`` in the store.
        """
        try:
            prompt = IMAGE_TRANSCRIPTION_USER.format(file_name=file_name)
            image_path = Path(file_path) if file_path else None

            transcript = await llm_call(
                system=IMAGE_TRANSCRIPTION_SYSTEM,
                prompt=prompt,
                image_path=image_path,
            )

            if transcript and transcript.strip():
                self.store.update_document_text(
                    doc_id, transcript.strip(), extraction_method="vision_transcription",
                )
                log.info("Transcribed doc %d (%s): %d chars", doc_id, file_name, len(transcript))
                return transcript.strip()
            else:
                log.warning("Empty transcript for doc %d (%s)", doc_id, file_name)
                return None

        except Exception as exc:
            log.warning("Transcription failed for doc %d: %s", doc_id, exc)
            return None

    async def analyze_image_document(
        self,
        doc_id: int,
        case_id: str,
        file_path: str,
        file_name: str,
        llm_call: Callable,
    ) -> AnalysisResult:
        """Two-phase image analysis: transcribe, then extract claims.

        Phase 1 — Transcribe: vision LLM reads image → plain text transcript,
        saved to ``document.extracted_text`` (searchable via FTS).

        Phase 2 — Extract claims: text LLM extracts structured claims from the
        transcript (same code path as any text document).

        The original image path stays linked via ``document.file_path`` for
        proof traceability.
        """
        result = AnalysisResult(doc_id=doc_id)

        try:
            # Phase 1: Transcribe image → plaintext
            transcript = await self.transcribe_image(
                doc_id=doc_id,
                file_path=file_path,
                file_name=file_name,
                llm_call=llm_call,
            )

            if transcript:
                # Phase 2: Extract claims from transcript (same as text docs)
                chunks = self._chunk_text(transcript)
                all_claims: List[Dict[str, Any]] = []

                for chunk in chunks:
                    prompt = DOCUMENT_ANALYSIS_USER.format(
                        file_name=file_name,
                        file_type="image_transcript",
                        text_chunk=chunk,
                    )

                    response = await llm_call(
                        system=DOCUMENT_ANALYSIS_SYSTEM,
                        prompt=prompt,
                    )

                    parsed = self._parse_claims_response(response)
                    all_claims.extend(parsed)

                    if len(all_claims) >= self.max_claims_per_doc:
                        all_claims = all_claims[: self.max_claims_per_doc]
                        break

                result.claims_extracted = self._store_parsed_claims(case_id, doc_id, all_claims)
            else:
                # Transcription failed — fall back to direct vision claim extraction
                log.info("Falling back to direct vision analysis for doc %d", doc_id)
                prompt = IMAGE_ANALYSIS_USER.format(file_name=file_name)
                image_path = Path(file_path) if file_path else None

                response = await llm_call(
                    system=IMAGE_ANALYSIS_SYSTEM,
                    prompt=prompt,
                    image_path=image_path,
                )

                all_claims = self._parse_claims_response(response)
                if len(all_claims) > self.max_claims_per_doc:
                    all_claims = all_claims[: self.max_claims_per_doc]

                result.claims_extracted = self._store_parsed_claims(case_id, doc_id, all_claims)

            self.store.mark_document_analyzed(doc_id)

        except Exception as exc:
            log.warning("Image analysis failed for doc %d: %s", doc_id, exc)
            result.error = str(exc)
            self.store.mark_document_failed(doc_id, str(exc))

        return result

    async def analyze_pending(
        self,
        case_id: str,
        llm_call: Callable,
        *,
        on_progress: Optional[Callable[[str, int, int, int], None]] = None,
    ) -> BatchAnalysisResult:
        """Analyze all pending documents in a case."""
        batch = BatchAnalysisResult()
        docs = self.store.get_pending_documents(case_id)
        batch.total = len(docs)

        for i, doc in enumerate(docs):
            # Route image documents to vision analysis
            if doc.file_type == "image" or doc.extraction_method == "image_placeholder":
                result = await self.analyze_image_document(
                    doc_id=doc.id,
                    case_id=case_id,
                    file_path=doc.file_path,
                    file_name=doc.file_name,
                    llm_call=llm_call,
                )
            elif not doc.extracted_text:
                # Empty docs with no text and not images — skip
                self.store.mark_document_analyzed(doc.id)
                batch.analyzed += 1
                if on_progress:
                    on_progress(doc.file_name, i + 1, batch.total, 0)
                continue
            else:
                result = await self.analyze_document(
                    doc_id=doc.id,
                    case_id=case_id,
                    text=doc.extracted_text,
                    file_name=doc.file_name,
                    file_type=doc.file_type,
                    llm_call=llm_call,
                )

            if result.error:
                batch.failed += 1
                batch.errors.append(f"{doc.file_name}: {result.error}")
            else:
                batch.analyzed += 1
                batch.total_claims += result.claims_extracted

            if on_progress:
                on_progress(doc.file_name, i + 1, batch.total, result.claims_extracted)

        return batch

    # -- Claim storage -------------------------------------------------------

    def _store_parsed_claims(
        self,
        case_id: str,
        doc_id: int,
        all_claims: List[Dict[str, Any]],
    ) -> int:
        """Build Claim objects from parsed LLM data and store them.

        Returns the number of claims actually stored (skips empty claim_text).
        """
        count = 0
        for claim_data in all_claims:
            claim = Claim(
                case_id=case_id,
                doc_id=doc_id,
                claim_text=claim_data.get("claim_text", ""),
                category=claim_data.get("category", "other"),
                subcategory=claim_data.get("subcategory"),
                date_referenced=claim_data.get("date_referenced"),
                date_precision=claim_data.get("date_precision", "unknown"),
                people_involved=claim_data.get("people_involved", []),
                sentiment=claim_data.get("sentiment", "neutral"),
                severity=int(claim_data.get("severity", 0)),
                confidence=float(claim_data.get("confidence", 0.7)),
                quote_excerpt=claim_data.get("quote_excerpt"),
            )
            if claim.claim_text.strip():
                self.store.add_claim(claim)
                count += 1
        return count

    # -- Text chunking -------------------------------------------------------

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into LLM-friendly chunks."""
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks: List[str] = []
        # Try to split on paragraph boundaries
        paragraphs = text.split("\n\n")
        current: List[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 2 > self.max_chunk_chars and current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(para)
            current_len += len(para) + 2

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    # -- Response parsing ----------------------------------------------------

    @staticmethod
    def _parse_claims_response(response: str) -> List[Dict[str, Any]]:
        """Parse JSON claims from LLM response. Robust to malformed JSON."""
        if not response:
            return []

        # Try direct JSON parse first
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "claims" in data:
                return data["claims"]
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in the response
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # Try to find individual JSON objects
        objects: List[Dict[str, Any]] = []
        for m in re.finditer(r"\{[^{}]+\}", response):
            try:
                obj = json.loads(m.group(0))
                if isinstance(obj, dict) and "claim_text" in obj:
                    objects.append(obj)
            except json.JSONDecodeError:
                continue

        return objects
