# Thomas Onboarding (Windows)

Use this guide when Thomas is downloaded on a fresh machine.

## 1) Prerequisites

- Windows 10 or Windows 11
- Internet access for dependency install
- `winget` available (recommended) for automatic prerequisite install
- If `winget` is unavailable, install Python 3.10+ manually first

## 2) Fastest Start (Recommended)

1. Open the Thomas folder.
2. Run `run-ui.cmd`.
3. On first launch, Thomas auto-runs quick bootstrap:
   - attempts automatic Python install if missing
   - creates `.venv`
   - installs Python dependencies
   - picks the best available starter profile
4. Open `http://127.0.0.1:8899` if it does not open automatically.
5. Complete the in-app `Onboarding Wizard`:
   - click `Use Recommended Path`
   - if anything fails, click `Auto Repair`
   - connect one provider path (ChatGPT, local, or cloud key)
   - run the interview so Thomas tunes defaults to your skill level

## 3) Manual Setup (Optional)

If you want explicit control, run `setup.cmd`.

What manual setup does:
- Creates `.venv`
- Installs Python dependencies
- Sets `default_model` in `thomas.toml`
- Optionally captures API key in user environment vars
- Writes status to `runtime/setup/last_setup.txt`

## 4) Troubleshooting

- Python missing:
  - `run-ui.cmd` first attempts automatic install via `winget`.
  - If auto-install is unavailable or fails, install Python 3.10+ and retry.
- Local profile not working:
  - Install Ollama: <https://ollama.com>
  - Start it: `ollama serve`
- ChatGPT/Codex path not working:
  - Install Node.js: <https://nodejs.org/en/download>
  - Install CLI: `npm i -g @openai/codex`
  - Login: `.\.venv\Scripts\python.exe -m thomas codex login`
- One-click repair:
  - Run `repair.cmd` from repo root.
- OpenAI profile not working:
  - Set `THOMAS_MODELS_OPENAI_API_KEY`
- Anthropic profile not working:
  - Set `THOMAS_MODELS_ANTHROPIC_API_KEY`
- Need deeper diagnostics:
  - `.\.venv\Scripts\python.exe -m thomas doctor --full`

## 5) Optional Non-Interactive Setup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Easy -AutoInstallTools -NoPrompt
```

Valid `-Profile` values: `local`, `codex`, `openai`, `anthropic`.

## 6) Dialogue Spec

Detailed onboarding dialogue + config mapping:

- `docs/ONBOARDING_DIALOGUE_MASTER.md`
