# Asset Studio OSS Stack

Last reviewed: 2026-02-22

## Goal

Define a legal, free/open-source toolchain for `Asset Studio` so Thomas can create and process audio, video, and visual assets without paid vendor lock-in.

## Toolchain

| Tool | License | Why it is in Asset Studio | Reference |
| --- | --- | --- | --- |
| FFmpeg | LGPL/GPL (build-dependent) | Transcoding, loudness normalization, export presets | https://ffmpeg.org/legal.html |
| OpenTimelineIO | Apache-2.0 | Timeline interchange between editing pipelines | https://github.com/PixarAnimationStudios/OpenTimelineIO |
| WaveSurfer.js | BSD-3-Clause | Browser waveform playback + seeking in Thomas UI | https://github.com/katspaugh/wavesurfer.js |
| Blender | GPL | 3D renders, animation, scripted batch output | https://docs.blender.org/manual/en/latest/getting_started/about/license.html |
| Krita | GPL | Concept painting, texture passes, paint-over workflows | https://krita.org/en/about/license/ |
| Inkscape | GPL | Vector icons, logos, and UI art | https://inkscape.org/about/ |
| Kdenlive | GPL-3.0-only | Full NLE editing and compositing | https://apps.kde.org/kdenlive/ |
| Shotcut | GPL-3.0 | Fast timeline editing and quick exports | https://github.com/mltframework/shotcut |
| ComfyUI | GPL-3.0 | Local node-based AI image generation | https://github.com/comfyanonymous/ComfyUI |
| LMMS | GPL-2.0 | Music loops and sound design | https://github.com/LMMS/lmms |

## Legal guardrails

- Keep attribution and license notices intact when redistributing binaries or modified source.
- For FFmpeg, confirm whether your specific binary build includes GPL codecs before commercial redistribution.
- Local generation tools (for example ComfyUI) are OSS, but model checkpoints may have separate licenses. Validate each model's terms before shipping generated assets.

## Current Thomas integration points

- `thomas/server/web/js/app.js`:
  - `moduleWorkbenchOssCatalog('studio')` exposes vetted tools with license labels + quick install commands.
  - `Asset Studio` includes command bridges for:
    - audio chain presets,
    - render preset commands,
    - local generation workflow commands.
- `thomas/server/web/index.html`:
  - sidebar tab label changed from `Studio` to `Asset Studio`.
