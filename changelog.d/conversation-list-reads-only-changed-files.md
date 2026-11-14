### Changed
- Listing Code conversations now reads again only the conversation files that changed since the last listing. Every listing parsed every file, transcripts and all: 26 to 177 seconds for 709 conversations on a busy 2026-10-27, holding a server thread the whole time. With 700 conversations of about 800 KB each, a repeat listing now takes 0.07 s instead of 8 s.
