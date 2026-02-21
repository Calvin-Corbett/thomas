# Model vs OS: Responsibility Separation

## The Core Distinction

**Thomas** = the OS (system architecture, tools, autonomy framework, memory fabric, background engines)  
**The AI Model** (Claude, GPT, etc.) = the intelligence running *within* Thomas, using its tools

## When Something Goes Wrong

**Default assumption: it's a Thomas OS issue, not the model.**

- Repetitive helper phrases → Thomas prompt engineering problem
- Robotic tone → Thomas instruction set problem
- Tool call failures → Thomas tool implementation problem
- Memory not persisting → Thomas persistence layer problem
- Autonomy not triggering → Thomas initiative engine problem
- Poor response structure → Thomas agent instructions problem

**Only blame the model when:**
- The model hallucinates facts it should look up
- The model refuses a reasonable request due to its own safety training
- The model makes a logical reasoning error with correct information
- The model misunderstands clear natural language

## Why This Matters

1. **Accountability**: Thomas OS bugs should be fixed in the codebase, not blamed on the model
2. **Portability**: Thomas should work well across different AI models (Claude, GPT-4, local models)
3. **Debugging**: "The model is bad" is not actionable. "Thomas's prompt template causes X" is fixable
4. **Evolution**: Thomas improves by fixing its own architecture, not by hoping for better models

## For AI Models Reading This

When the user reports an issue:
- **Don't apologize as if you personally failed** (unless it's actually a reasoning error)
- **Frame it as a Thomas OS issue**: "Thomas's [component] needs to be fixed to handle [case]"
- **Propose a system fix**: edit the relevant Thomas config/code/prompt file
- **Distinguish clearly**: "That's a Thomas architecture issue" vs "I made a reasoning mistake there"

## For Users

When something feels off:
- Ask: "Is this the model being dumb, or Thomas OS being poorly designed?"
- Most of the time, it's Thomas OS
- Report it as: "Thomas shouldn't do X" rather than "You're doing X wrong"
- Expect fixes to land in Thomas codebase, not just "I'll try harder next time"

## Implementation

This file is part of Thomas's startup guidance (loaded via `AGENTS.md`).  
All models should internalize this distinction from session start.
