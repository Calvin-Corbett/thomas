"""Folding attachments into a chat prompt -- and naming whatever did not fit.

Moved verbatim out of chat_v2.py, which had grown past the monolith guard's
soft limit. Behaviour is unchanged; the point of the move is that these are
one job (assemble the outgoing prompt from what the user attached), and they
sit beside chat_page_context.py, which does the same job for the tab the user
is looking at.

The through-line in both functions: anything that will NOT reach the model is
said out loud in the prompt. A dropped attachment that nobody mentions turns
into an answer that quietly ignored a file the composer already drew a chip
for.
"""

from __future__ import annotations

from typing import Any

# How much attached-document text can ride along with one message. A budget, not a
# file count: nine short notes are cheap and two large exports are not, and the old
# `docs[:6]` could drop a one-line file while admitting six huge ones. Anything past
# this is named in the prompt rather than silently discarded.
ATTACHED_DOCS_BUDGET = 300_000
# Images are metered per image on vision calls, so this ceiling is real. Extras are
# named, not hidden.
ATTACHED_IMAGE_LIMIT = 4


def prompt_with_documents(prompt: str, docs: Any) -> str:
    """Fold attached documents into the prompt, naming any that did not fit.

    Attachments used to stop at `docs[:6]`, so a seventh file was deleted from the
    message before the model ever saw it -- no marker, no mention, and the composer
    had already drawn a chip for it. Attach nine, get answered about six, with
    nothing to suggest the other three existed.

    The real limit was never a file count, it is how much text can be carried, so
    that is what is measured here. Anything that will not fit is NAMED: the
    per-document truncation below has always said "... (truncated)" out loud, and
    there is no reason the whole-file case should be quieter than the partial one.
    """

    if not isinstance(docs, list) or not docs:
        return prompt
    blocks: list[str] = []
    used = 0
    omitted: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        name = str(doc.get("name") or "document")
        content = str(doc.get("text") or "")
        if not content.strip():
            continue
        if len(content) > 50_000:
            content = content[:50_000] + "\n... (truncated)"
        # Always admit the first document, so one oversized file still arrives
        # (truncated and labelled) rather than the message losing every attachment.
        if blocks and used + len(content) > ATTACHED_DOCS_BUDGET:
            omitted.append(name)
            continue
        used += len(content)
        blocks.append(f"--- {name} ---\n{content}\n--- end {name} ---")
    if blocks:
        prompt = (prompt.rstrip() + "\n\n[Attached documents]\n" + "\n\n".join(blocks)).strip()
    if omitted:
        prompt = (
            prompt.rstrip()
            + "\n\n[Not attached: "
            + ", ".join(omitted)
            + " — these did not fit and were NOT read. Say so if they matter to the answer.]"
        )
    return prompt


def images_for_request(prompt: str, images: Any) -> tuple[list[dict[str, Any]], str]:
    """Vision blocks for the request, plus a prompt naming any image not sent.

    Same silence as the documents: a fifth image was dropped without a word. The
    cap stays -- vision calls are metered per image, so this ceiling is real rather
    than arbitrary -- but a dropped image is named so the answer can admit it did
    not look at everything.
    """

    image_data: list[dict[str, Any]] = []
    if not isinstance(images, list) or not images:
        return image_data, prompt
    for img in images[:ATTACHED_IMAGE_LIMIT]:
        if isinstance(img, dict) and img.get("data_url"):
            image_data.append({"type": "image_url", "image_url": {"url": str(img["data_url"])}})
    unseen = [
        str(img.get("name") or f"image {n}")
        for n, img in enumerate(images[ATTACHED_IMAGE_LIMIT:], ATTACHED_IMAGE_LIMIT + 1)
        if isinstance(img, dict)
    ]
    if unseen:
        prompt = (
            prompt.rstrip()
            + "\n\n[Not attached: "
            + ", ".join(unseen)
            + f" — only the first {ATTACHED_IMAGE_LIMIT} images were sent. Say so if they matter.]"
        )
    return image_data, prompt
