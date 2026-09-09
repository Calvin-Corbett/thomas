# Domain Module Checklist

- Do not delete domain packages to resolve failures.
- Keep imports side-effect free.
- If behavior is missing, keep import-safe skeletons and raise `NotImplementedError` only at call time.
- Update `docs/ai/FEATURE_REGISTRY.md` status when touching domain modules.
- Add or update targeted tests when implementing real behavior.
