"""Package for Thomas marketplace domain modules.

This package deliberately re-exports nothing. Until 2026-09-25 it re-exported
sixteen dataclasses (``Vendor``, ``Listing``, ``Order``, ``Payment``, ...) from
a ``_types`` module belonging to a multi-vendor e-commerce engine that no
caller ever imported -- ``from thomas.marketplace import <name>`` appears
nowhere in this repository. That engine and its ``_types``/``_exceptions``
modules are gone; importing this package is now import-free and cheap.

What is still here and wired:

- ``surface_policy`` -- ``thomas/server/routes/marketplace_catalog_aiohttp.py``
  reads ``classify_marketplace_row`` and ``row_is_visible`` from it to decide
  which catalog rows are visible, and ``thomas/cli/pack_bridge.py`` reads
  ``family_requires_strict_entrypoint`` from it to decide whether a CLI pack
  family requires a strict entrypoint.
- ``publisher`` -- driven by ``scripts/publish_marketplace_wave.py``.
- the subpackages listed in ``MANIFEST.json``.

Here but not wired: ``governed_distribution`` and ``org_inventory`` have real
tests and no caller outside them. ``STATUS.md`` records why they were left in
place rather than removed with the commerce engine.

The installable-plugin product (``extensions/``, ``/api/marketplace/*``) is a
different thing and never depended on the deleted engine.
"""
