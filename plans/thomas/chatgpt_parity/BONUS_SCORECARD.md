# Thomas 110/100 Proof Scorecard

Generated 2026-07-13 for the local Thomas v0.18.0 server at `http://127.0.0.1:8908`.

## Base score: 100/100

The fail-closed, all-family audit completed on the final product code with parity required:

- parity index: **100.0/100**
- families at tier 4: **14/14**
- checks passed: **74/74**
- critical failures: **0**
- parity achieved: **true**
- scorecard generated at: `2026-07-13T21:48:11.986315+00:00`
- runner output: `output/parity/full-110-final-r5.stdout.log`
- machine-readable evidence: `latest_scorecard.json` and `latest_evidence.jsonl`

The bonus is evidence beyond the rubric. It does not inflate or weaken the 100-point parity calculation.

## Adversarial/browser bonus: +10/10

| Point | Proof | Evidence |
| --- | --- | --- |
| +1 | Real signed-in GPT-5.6 Sol browser turns returned exact markers before and after the 0.18.0 restart, with no false sign-in prompt. | `output/playwright/final-110-sol-chat-r3.png`, `output/playwright/final-018-live-smoke.png` |
| +1 | The live selector exposes GPT-5.6 Sol, Terra, and Luna plus GPT-5.5; Sol and Terra are usable, while Luna is honestly disabled with the backend's `Model not found` explanation. | Headed-browser model-menu assertions, 41/41 pass |
| +1 | All six reasoning levels (`None`, `Low`, `Medium`, `High`, `xHigh`, `Max`) and all five file-access levels render; `Max` plus `Project` survived a reload. | Headed-browser persistence assertions, 41/41 pass |
| +1 | Settings now shows GPT-5.6 variants and keeps signed-in ChatGPT/Codex distinct from the API-key OpenAI provider; tool permissions and privacy controls are visible. | `output/playwright/final-110-settings-r3.png` |
| +1 | My Stuff loaded its real project library with 48 project/artifact cards, including FreedomFlappy and FreedomTMS. | `output/playwright/final-110-my-stuff-r3.png` |
| +1 | Windows offline speech-to-text and text-to-speech are available, with Microsoft David and Zira voices and realtime barge-in enabled. | `/api/v2/chat/voice/status` headed-browser assertion |
| +1 | A generated Canvas site opened with its marker, changed from `Ready` to `Revised` after a real browser click, and kept its CSP intact. | `output/playwright/final-110-canvas-artifact-r3.png` |
| +1 | Chat, Settings, My Stuff, and Canvas each completed with zero console errors/warnings and zero failed browser requests. | Headed-browser surface assertions, 41/41 pass |
| +1 | All four tested browser surfaces loaded only local/data assets; the parser-blocking icon/font CDN dependency was removed from the main chat shell. | Headed-browser external-request assertions, 41/41 pass |
| +1 | Local safety and responsiveness held after the 0.18.0 restart: workspace auto-push was `False`; 10/10 health requests succeeded (2-163 ms, 18.4 ms average) with no crashes. | `%TEMP%/thomas-parity-8908-r14.err.log`, local health sample |

## Total: 110/100

`100` fail-closed parity points + `10` independent adversarial/browser proof points = **110/100**.
