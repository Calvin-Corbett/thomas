from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
CSS = ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "marketplace-workspace.css"
RENDERER = RUNTIME / "036_workbench_editors_08.js"
ELIGIBILITY = ROOT / "docs" / "MARKETPLACE_VISIBLE_ELIGIBILITY.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_marketplace_registers_live_regions_with_stable_edit_contracts() -> None:
    state = _read(RUNTIME / "025_module_system_command_center_01.js")
    lifecycle = _read(RUNTIME / "037_workbench_editors_09.js")
    scoped_runtime = "\n".join(
        _read(RUNTIME / name)
        for name in (
            "025_module_system_command_center_01.js",
            "026_module_system_command_center_02.js",
            "027_module_system_command_center_03.js",
            "028_module_system_command_center_04.js",
        )
    )

    for semantic_id in (
        "marketplace.shell",
        "marketplace.identity",
        "marketplace.header",
        "marketplace.controls",
        "marketplace.search",
        "marketplace.filters",
        "marketplace.status",
        "marketplace.detail",
        "marketplace.catalog",
        "marketplace.package",
        "marketplace.package.action",
    ):
        assert semantic_id in state

    assert "data-ui-instance-key" in state
    assert "data-ui-group" in state
    assert "items-runtime-owned" in state
    assert "preserve-runtime-ids,preserve-handlers" in state
    assert "protected live-record" in state
    assert "protected control" in state
    assert "thomas-eyes-mark marketplace-eyes-mark" in state
    assert "moduleApplyMarketplaceUiContracts(moduleRenderMarketplaceSurface(moduleQueueList));" in lifecycle
    assert "moduleObserveMarketplaceUiContracts" not in scoped_runtime
    assert "__thomasMarketplaceUiContractObserver" not in scoped_runtime
    assert "new MutationObserver(schedule)" not in scoped_runtime
    assert "window.requestAnimationFrame(apply)" not in scoped_runtime
    assert "data-ui-workspace', 'marketplace" in state


def test_marketplace_uses_chat_tokens_and_has_no_normal_editor_chrome() -> None:
    css = _read(CSS)
    modern = css.split("/* Marketplace modernization:", maxsplit=1)[1]

    assert '#moduleWorkspace[data-mode="marketplace"]' in modern
    for token in (
        "--c-surface",
        "--c-surface-2",
        "--c-border",
        "--c-border-2",
        "--c-text",
        "--c-dim",
        "--c-muted",
        "--c-accent",
        "--c-accent-soft",
        "--c-accent-line",
        "--font-sans",
        "--font-label",
    ):
        assert f"var({token}" in modern
    assert '"Manrope"' in modern
    assert ".marketplace-eyes-mark" not in modern
    assert "@media (max-width: 760px)" in modern
    assert "@media (prefers-reduced-motion: reduce)" in modern
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", modern)
    assert "ui-edit-toolbar" not in modern
    assert "Edit UI" not in modern
    assert 'background:transparent!important' in modern
    assert ':is(.module-marketplace-shell,.module-marketplace-stream)' in modern


def test_marketplace_coalesces_fetches_without_weakening_install_security() -> None:
    state = _read(RUNTIME / "025_module_system_command_center_01.js")

    assert "if (state.marketplace.refreshPromise)" in state
    assert "if (state.marketplace.installedRefreshPromise)" in state
    assert "state.marketplace.refreshSucceeded === true" in state
    assert "if (state.marketplace.refreshSucceeded)" in state
    assert "state.marketplace.catalogChanged = nextCatalogSignature" in state
    assert "if (state.marketplace.catalogChanged)" in state
    assert "'/api/marketplace/sync?limit=600'" in state
    assert "`/api/marketplace/sync?limit=600&store=${encodeURIComponent(preferredStoreUrl)}`" in state
    assert "`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/install`" in state
    assert "'/api/marketplace/install-from-deep-link'" in state
    assert "`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/uninstall`" in state
    assert "`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/${action}`" in state
    assert "'/api/marketplace/import'" in state
    assert "mock" not in state.lower()
    assert "fake listing" not in state.lower()


def test_marketplace_uses_editorial_shelves_without_hiding_real_catalog_actions() -> None:
    renderer = _read(RENDERER)

    for contract in (
        'class="marketplace-card marketplace-product-card',
        'class="marketplace-feature-wrap${',
        'class="marketplace-shelf"',
        'class="marketplace-shelf-rail"',
        'class="marketplace-results-grid"',
        'class="marketplace-selected-strip"',
        'data-ui-id="marketplace.feature"',
        'data-ui-id="marketplace.shelf"',
        'data-ui-id="marketplace.shelf.items"',
        'data-ui-id="marketplace.package.art"',
        'data-ui-group="marketplace.shelves"',
        'data-ui-policy="move resize ai-edit"',
        'data-module-marketplace-select=',
        'data-module-marketplace-filter=',
        'data-module-marketplace-search',
        'data-module-marketplace-refresh',
        'data-marketplace-import',
    ):
        assert contract in renderer

    assert "const featuredApp = browseMode ? rankApps(activePool)" in renderer
    assert ").slice(0, 8);" in renderer
    assert ").filter(Boolean).slice(0, 4);" in renderer
    assert "const resultLimit = activeFilter === 'all' ? 120 : 80;" in renderer
    assert "apps.filter((app)" in renderer
    assert "buildPrimaryAction(app)" in renderer
    assert "buildSecondaryActions(app)" in renderer
    assert "renderActionButton(app, primaryAction" in renderer
    assert "mock" not in renderer.lower()
    assert "fake listing" not in renderer.lower()


def test_marketplace_main_store_is_evidence_gated_and_potential_is_quarantined() -> None:
    renderer = _read(RENDERER)
    policy = _read(ELIGIBILITY)

    for contract in (
        "const marketplaceEvidence = (app)",
        "const signedInstall = Boolean(app?.installable && app?.compatibility?.eligible)",
        "const trustedDownload = Boolean(app?.download_available && downloadUrl)",
        "const verifiedApps = apps.filter((app) => marketplaceEvidence(app).verified)",
        "const potentialApps = apps.filter((app) => !marketplaceEvidence(app).verified)",
        "const activePool = potentialMode ? potentialApps : verifiedApps",
        "No packages have proven operating evidence yet.",
        "Potential · local review only",
        "No verified install",
    ):
        assert contract in renderer

    assert "Verified Store" in policy
    assert "hooks.py" in policy
    assert "is not operating evidence" in policy
    assert "481 Potential" in policy
    assert "not copied into a committed replacement catalog" in policy
    assert "destructively deleted" in policy


def test_marketplace_has_deterministic_iconography_and_interactive_carousels() -> None:
    renderer = _read(RENDERER)
    css = _read(CSS)

    for token in (
        "categoryIconMap",
        "ph-bell-ringing",
        "ph-chart-line-up",
        "ph-shield-warning",
        "ph-credit-card",
        "ph-discord-logo",
        "marketplace-icon-secondary",
        "data-marketplace-carousel=",
        "data-marketplace-carousel-target=",
        "rail.scrollBy({",
        "prefers-reduced-motion: reduce",
    ):
        assert token in renderer or token in css

    assert "return /^ph-[a-z0-9-]+$/i.test(value) ? value : 'ph-puzzle-piece'" not in renderer
    assert ".marketplace-carousel-btn" in css


def test_marketplace_editorial_layout_remains_responsive_and_keyboard_visible() -> None:
    css = _read(CSS)
    modern = css.split("/* Marketplace modernization:", maxsplit=1)[1]

    for selector in (
        ".marketplace-feature-wrap",
        ".marketplace-shelf-rail",
        ".marketplace-product-card",
        ".marketplace-card-hit:focus-visible",
        ".marketplace-results-grid",
        ".marketplace-selected-strip",
        ".marketplace-store-empty",
    ):
        assert selector in modern
    assert "overflow-x:auto" in modern
    assert "scroll-snap-type:inline proximity" in modern
    assert "@media (max-width: 1000px)" in modern
    assert "@media (max-width: 760px)" in modern


def test_marketplace_scoped_files_stay_within_guardrail_limits() -> None:
    limits = {
        RUNTIME / "025_module_system_command_center_01.js": 1500,
        RUNTIME / "026_module_system_command_center_02.js": 1500,
        RUNTIME / "027_module_system_command_center_03.js": 1500,
        RUNTIME / "028_module_system_command_center_04.js": 1500,
        CSS: 1600,
    }
    for path, hard_limit in limits.items():
        assert len(_read(path).splitlines()) <= hard_limit, path
