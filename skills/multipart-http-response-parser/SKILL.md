---
name: multipart-http-response-parser
description: Implement multipart HTTP response parsing APIs with Content-Type boundary validation, MIME delimiter framing, CRLF/LF/CR streaming chunks, part headers, continuations, duplicate headers, DecodingError, StreamConsumed, sync iter_multipart, async aiter_multipart, and raw response stream closure.
---

# Multipart HTTP Response Parser

Use this skill when adding or fixing multipart response parsing, MIME boundary scanners, HTTP streaming body iterators, or sync/async APIs that yield parsed response parts.

## Workflow
1. Trace the response body lifecycle first: in-memory bytes, sync streaming, async streaming, decoder layers, stream-consumed checks, and response close behavior.
2. Parse and validate `Content-Type` before consuming the body. Treat media type and parameter names case-insensitively, let the last `boundary` parameter win, and reject CR/LF injection, empty/non-ASCII/NUL/leading-`=` boundaries, missing boundary, and `multipart/` with an empty subtype.
3. Normalize body line scanning without losing bytes. Support LF, CRLF, CR, and delimiters split across chunks; do not include the line terminator immediately before a delimiter in part content.
4. Accept only exact delimiter lines `--boundary` and `--boundary--` with optional trailing SP/HTAB. Ignore preamble and epilogue; if the first boundary-like line is malformed, raise the public decoding error.
5. Parse each part's headers until a blank line. Reject missing colon, empty names, leading whitespace on the first header, and continuation lines containing only SP/TAB.
6. Preserve duplicate headers and continuation values through the project's header type instead of flattening them into a plain dict.
7. Keep sync and async behavior equivalent. Streaming multipart iteration should consume the raw stream, close the response, and raise the stream-consumed error on repeat; buffered bodies should be repeatable.
8. Add matrix tests for boundary parsing, delimiter variants, malformed framing, duplicate/continued headers, preamble/epilogue, streaming chunk splits, sync and async APIs, and repeat iteration semantics.

## Rules
- Do not parse multipart bodies through text decoding; all boundary and body handling must be bytes-safe.
- Boundary-like lines inside a part body are content unless they are exact delimiter lines.
- A successful close delimiter with no preceding parts is a valid zero-part response.
- Public errors should use the library's existing decoding/stream-consumed exception types.
