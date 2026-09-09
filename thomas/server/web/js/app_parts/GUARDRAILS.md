# Dead Code Warning: app_parts/ Directory

> **STOP. DO NOT EDIT THESE FILES.**
> **THIS IS DEAD CODE BEING MIGRATED TO MODULES.**
> **NO AGENT MAY MODIFY FILES IN THIS DIRECTORY.**

## What This Directory Is

The files in this directory (`part-001.js`, `part-002.js`, etc.) are **legacy dead code**. They are:
- NOT actively maintained
- Being gradually migrated to the module-based `app_runtime_primary.mjs`
- Protected by automated safety gates that WILL REJECT your changes

## What You Must Do Instead

If you need to modify app functionality, edit this file instead:

```
thomas/server/web/js/app_runtime_primary.mjs
```

This is the REAL application runtime. All active development happens here.

## If You Need to Add New Features

1. Implement your feature in `app_runtime_primary.mjs`
2. Follow the existing module patterns
3. Add tests in `tests/` directory
4. Do NOT touch the `app_parts/` files

## If You Made Changes Here

Your commit WILL BE REJECTED by the pre-commit safety gate:

```
❌ SAFETY GATE FAILED: Dead Code Files Edited

You edited files in thomas/server/web/js/app_parts/
These are DEAD CODE. Do not edit them. Edit app_runtime_primary.mjs instead.

HOW TO FIX IT:
1. git checkout -- thomas/server/web/js/app_parts/
2. Make your changes in app_runtime_primary.mjs instead
3. Commit again
```

## Questions?

If you believe these files need to be edited, STOP and ask the user. Do not proceed.
