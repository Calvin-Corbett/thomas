---
name: self-extend
description: Give Thomas a brand-new ability at runtime. Use when Thomas lacks a capability the user is asking for, needs a new tool or ability, or cannot do something yet with its current tools.
---

# Self-Extend

Use this skill whenever you hit a user request you cannot fulfill with the
tools you currently have — for example the user asks you to email someone,
post to a service, or run a repeated multi-step workflow you keep redoing by
hand. Instead of giving up or saying "I can't do that", give yourself the
ability.

## When to use

Activate this skill the moment you notice any of:

- You were asked to perform an action and no current tool covers it.
- You find yourself repeating the same multi-step procedure across turns.
- The user explicitly asks you to "learn", "gain the ability to", or "be able
  to" do something new.

## Workflow

1. Name the missing ability in one short slug, e.g. `send-email`.
2. Call the `create_skill` tool with:
   - `name` — the slug.
   - `description` — one sentence on what it does (this is how future turns
     decide to use it).
   - `instructions` — a markdown body telling your future self exactly HOW and
     WHEN to perform the ability: the steps, which existing tools to call
     (shell, http, filesystem, email.send, etc.), the inputs needed, and any
     config the user must supply.
   - `trigger` (optional) — a plain-English condition, e.g. "the user asks to
     email someone".
3. After `create_skill` returns, tell the user the new ability is ready and
   continue with their request. The new skill is discovered automatically and
   is available to you on your NEXT turn.

## Email example

If the user says "email Calvin and tell him the build is done" and you cannot
send email right now:

1. First check whether an `email.send` tool is already available to you — if it
   is, just use it.
2. If it is not, call `create_skill` with `name: send-email`,
   `description: Send an email to a recipient on the user's behalf`, and
   `instructions` describing how to send mail (use the `email.send` tool once
   the user has configured the email provider settings in `thomas.toml` under
   `[tools.email]`; if those settings are missing, ask the user to add them and
   say exactly which keys are required: `provider`, `client_id`,
   `client_secret`, `refresh_token`).
3. On the next turn, follow the new skill's instructions to actually send the
   email, or clearly tell the user which configuration values you still need.

## Rules

- Do not create a skill for a one-off action you can already do inline.
- Prefer refining an existing skill over fragmenting the catalog — check first.
- A new skill is markdown instructions for yourself; it composes your existing
  tools. It does not bypass any safety rule, and self-created skills are written
  only to your user skills folder, never into Thomas's protected runtime code.
