# Thomas vs. Current ChatGPT Capability Rubric

- Target date: `2026-07-13`
- Schema: `thomas-chatgpt-parity-v1`
- Completion rule: every family must score 4/4; averages never waive a missing family.

## Evidence Levels

- **0** — Absent, contradicted, or no executable evidence
- **1** — Declared or statically wired; no executed contract proof
- **2** — Deterministic executable contract proof
- **3** — Live normal-case proof through the user-facing runtime
- **4** — Live adversarial, recovery, persistence, or steerability proof

## Official Target Sources

- https://help.openai.com/en/articles/9260256-chatgpt-capabilities-overview
- https://help.openai.com/en/articles/6825453-chatgpt-release-notes
- https://help.openai.com/en/articles/8554407-gpts-faq
- https://openai.com/index/introducing-deep-research/
- https://learn.chatgpt.com/docs/use-chatgpt
- https://learn.chatgpt.com/docs/customization/memories
- https://learn.chatgpt.com/docs/projects
- https://learn.chatgpt.com/docs/automations
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://developers.openai.com/api/docs/models/gpt-5.6-luna

## Capability Families

### Conversation, reasoning, writing, translation, and instruction fidelity (`core-conversation-instructions`, weight 0.11) — critical floor

- Answer and explain
- Draft, rewrite, summarize, create, reason, and translate
- Follow multiple constraints
- Carry and revise context across turns

- Tier 1 evidence: path_contains, path_contains
- Tier 2 evidence: command
- Tier 3 evidence: conversation_multi_turn
- Tier 4 evidence: conversation_adversarial_followup, conversation_benign_token_refusal

### Current web search, citations, and deep multi-source research (`web-search-deep-research`, weight 0.10) — critical floor

- Find current information on the web
- Cite sources beside supported claims
- Perform multi-step, multi-source research
- Produce a structured synthesis that can be refined

- Tier 1 evidence: path_exists_any, path_contains
- Tier 2 evidence: command
- Tier 3 evidence: web_search_cited_answer
- Tier 4 evidence: web_source_conflict

### Image understanding, generation, and natural-language editing (`multimodal-images`, weight 0.07)

- Analyze screenshots, diagrams, charts, and photos
- Extract and interpret visual content
- Generate images from text
- Edit an existing or generated image

- Tier 1 evidence: path_contains, path_contains
- Tier 2 evidence: command
- Tier 3 evidence: image_understanding_generation_edit
- Tier 4 evidence: image_visual_injection_edit_fidelity

### File uploads, document understanding, and downloadable document work (`files-documents`, weight 0.07)

- Accept PDFs, presentations, text, and other documents
- Summarize and extract grounded information
- Answer questions from uploaded content
- Create and return usable document artifacts

- Tier 1 evidence: path_contains, tools_any
- Tier 2 evidence: command
- Tier 3 evidence: document_upload_grounded_artifact
- Tier 4 evidence: document_conflict_truncation_grounding

### Secure code execution, data analysis, spreadsheets, and charts (`data-code-charts`, weight 0.08) — critical floor

- Run code in an isolated environment
- Analyze and clean structured data
- Calculate projections and summarize trends
- Create accurate static or interactive visualizations

- Tier 1 evidence: tools_any, path_exists_any
- Tier 2 evidence: api_json
- Tier 3 evidence: data_code_chart_roundtrip
- Tier 4 evidence: data_dirty_formula_sandbox

### Voice conversation, dictation, transcription, and spoken responses (`voice-dictation`, weight 0.05)

- Transcribe natural speech and dictation
- Support conversational spoken input and output
- Handle interruptions and turn-taking
- Work across supported languages and accents

- Tier 1 evidence: path_contains
- Tier 2 evidence: command
- Tier 3 evidence: voice_audio_roundtrip
- Tier 4 evidence: voice_noise_language_interrupt_latency

### Canvas collaboration, finished artifacts, and interactive Sites (`canvas-sites-artifacts`, weight 0.08) — critical floor

- Co-write, edit, mark up, and debug in a shared workspace
- Create finished documents, spreadsheets, presentations, reports, and apps
- Preview and refine interactive sites
- Return an openable, accurate, shareable result

- Tier 1 evidence: path_exists_any, path_contains
- Tier 2 evidence: command
- Tier 3 evidence: canvas_artifact_matrix
- Tier 4 evidence: canvas_revision_integrity

### Memory, personalization, and user-controlled correction/deletion (`memory-personalization`, weight 0.08) — critical floor

- Remember useful facts, preferences, and goals across chats
- Use remembered context appropriately
- Show and correct memory
- Delete or disable memory without contaminating temporary chats

- Tier 1 evidence: path_exists_any, path_contains
- Tier 2 evidence: command, api_json
- Tier 3 evidence: memory_cross_session_recall
- Tier 4 evidence: memory_correction_deletion_isolation

### Projects, persistent context, libraries, chat organization, and sharing (`projects-library-sharing`, weight 0.06)

- Organize chats, files, and context under a shared objective
- Resume multi-session work
- Pin, find, and manage important chats and artifacts
- Share conversations or results intentionally

- Tier 1 evidence: path_exists_any, path_contains
- Tier 2 evidence: command, api_json
- Tier 3 evidence: project_workspace_lifecycle
- Tier 4 evidence: project_isolation_stale_share

### One-time, recurring, triggered, and monitoring tasks (`scheduled-monitoring`, weight 0.07) — critical floor

- Schedule one-time and recurring work
- Monitor the web or connected apps for changes
- Notify only when useful
- View, pause, resume, edit, and delete scheduled work

- Tier 1 evidence: path_exists_any, tools_any
- Tier 2 evidence: command
- Tier 3 evidence: scheduled_task_lifecycle
- Tier 4 evidence: scheduled_recovery_dedup_noise

### Custom assistants, skills, plugins, knowledge, tools, and publishing (`custom-assistants-plugins`, weight 0.06)

- Create an assistant with tailored instructions and starters
- Attach knowledge files
- Select tools, apps, or APIs
- Install, share, publish, discover, and remove extensions safely

- Tier 1 evidence: path_exists_any, tools_any
- Tier 2 evidence: command, api_json
- Tier 3 evidence: custom_assistant_plugin_lifecycle
- Tier 4 evidence: custom_assistant_plugin_adversarial

### Connected apps, source-grounded actions, and approval controls (`connected-apps-actions`, weight 0.06) — critical floor

- Read from connected apps and files with permission
- Draft and perform supported actions such as email
- Ask before changes according to user policy
- Never claim an external effect without a receipt

- Tier 1 evidence: tools_any, path_exists_any
- Tier 2 evidence: command
- Tier 3 evidence: connected_app_receipt
- Tier 4 evidence: connected_app_adversarial_controls

### Long-running agentic work, browser/computer use, steering, and approvals (`agentic-work-browser-computer`, weight 0.08) — critical floor

- Research and work across websites, local files, and supported apps
- Show progress and ask questions while working
- Accept changed direction and cancellation
- Require approval for important actions and report verified completion

- Tier 1 evidence: tools_any, path_exists_any
- Tier 2 evidence: command
- Tier 3 evidence: agentic_browser_artifact
- Tier 4 evidence: agentic_interrupt_approval_recovery

### Privacy, temporary use, export, deletion, and security controls (`privacy-export-controls`, weight 0.03) — critical floor

- Export owned data and results
- Delete chats, projects, files, memories, and account-local state
- Support temporary/non-memory work
- Restrict network and external-service access when requested

- Tier 1 evidence: path_contains, path_exists_any
- Tier 2 evidence: api_json, command
- Tier 3 evidence: privacy_export_delete_temporary
- Tier 4 evidence: privacy_remanence_isolation_lockdown
