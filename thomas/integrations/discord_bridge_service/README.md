# Thomas Discord Bridge

This bot puts Thomas into Discord by forwarding Discord messages into Thomas's existing `/api/chat` endpoint.

What it does:

- Responds in DMs.
- Responds in servers when mentioned.
- Optionally responds without mention in specific channel IDs.
- Supports owner-only mode so only configured Discord user IDs can control or trigger Thomas.
- Supports delegated access so the owner can grant specific members chat/music access without giving them settings control.
- Keeps one Thomas session per Discord DM or per Discord channel.
- Joins voice channels, listens for wake-word commands, and speaks replies locally.
- Searches YouTube with local `yt-dlp`, posts results in chat, and plays YouTube audio in voice.
- Includes a small local soundboard with `bang`, `airhorn`, and `rimshot`.
- Adds slash commands:
  - `/thomas`
  - `/reset`
  - `/status`
  - `/voice join|leave|status|queue|play|pause|resume|skip|stop|volume|profile|search|effect|say|ask`

## Requirements

- Node 20+
- Python 3.11+
- A running Thomas server, usually at `http://127.0.0.1:8899`
- A Discord bot token

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in:
   - `DISCORD_BOT_TOKEN`
   - `DISCORD_GUILD_ID`
   - `DISCORD_ALLOWED_GUILD_IDS`
   - `DISCORD_OWNER_USER_IDS`
3. Install dependencies:

```bash
npm install
```

4. Install the local voice runtime:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install faster-whisper piper-tts pathvalidate yt-dlp
```

5. Start Thomas if it is not already running:

```bash
python -m thomas.server --host 127.0.0.1 --port 8899
```

6. Start the bridge:

```bash
npm start
```

## Discord bot settings

In the Discord Developer Portal:

- Enable `MESSAGE CONTENT INTENT`
- Enable `SERVER MEMBERS INTENT`
- Create an invite URL with:
  - `bot`
  - `applications.commands`

Recommended bot permissions:

- View Channels
- Send Messages
- Read Message History
- Embed Links

## Behavior

- DMs always work.
- In servers, Thomas replies when directly addressed by `@Thomas` or text like `Thomas, ...`.
- If `DISCORD_OWNER_ONLY_MODE=true`, only the configured owner user IDs can trigger Thomas or change settings.
- In owner-only mode, the owner can grant delegated access in chat with commands like `Thomas, allow @Wolves1289 to use music and chat` or remove it with `Thomas, revoke @Wolves1289 access`.
- `DISCORD_AUTO_CHANNEL_IDS` is used as the linked text fallback for voice/media status posts.
- `/reset` clears Thomas context for the current DM or channel.
- In voice, you can say commands like `Thomas, play never gonna give you up`, `Thomas, search YouTube for lofi hip hop`, `Thomas, bang`, or `Thomas, stop music`.
- Media controls now support queueing plus `pause`, `resume`, `skip`, `queue`, `now playing`, and `set volume to 120 percent`.
- Volume changes are applied live now instead of restarting the current track.
- When wake words are required, the bot uses a shorter wake-listen window plus a no-wake cooldown so background TV/commentary does not keep hammering the STT path.
- You can switch installed local voices live with `/voice profile` or text like `Thomas, switch to lessac high voice`.
- The owner can also change runtime behavior live with commands like `reply only when mentioned`, `reply to everyone`, `require wake word`, `wake word off`, or `set wake words to thomas, hey thomas`.
- Delegated users can use chat/music features, but settings, wake words, voice profiles, and access grants remain owner-only.

## Notes

- This bridge only handles Discord transport. Thomas still decides how to talk, what tools to use, and whether it can control music or other apps on the machine.
- If your Thomas server requires bearer auth, set `THOMAS_SERVER_API_TOKEN`.
- Voice transcription defaults to local `faster-whisper` with the reliable CPU `int8` profile. If you have the CUDA runtime DLLs installed, you can switch `DISCORD_VOICE_STT_DEVICE=cuda` and `DISCORD_VOICE_STT_COMPUTE_TYPE=float16`.
- Voice synthesis defaults to local Piper with the faster `en_US-lessac-medium` profile, stored under `data/piper-voices`.
- Piper speech is now rendered sentence-by-sentence with a short configurable pause between sentences (`DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS`) so replies sound less flat and run-on.
- Spoken replies also normalize symbols and acronyms before synthesis so things like `GPU`, `API`, `%`, `@`, and `#` sound cleaner.
- On NVIDIA GPUs, the bridge now prepends the venv CUDA/ONNX library paths automatically for local speech workers, so `faster-whisper` and Piper CUDA can run without extra shell PATH hacks.
- Optional cloud voice is supported with OpenAI. Set `DISCORD_VOICE_TTS_BACKEND=openai`, `DISCORD_VOICE_TTS_MODEL=gpt-4o-mini-tts`, `DISCORD_VOICE_STT_BACKEND=openai`, `DISCORD_VOICE_STT_MODEL=gpt-4o-mini-transcribe`, and `DISCORD_VOICE_OPENAI_API_KEY`. If Thomas already runs with `THOMAS_MODELS_OPENAI_API_KEY`, the bridge will reuse that automatically.
- Spotify URLs are not supported directly yet; use the song title or a YouTube link.
