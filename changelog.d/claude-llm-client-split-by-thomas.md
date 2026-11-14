### Changed

- **The LLM client is under the size limit again, and Thomas made the change itself.**
  `thomas/core/llm_client.py` was 904 lines against a 800-line limit, on a waiver that
  expires 2026-09-30. Provider cooldown state now lives in `thomas/core/llm_provider_state.py`
  and the HTTP client and streaming helpers in `thomas/core/llm_transport_pool.py`, with
  every name still importable from `thomas.core.llm_client`, so nothing that uses or
  patches it has to change. This was written by Thomas's own Build agent, working on a
  copy of Thomas, and checked with its own tests before landing.
