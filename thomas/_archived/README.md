# Thomas Archived Domain Modules

This directory contains domain-specific modules that have been archived and are not part of the core Thomas agent platform. These modules are not imported, tested, or maintained as part of the active codebase.

## Archival Rationale

Per THOMAS_FIX_PLAN.md (Phase 6: Domain Module Triage), these modules were archived because they are **not core to the agent platform's core mission** of intelligent task execution and automation. They represent domain-specific expertise that can be revived later as plugins if needed.

## Archived Modules

### Archived (Not Core to Agent Platform)

1. **agriculture/** - Agriculture domain algorithms and utilities
2. **autonomous_vehicles/** - Autonomous vehicle domain algorithms and utilities
3. **ecommerce/** - E-commerce domain algorithms and utilities
4. **fintech/** - FinTech domain algorithms and utilities
5. **food_tech/** - Food technology domain algorithms and utilities
6. **healthcare/** - Healthcare domain algorithms and utilities
7. **hr_platform/** - HR platform domain algorithms and utilities
8. **hrm/** - Human resource management domain algorithms and utilities
9. **legal/** - Legal domain algorithms and utilities
10. **quantfin/** - Quantitative finance domain algorithms and utilities
11. **real_estate/** - Real estate domain algorithms and utilities
12. **supply_chain/** - Supply-chain domain algorithms and utilities
13. **travel/** - Travel domain algorithms and utilities

## Modules Still Active

The following domain modules **remain active** because they serve Thomas's core mission:

- **smart_home/** - IoT automation is agent-relevant for task execution and control
- **social_platform/** - Social media automation is agent-relevant for outreach and monitoring
- **project_mgmt/** - Project management is core to task execution
- **crm/** - CRM integrations support workflow automation

## Reviving an Archived Module

If you need to revive an archived module for use as a plugin:

1. Move it from `thomas/_archived/<module>/` back to `thomas/<module>/`
2. Update `thomas/_architecture.py` to remove the `"archived": True` flag
3. Run `python -m pytest tests/test_architecture.py` to verify module integrity
4. Add it to the appropriate tier (`ext` for extensions, `infra` for infrastructure) in the architecture
5. Update FEATURE_MASTER_LIST.md if it becomes a primary feature

## Storage & Deletion

These modules are **archived, not deleted**:
- All original code is preserved in the filesystem
- No functionality has been removed or lost
- They can be restored to active development at any time
- They are not tracked by git operations or imports

## Architecture File

Each archived module has an entry in `thomas/_architecture.py` with `"archived": True` flag set, making it easy to filter in tools and documentation.
