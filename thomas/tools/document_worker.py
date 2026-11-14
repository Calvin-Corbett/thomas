"""Bounded document decoding for chat uploads and authorized PDF tool reads."""

from __future__ import annotations

import base64
import binascii
import json
import sys
from pathlib import Path
from typing import Any

from thomas.tools.bounded_worker import WorkerFailure, run_json_worker
from thomas.tools.file_readers import UPLOAD_MAX_BYTES, DocumentReadError, extract_uploaded_document


async def read_pdf_document(
    *,
    path: Path | None = None,
    raw: bytes | None = None,
    max_pages: int | None = None,
    page_markers: bool = False,
) -> dict[str, Any]:
    """Read an already authorized path or bounded response in a killable child.

    Callers retain path/host authorization. Resolve local paths before the child
    changes working directory; neither file reading nor PDF parsing runs on the
    event loop. A failed decode has no document and must not be cached as text.
    """
    payload: dict[str, Any] = {
        "name": path.name if path is not None else "document.pdf",
        "content_type": "application/pdf",
        "pdf_max_pages": max_pages,
        "pdf_page_markers": page_markers,
    }
    try:
        if path is not None:
            payload["path"] = str(path.resolve())
        elif raw is not None and 0 < len(raw) <= UPLOAD_MAX_BYTES:
            payload["data"] = base64.b64encode(raw).decode("ascii")
        else:
            raise DocumentReadError("Choose a non-empty document no larger than 5 MB.")
        return await run_json_worker("thomas.tools.document_worker", payload)
    except (WorkerFailure, DocumentReadError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if "path" in payload:
            with Path(payload["path"]).open("rb") as source:
                raw = source.read(UPLOAD_MAX_BYTES + 1)
        else:
            raw = base64.b64decode(payload["data"], validate=True)
        document = extract_uploaded_document(
            raw,
            payload["name"],
            payload.get("content_type", ""),
            pdf_max_pages=payload.get("pdf_max_pages"),
            pdf_page_markers=bool(payload.get("pdf_page_markers", False)),
        )
        result = {"ok": True, "document": document}
    except (DocumentReadError, binascii.Error, ValueError, OSError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
