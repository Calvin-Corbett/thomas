"""
Verification script for Thomas migration setup.

Checks that all migration files are present and properly configured.

Usage:
    python thomas/migrations/verify_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_FILES = [
    "alembic.ini",
    "env.py",
    "__init__.py",
    "migrate.py",
    "verify_setup.py",
    "INTEGRATION_GUIDE.md",
    "versions/__init__.py",
    "versions/001_initial_schema.py",
    "versions/002_add_migration_tracking.py",
]


def verify_files() -> bool:
    """Verify all migration files exist."""
    migrations_dir = Path(__file__).parent
    print(f"Checking migration setup in: {migrations_dir}\n")

    all_present = True
    for filename in REQUIRED_FILES:
        filepath = migrations_dir / filename
        exists = filepath.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {filename}")
        if not exists:
            all_present = False

    return all_present


def verify_imports() -> bool:
    """Verify Python imports work."""
    print("\n" + "=" * 50)
    print("Checking imports...\n")

    errors = []

    # Check migrate.py
    try:
        from thomas.migrations import migrate

        print("✓ thomas.migrations.migrate")
    except ImportError as e:
        print(f"✗ thomas.migrations.migrate: {e}")
        errors.append(str(e))

    # Check server integration
    try:
        from thomas.server import db_init

        print("✓ thomas.server.db_init")
    except ImportError as e:
        print(f"✗ thomas.server.db_init: {e}")
        errors.append(str(e))

    # Check Alembic (optional but recommended)
    try:
        import alembic

        print("✓ alembic (installed)")
    except ImportError:
        print("⚠ alembic (not installed - migrations require: pip install alembic)")

    return len(errors) == 0


def verify_migration_files() -> bool:
    """Verify migration version files are valid Python."""
    print("\n" + "=" * 50)
    print("Checking migration files...\n")

    migrations_dir = Path(__file__).parent
    versions_dir = migrations_dir / "versions"

    required_attributes = ["revision", "down_revision", "upgrade", "downgrade"]
    all_valid = True

    for filepath in sorted(versions_dir.glob("*.py")):
        if filepath.name.startswith("_"):
            continue

        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                missing = []
                for attr in required_attributes:
                    if not hasattr(module, attr):
                        missing.append(attr)

                if missing:
                    print(f"✗ {filepath.name}: missing {', '.join(missing)}")
                    all_valid = False
                else:
                    revision = getattr(module, "revision", "unknown")
                    print(f"✓ {filepath.name} (revision: {revision})")
            else:
                print(f"✗ {filepath.name}: could not load")
                all_valid = False

        except Exception as e:
            print(f"✗ {filepath.name}: {e}")
            all_valid = False

    return all_valid


def verify_configuration() -> bool:
    """Verify Alembic configuration."""
    print("\n" + "=" * 50)
    print("Checking Alembic configuration...\n")

    migrations_dir = Path(__file__).parent
    alembic_ini = migrations_dir / "alembic.ini"

    if not alembic_ini.exists():
        print("✗ alembic.ini not found")
        return False

    try:
        from alembic.config import Config

        config = Config(str(alembic_ini))
        script_location = config.get_main_option("script_location")
        print("✓ alembic.ini is valid")
        print(f"  Script location: {script_location}")
        return True
    except Exception as e:
        print(f"✗ alembic.ini configuration error: {e}")
        return False


def main() -> int:
    """Run all verification checks."""
    print("=" * 50)
    print("Thomas Migration Setup Verification")
    print("=" * 50 + "\n")

    results = {
        "Files present": verify_files(),
        "Imports work": verify_imports(),
        "Migration files valid": verify_migration_files(),
        "Configuration valid": verify_configuration(),
    }

    print("\n" + "=" * 50)
    print("Summary\n")

    all_passed = True
    for check, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {check}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 50)

    if all_passed:
        print("\n✓ All checks passed! Migration system is ready.\n")
        print("Next steps:")
        print("1. Install Alembic: pip install alembic")
        print("2. Integrate into thomas/server/app.py")
        print("3. Test with: python -m thomas.migrations.migrate current")
        print("\nSee INTEGRATION_GUIDE.md for detailed instructions.")
        return 0
    else:
        print("\n✗ Some checks failed. See above for details.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
