"""The multi-vendor e-commerce engine under thomas/marketplace/ stays gone.

It was generated in the 2026-03-23 burst, registered nine ``marketplace.*``
tools into every boot's tool registry, and could not complete a single call:
``thomas/marketplace/tools.py`` imported ``VendorManager``, ``ListingManager``,
``OrderManager``, ``ReviewManager`` and ``SearchEngine`` from its sibling
modules, which define no such classes -- they define ``VendorRegistry``,
``ListingRegistry``, ``OrderProcessor``, ``ReviewRegistry`` and ``SearchIndex``.
The import sat inside ``execute()`` above that method's ``try:``, so every call
raised ``ImportError`` out of ``execute()`` rather than being caught.

A deletion a merge can silently undo is not a deletion, so these assertions are
the record: the registration is out of the boot table, the nine tool names are
out of the runtime policy tables, the package re-exports no commerce types, and
nothing stands at any of the eighteen paths the engine occupied.

``merge_resurrection_gate.py`` is the repo's own version of the last check, and
it needs a ``scripts/forge/graveyard.py record-file`` death record per path to
see these paths at all. This file needs no such bookkeeping, which is why it is
worth having next to the gate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import thomas.marketplace
from thomas.server import chat_tool_policy_model, tool_extensions

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The twelve engine modules and the six module-only tests that exercised
# nothing else. thomas/marketplace/STATUS.md is deliberately NOT here: the
# package outlives the engine, so its status doc was rewritten to describe
# what is left, rather than removed with it.
_REMOVED_PATHS = (
    "thomas/marketplace/_exceptions.py",
    "thomas/marketplace/_types.py",
    "thomas/marketplace/analytics.py",
    "thomas/marketplace/disputes.py",
    "thomas/marketplace/listings.py",
    "thomas/marketplace/orders.py",
    "thomas/marketplace/payments.py",
    "thomas/marketplace/recommendations.py",
    "thomas/marketplace/reviews.py",
    "thomas/marketplace/search.py",
    "thomas/marketplace/tools.py",
    "thomas/marketplace/vendors.py",
    "tests/test_marketplace_listings.py",
    "tests/test_marketplace_orders.py",
    "tests/test_marketplace_payments.py",
    "tests/test_marketplace_reviews.py",
    "tests/test_marketplace_search.py",
    "tests/test_marketplace_vendors.py",
)

# The subset of the above that was an importable module path. Each name must
# now be unresolvable, so a reintroduced caller fails at its import line.
_REMOVED_MODULES = (
    "thomas.marketplace._exceptions",
    "thomas.marketplace._types",
    "thomas.marketplace.analytics",
    "thomas.marketplace.disputes",
    "thomas.marketplace.listings",
    "thomas.marketplace.orders",
    "thomas.marketplace.payments",
    "thomas.marketplace.recommendations",
    "thomas.marketplace.reviews",
    "thomas.marketplace.search",
    "thomas.marketplace.tools",
    "thomas.marketplace.vendors",
)

_REMOVED_TOOL_NAMES = (
    "marketplace.create_listing",
    "marketplace.create_order",
    "marketplace.create_review",
    "marketplace.get_listing",
    "marketplace.get_order",
    "marketplace.get_vendor",
    "marketplace.publish_listing",
    "marketplace.register_vendor",
    "marketplace.search_listings",
)

# Fourteen of the sixteen names the package used to re-export. The
# ``__all__`` assertion below covers all sixteen without naming them.
_REMOVED_TYPE_NAMES = (
    "Badge",
    "Commission",
    "Dispute",
    "Listing",
    "Order",
    "Payment",
    "PricingTier",
    "Product",
    "Rating",
    "Review",
    "SearchQuery",
    "SearchResult",
    "Subscription",
    "Vendor",
)


def test_boot_table_does_not_register_the_commerce_engine() -> None:
    modules = [entry[0] for entry in tool_extensions._OPTIONAL_TOOL_MODULES]
    assert "thomas.marketplace.tools" not in modules
    # paper_trading is one of ten marketplace subpackages still registered (six
    # load through _try_import's thomas.marketplace. fallback; channels, nodes and
    # policy load directly through their bridge packages); the one entry named by
    # its full marketplace path must survive.
    assert "thomas.marketplace.paper_trading.tools" in modules


def test_runtime_policy_tables_name_no_commerce_tool() -> None:
    classified = (
        chat_tool_policy_model._WRITE_TOOLS
        | chat_tool_policy_model._SHELL_TOOLS
        | chat_tool_policy_model._EXTERNAL_TOOLS
        | chat_tool_policy_model._CHANNEL_TOOLS
        | chat_tool_policy_model._SAFE_READ_TOOLS
    )
    prefixes = (
        chat_tool_policy_model._WRITE_PREFIXES
        + chat_tool_policy_model._EXTERNAL_PREFIXES
        + chat_tool_policy_model._CHANNEL_PREFIXES
        + chat_tool_policy_model._SAFE_READ_PREFIXES
    )
    for name in _REMOVED_TOOL_NAMES:
        assert name not in classified, name
        # A capability granted by prefix would be just as real as one granted by
        # name, and would catch every future marketplace.* tool with it.
        assert not name.startswith(prefixes), name

    # paper_trading, a still-registered marketplace subpackage, keeps its
    # grants; this test must not be read as "marketplace is unclassifiable".
    assert "paper_trading.submit" in chat_tool_policy_model._WRITE_TOOLS
    assert "paper_trading." in chat_tool_policy_model._EXTERNAL_PREFIXES


def test_marketplace_package_re_exports_no_commerce_types() -> None:
    for name in _REMOVED_TYPE_NAMES:
        assert not hasattr(thomas.marketplace, name), name
    assert not getattr(thomas.marketplace, "__all__", [])


def test_the_wired_marketplace_surface_still_imports() -> None:
    from thomas.marketplace.surface_policy import classify_marketplace_row, row_is_visible

    assert callable(classify_marketplace_row)
    assert callable(row_is_visible)


def test_nothing_stands_at_any_removed_path() -> None:
    """The ratchet: these eighteen paths stay absent.

    This is what stops a merge from quietly restoring the engine. If a branch
    brings ``thomas/marketplace/orders.py`` back, this fails and names the file.
    An empty file counts as back, because the next commit would fill it.
    """
    present = [relative for relative in _REMOVED_PATHS if (_REPO_ROOT / relative).exists()]
    assert not present, (
        "Paths this change deleted exist again. The engine was removed because "
        "nothing called it and none of its tools could complete a call; "
        "re-landing it needs a caller and a test, not a merge: " + ", ".join(present)
    )


def test_a_removed_module_cannot_be_imported() -> None:
    """The import a reintroduced caller would write has to fail.

    ``find_spec`` returns the cached spec for a name already in ``sys.modules``,
    even after its file is gone, so this only proves the deletion when nothing
    earlier in the session imported one of these names. Nothing in the tree
    imports them now; ``test_nothing_stands_at_any_removed_path`` is the check
    that does not depend on that.
    """
    resolvable = [name for name in _REMOVED_MODULES if importlib.util.find_spec(name) is not None]
    assert not resolvable, f"still importable: {resolvable}"
