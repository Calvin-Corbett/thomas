# Thomas Ollama models

A "Thomas version" of a local model is the base model with the canonical Thomas
persona + security floor (`thomas.system.txt`) and a couple of safe sampling
defaults layered on via a Modelfile. Ollama shares the base weight blob, so each
Thomas model costs ~nothing extra on disk.

## Build one for every installed model

```bash
python scripts/build_thomas_models.py            # build all missing
python scripts/build_thomas_models.py --force    # rebuild
python scripts/build_thomas_models.py --dry-run  # preview
python scripts/build_thomas_models.py --model mistral:7b
```

This creates `thomas-<base>` (e.g. `thomas-mistral-7b`) for each installed local
base model, skipping cloud models and ones that are already Thomas-flavored.

## What the baked persona actually does

- **Standalone / terminal use** (`ollama run thomas-mistral-7b`): the model
  answers as Thomas and applies the security floor.
- **Inside the Thomas app:** the app sends its **own** system prompt on every
  request, and Ollama *replaces* (does not merge) the baked one — so in-app
  behavior comes from the app, not the Modelfile. The same security floor is
  enforced in-app via `thomas/agent/prompt_templates.py` (`_SECURITY_CONTRACT`),
  which is the single source of truth this file mirrors.
- **Defense in depth:** any caller that reaches a Thomas model *without* sending
  a system prompt still gets the baked Thomas floor.

## Wiring the app to a Thomas model (optional)

The shipped `thomas.toml` intentionally points the `local` profile at a raw base
model so fresh installs work before any Thomas model is built. To make your own
machine default to a Thomas model, point `[models.local].model` at e.g.
`thomas-qwen2.5-coder-7b` after building it. (That is a protected-config edit.)
