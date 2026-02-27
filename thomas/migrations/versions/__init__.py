"""
Thomas database migration versions.

Each migration file follows the naming convention:
    NNN_<description>.py

Where NNN is a zero-padded revision number (001, 002, etc.)

Each migration must define:
- revision: unique revision identifier
- down_revision: previous revision ID or None for first migration
- upgrade(): function to apply the migration
- downgrade(): function to revert the migration
"""
