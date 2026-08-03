"""Every file you attach either reaches the model or gets named as missing.

`docs[:6]` and `images[:4]` deleted the extras before the model saw the message.
No marker, no mention -- and the composer had already drawn a chip for each one.
Attach nine documents, get answered about six, with nothing to suggest the other
three existed. That is the worst version of the complaint behind this work: the
owner's own request reshaped before anyone reads it.

Two things are pinned here, and both matter. A small attachment must never be
dropped for being seventh -- the limit was never a file count, it is how much text
can be carried. And an attachment that genuinely will not fit must be NAMED, the
same way the per-document truncation has always printed "... (truncated)" rather
than quietly shortening the file.
"""

from __future__ import annotations

from thomas.server.routes.chat_v2 import (
    _ATTACHED_DOCS_BUDGET,
    _ATTACHED_IMAGE_LIMIT,
    _images_for_request,
    _prompt_with_documents,
)


def _docs(count: int, size: int = 20) -> list[dict[str, str]]:
    return [{"name": f"note{n}.txt", "text": "x" * size} for n in range(count)]


def test_a_seventh_small_document_still_reaches_the_model() -> None:
    """The regression that started this: nine small files, six read."""

    prompt = _prompt_with_documents("summarise these", _docs(9))

    for n in range(9):
        assert f"note{n}.txt" in prompt, f"note{n}.txt was dropped from the message"
    assert prompt.count("--- end ") == 9
    assert "Not attached" not in prompt, "nothing was too big; nothing should be reported missing"


def test_a_document_that_cannot_fit_is_named_rather_than_deleted() -> None:
    oversized = [{"name": f"export{n}.csv", "text": "y" * 40_000} for n in range(12)]

    prompt = _prompt_with_documents("compare these", oversized)

    assert "Not attached" in prompt, "documents were dropped without a word"
    assert "NOT read" in prompt, "the note must say the content was not read, not merely list names"
    named = [f"export{n}.csv" for n in range(12) if f"export{n}.csv" in prompt]
    assert len(named) == 12, "a dropped file was neither included nor named"


def test_one_oversized_document_still_arrives() -> None:
    """A single file larger than the whole budget must not leave the message empty:
    it arrives truncated and labelled, which is what the 50k trim already did."""

    prompt = _prompt_with_documents("read this", [{"name": "huge.txt", "text": "z" * (_ATTACHED_DOCS_BUDGET * 2)}])

    assert "huge.txt" in prompt
    assert "(truncated)" in prompt, "the content was shortened without saying so"
    assert "Not attached" not in prompt, "the only attachment was reported as missing"


def test_extra_images_are_named_even_though_the_cap_is_real() -> None:
    """Vision calls are metered per image, so the ceiling stays. Silence does not."""

    images = [{"data_url": f"data:image/png;base64,{n}", "name": f"shot{n}.png"} for n in range(6)]

    blocks, prompt = _images_for_request("what do these show", images)

    assert len(blocks) == _ATTACHED_IMAGE_LIMIT, "the metered cap was removed, not just made honest"
    assert "shot4.png" in prompt and "shot5.png" in prompt, "dropped images were not named"
    assert "Not attached" in prompt


def test_nothing_attached_leaves_the_message_alone() -> None:
    assert _prompt_with_documents("plain question", []) == "plain question"
    assert _images_for_request("plain question", []) == ([], "plain question")
    # Malformed entries must not invent an attachment note either.
    assert "Not attached" not in _prompt_with_documents("q", [{"name": "empty.txt", "text": "   "}])
